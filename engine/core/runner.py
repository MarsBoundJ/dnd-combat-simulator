"""Encounter runner — drives an encounter to termination.

Two operating modes (per docs/architecture/schema-design.md §1 +
docs/CONTEXT.md):

  - **Sim mode**: engine drives every decision via the decision pipeline.
    Stage 1 internal grading runs.
  - **Observation mode**: external driver (Foundry bridge, future)
    feeds events via EventBus.emit; engine records and runs handlers
    but doesn't decide. Phase 2+ work.

This skeleton implements sim mode. Observation mode is enabled by the
EventBus design — Foundry bridge just calls `bus.emit()` instead of
`runner.tick()`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from engine.core.events import EventBus
from engine.core.state import Actor, Encounter, CombatState
from engine.core import pipeline, modifiers
from engine.primitives import PrimitiveRegistry, remove_condition


# Safety cap — don't loop forever if termination logic has a bug
MAX_ROUNDS = 50


# Built-in Dodge action used as the PC fallback when RP hard filters
# empty the candidate set. Per pillars-reconciliation.md §6.4:
#   "Guaranteed-legal fallback when candidate set drops to zero:
#    PCs default to Dodge; Monsters default to Pass turn."
# Sourced from engine.core.basic_actions (same constant that the
# candidate generator uses for built-in availability — see PR #29).
from engine.core.basic_actions import BUILT_IN_DODGE as _BUILT_IN_DODGE_ACTION


@dataclass
class EncounterRunner:
    encounter: Encounter
    event_bus: EventBus
    primitives: PrimitiveRegistry
    rng: random.Random
    content_registry: Any = None        # ContentRegistry from engine.loader

    @classmethod
    def new(cls, encounter: Encounter, seed: int | None = None,
            content_registry: Any = None) -> "EncounterRunner":
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        rng = random.Random(seed) if seed is not None else random.Random()
        return cls(encounter=encounter, event_bus=bus, primitives=prims,
                    rng=rng, content_registry=content_registry)

    def roll_initiative(self, state: CombatState) -> None:
        """Roll initiative for every actor; sort descending; resolve ties by DEX."""
        rolls: list[tuple[int, int, str]] = []  # (init_roll, dex_mod_tiebreak, actor_id)
        for a in self.encounter.actors:
            init_mod = a.template.get("combat", {}).get("initiative", {}).get("modifier", 0)
            dex_mod = a.abilities.get("dex", {}).get("save", 0)
            roll = self.rng.randint(1, 20) + init_mod
            a.initiative = roll
            rolls.append((roll, dex_mod, a.id))
        rolls.sort(key=lambda x: (-x[0], -x[1]))
        state.turn_order = [r[2] for r in rolls]
        state.event_log.append({"event": "initiative_rolled",
                                "order": [(a.id, a.initiative) for a in self.encounter.actors]})

    def check_termination(self, state: CombatState) -> bool:
        """Encounter ends when one side has no living actors, or round cap hit."""
        sides = state.living_actors_by_side()
        if len(sides) <= 1:
            state.terminated = True
            if sides:
                winning_side = next(iter(sides.keys()))
                state.termination_reason = f"side_{winning_side}_victory"
            else:
                state.termination_reason = "mutual_destruction"
            return True
        if state.round > MAX_ROUNDS:
            state.terminated = True
            state.termination_reason = "round_cap_reached"
            return True
        return False

    def tick(self, state: CombatState) -> None:
        """Run one turn of the current actor, then advance turn order."""
        actor = state.current_actor()
        if actor is None or not actor.is_alive():
            state.advance_turn()
            return

        # Reset per-turn state + expire turn-start modifiers
        actor.reset_turn()
        modifiers.expire_modifiers(actor, {"turn_start"})

        self.event_bus.emit("turn_start", {"actor": actor, "round": state.round})
        state.event_log.append({"event": "turn_start", "actor": actor.id, "round": state.round})

        # PR #43: persistent aura triggers (Spirit Guardians-shape).
        # Fires AFTER turn_start so the event log shows turn_start first,
        # then any aura damage. Skip if the actor died from the aura
        # (the run_actor_turn check below will catch it again).
        self._resolve_persistent_aura_triggers(actor, state)

        # Run the 8-step decision pipeline
        if actor.is_alive():
            self._run_actor_turn(actor, state)

        # Resolve any recurring saves registered against this actor's turn_end
        self._resolve_recurring_saves(actor, state)

        self.event_bus.emit("turn_end", {"actor": actor, "round": state.round})
        state.event_log.append({"event": "turn_end", "actor": actor.id,
                                "hp_remaining": actor.hp_current})

        state.advance_turn()

    def _maybe_activate_action_surge(self, actor: Actor,
                                       state: CombatState) -> None:
        """Decide whether `actor` activates Action Surge this turn.

        Per RAW (2024 PHB): Fighter feature, 1/short-rest (2/short-rest
        at L17 but still only once per turn). Grants one additional
        action this turn (not a Magic action — v1 ignores the
        spell-action gating since we don't yet distinguish Magic
        actions from other actions).

        Activation gates (PR #31 + PR #42):
          1. Actor has `action_surge_uses_remaining` > 0 in resources
          2. Not already activated this turn (L17 cap)
          3. At least one enemy is alive
          4. At least one in-reach weapon_attack / multiattack candidate
             exists this turn (otherwise the extra action would be
             wasted)
          5. **Pace-aware gain-vs-cost check (PR #42):** score the best
             in-reach attack candidate via the eHP framework; compute
             the AS opportunity cost from `state.encounters_remaining_today`
             via `action_surge_cost_ehp`. Activate only if gain > cost.

        Side effects when activated:
          - Decrements `actor.resources["action_surge_uses_remaining"]`
          - Sets `actor.action_surge_used_this_turn = True`
          - Logs `action_surge_activated` event with gain / cost / charges
        """
        charges = int(actor.resources.get("action_surge_uses_remaining", 0))
        if charges <= 0:
            return
        if actor.action_surge_used_this_turn:
            return     # already fired this turn (e.g., L17 fighter
                       # cannot AS twice in one turn even with 2 charges)

        # Any living enemy?
        enemies_alive = any(a.side != actor.side and a.is_alive()
                              for a in state.encounter.actors)
        if not enemies_alive:
            return

        # In-reach attack candidate available now?
        candidates = pipeline.generate_candidates(actor, state, slot="action")
        attack_candidates = [c for c in candidates
                              if c.get("kind") in ("weapon_attack",
                                                    "multiattack")]
        if not attack_candidates:
            return

        # Pace-aware: weigh expected gain (eHP of best attack candidate)
        # against the opportunity cost of spending an AS charge now.
        # encounters_remaining_today on the state drives the urgency
        # factor — session runners pass per-encounter values; single-
        # encounter sims default to mid-day (3).
        from engine.ai.ehp_scoring import score_candidate
        from engine.core.feature_pacing import action_surge_cost_ehp
        best_gain = max(score_candidate(c, state) for c in attack_candidates)
        cost = action_surge_cost_ehp(
            charges_remaining=charges,
            encounters_remaining=state.encounters_remaining_today,
        )
        if best_gain <= cost:
            return     # save the charge for a more impactful moment

        # Activate
        actor.resources["action_surge_uses_remaining"] = charges - 1
        actor.action_surge_used_this_turn = True
        state.event_log.append({
            "event": "action_surge_activated",
            "actor": actor.id,
            "charges_remaining": charges - 1,
            "gain_eHP": round(best_gain, 2),
            "cost_eHP": round(cost, 2),
        })

    def _move_to_engage(self, actor: Actor, state: CombatState) -> None:
        """Move actor toward the dial-preferred enemy up to walk speed.

        Greedy v1: pick the targeting dial's preferred enemy (the same
        one the AI would target if it could act), step toward them up
        to `speed.walk` feet. No kiting / hold-at-range optimization —
        ranged attackers will close to melee if they have no in-range
        options after closing.

        Logs `moved` event with from/to positions and distance.

        RAW gives one move per turn. If `actor.moved_this_turn` is
        already True, return without moving — the Action Surge second
        action does not grant a second move (Action Surge grants an
        extra action, not extra movement). See `_run_actor_turn`.
        """
        if actor.moved_this_turn:
            return
        from engine.core.geometry import move_toward, distance_ft
        from engine.ai.behavior_profile import resolve_targeting_preset
        from engine.ai.targeting import pick_target

        enemies = [a for a in state.encounter.actors
                    if a.side != actor.side and a.is_alive()]
        if not enemies:
            return
        preset = resolve_targeting_preset(actor)
        target = pick_target(actor, enemies, state, preset)
        if target is None:
            return

        speed_ft = int((actor.speed or {}).get("walk", 30))
        if speed_ft <= 0:
            return

        # Stop at the actor's MAX reach across their attack actions so
        # they land in range to act, not stacked on the target's square.
        # Defaults to 5 ft (melee) if no actions found.
        from engine.core.pipeline import _action_reach_ft
        reaches = [_action_reach_ft(a) for a in (actor.template.get("actions") or [])
                    if a.get("type") in ("weapon_attack", "hard_control")]
        stop_at = max(reaches) if reaches else 5

        from_pos = actor.position
        from_dist = distance_ft(actor, target)
        moved_ft = move_toward(actor, target, speed_ft, stop_at_ft=stop_at)
        if moved_ft <= 0:
            return
        actor.moved_this_turn = True
        state.event_log.append({
            "event": "moved",
            "actor": actor.id,
            "from": list(from_pos),
            "to": list(actor.position),
            "ft": moved_ft,
            "toward": target.id,
            "distance_before": from_dist,
            "distance_after": distance_ft(actor, target),
        })

        # Trigger opportunity attacks from any enemy whose melee reach
        # the mover just left. The mover may take damage / drop here;
        # subsequent `_run_slot` candidate generation will see
        # actor.is_alive() == False and skip cleanly.
        from engine.core import reactions
        reactions.resolve_opportunity_attacks(
            actor, from_pos, state,
            self.event_bus, self.primitives, self.rng,
        )

    def _resolve_persistent_aura_triggers(self, actor: Actor,
                                              state: CombatState) -> None:
        """Fire registered persistent_aura triggers at this actor's
        turn-start (PR #43 + PR #44).

        For each aura with `trigger_event == 'target_turn_start_in_area'`:
          - Skip if the caster is dead / fled / not in the encounter
          - Skip if `actor` doesn't satisfy `affected` filter (default
            'enemies' skips same-side; 'all_creatures' includes
            everyone — used by spells without RAW exclusion like Cloud
            of Daggers / Sickening Radiance).
          - Compute the aura's current origin:
            - `anchor='caster'` (Spirit Guardians) → caster.position
            - `anchor='point'` (Moonbeam, CoD) → aura['origin']
              (recorded at cast time, doesn't move)
          - Skip if `actor` is outside the area (sphere → radius_ft;
            cube → size_ft via actors_in_cube).
          - If the aura has a save (`ability` is not None): set up
            forced_save context and invoke. forced_save handles the
            roll + on_fail / on_success branching.
          - If no save (Cloud of Daggers-shape): invoke on_fail
            sub-primitives directly (always-damage).
        """
        if not state.persistent_auras:
            return
        from engine.core.geometry import distance_ft, actors_in_cube
        for aura in state.persistent_auras:
            if aura.get("trigger_event") != "target_turn_start_in_area":
                continue
            caster = state._actor_by_id(aura["caster_id"])
            if caster is None or not caster.is_alive():
                continue
            # Affected gate — see method docstring
            if aura.get("affected", "enemies") == "enemies" \
                    and actor.side == caster.side:
                continue
            # Resolve current origin based on anchor type
            anchor = aura.get("anchor", "caster")
            if anchor == "point":
                origin = aura.get("origin") or tuple(caster.position)
            else:
                origin = tuple(caster.position)
            # Area check — sphere uses radius, cube uses size
            shape = aura.get("shape", "sphere")
            if shape == "cube":
                size_ft = int(aura.get("size_ft", 0))
                in_area = actors_in_cube(origin, size_ft, [actor])
                if not in_area:
                    continue
            else:
                radius_ft = int(aura.get("radius_ft", 0))
                if distance_ft(actor.position, origin) > radius_ft:
                    continue
            # Set up trigger context: caster is the "actor", the
            # turn-taking creature is the "target". area_origin
            # propagates so any AoE-aware sub-primitives can reference it.
            saved_attack = state.current_attack
            state.current_attack = {
                "actor": caster, "target": actor,
                "action": {"id": aura["action_id"],
                            "named_effect": aura.get("named_effect")},
                "state": None,
                "had_advantage": False, "had_disadvantage": False,
                "area_origin": tuple(origin), "area_direction": None,
            }
            try:
                if aura.get("ability") is None:
                    # No-save path: invoke on_fail sub-primitives
                    # directly (always damages). Cloud of Daggers,
                    # Sleet Storm-class spells.
                    from engine.primitives import _invoke_subprimitive
                    for sub in aura["on_fail"] or []:
                        _invoke_subprimitive(sub, state, self.event_bus)
                    state.event_log.append({
                        "event": "persistent_aura_no_save_trigger",
                        "target": actor.id,
                        "action": aura["action_id"],
                    })
                else:
                    # Save-based: invoke forced_save with the aura's
                    # params; on_fail / on_success branching handled there.
                    self.primitives.invoke("forced_save", {
                        "ability": aura["ability"],
                        "dc": aura["dc"],
                        "affected": "current_target",
                        "on_fail": aura["on_fail"],
                        "on_success": aura["on_success"],
                    }, state, self.event_bus)
            finally:
                state.current_attack = saved_attack
            # If the actor died from the aura, stop processing further
            # auras on them this turn (defensive).
            if not actor.is_alive():
                break

    def _resolve_recurring_saves(self, actor: Actor, state: CombatState) -> None:
        """At actor's turn_end, roll any recurring saves registered against them.

        Used by Hold Person etc.: target re-rolls save at end of its turn; on
        success, end the source condition.
        """
        if not state.recurring_saves:
            return
        remaining: list = []
        for entry in state.recurring_saves:
            if entry.get("target_id") != actor.id:
                remaining.append(entry)
                continue
            if entry.get("trigger_event") != "target_turn_end":
                remaining.append(entry)
                continue
            # Roll the save
            from engine.core.state import ability_modifier as _am
            ability = entry.get("ability", "wisdom")
            short_ab = {"strength": "str", "dexterity": "dex", "constitution": "con",
                         "intelligence": "int", "wisdom": "wis", "charisma": "cha"}.get(ability, ability)
            save_mods = modifiers.query_save_modifiers(actor, ability, state)
            override = save_mods.net_outcome_override()
            if override == "auto_fail":
                outcome = "fail"
                d20, total = None, None
            elif override == "auto_succeed":
                outcome = "success"
                d20, total = None, None
            else:
                save_bonus = actor.abilities.get(short_ab, {}).get("save", 0)
                adv_state = save_mods.net_advantage()
                if adv_state == "advantage":
                    d20 = max(self.rng.randint(1, 20), self.rng.randint(1, 20))
                elif adv_state == "disadvantage":
                    d20 = min(self.rng.randint(1, 20), self.rng.randint(1, 20))
                else:
                    d20 = self.rng.randint(1, 20)
                total = d20 + save_bonus + save_mods.save_bonus_modifier
                outcome = "success" if total >= entry["dc"] else "fail"
            state.event_log.append({
                "event": "recurring_save", "target": actor.id,
                "ability": ability, "dc": entry["dc"],
                "d20": d20, "total": total, "outcome": outcome,
                "for_condition": entry.get("condition_id"),
            })
            if outcome == "success" and entry.get("on_success") == "end_spell_on_target":
                # End the source condition on this target
                if entry.get("condition_id"):
                    remove_condition(actor, entry["condition_id"], entry.get("source_id"))
                # Don't re-register this entry (spell ended)
                continue
            # Save failed (or no end-on-success) — keep the entry for next turn
            remaining.append(entry)
        state.recurring_saves = remaining

    def _run_actor_turn(self, actor: Actor, state: CombatState) -> None:
        """Execute one actor's turn via the decision pipeline.

        Two slots per turn (Action + Bonus Action). Reactions are
        triggered, not turn-scheduled — deferred to a future PR.

        Action Surge: if the actor has the feature + charges and
        passes the activation heuristic, fires BEFORE the main slot
        and grants a second main-slot pass AFTER the bonus slot. RAW
        gives the second action, not extra movement or a second bonus
        action — the runner suppresses double-moves via
        `actor.moved_this_turn` and only re-runs the main slot.
        """
        # Step 0: resolve effective profile
        profile = pipeline.resolve_effective_profile(actor, state)
        # Step 1: retreat trigger — DMG p48 algorithm; if triggered, the
        # actor flees this turn and the rest of the pipeline is skipped.
        retreat = pipeline.check_retreat_trigger(actor, state, rng=self.rng)
        if retreat:
            actor.is_fled = True
            state.event_log.append({
                "event": "fled", "actor": actor.id,
                "preset": retreat.get("preset"),
                "triggers": retreat.get("triggers"),
            })
            return

        # ---- Action Surge: pre-action activation check ----
        # Decision fires once, before the main slot. If activated, the
        # `action_surge_used_this_turn` flag is set; the post-bonus-slot
        # check below re-runs the main slot once.
        self._maybe_activate_action_surge(actor, state)

        # ---- Main slot ----
        self._run_slot(actor, state, slot="action")

        # ---- Bonus slot ----
        # Skip if the main slot killed the actor or terminated the encounter.
        if actor.is_alive() and not state.terminated:
            self._run_slot(actor, state, slot="bonus_action")

        # ---- Action Surge: second main slot ----
        # Only runs if AS was activated this turn AND actor is still
        # alive AND encounter not terminated. Resets the main-slot
        # usage flag so `apply_action_economy` and downstream logic
        # treat this as a fresh action. Movement remains gated by
        # `moved_this_turn` so the actor can't move twice.
        if (actor.action_surge_used_this_turn
                and actor.is_alive() and not state.terminated):
            actor.actions_used_this_turn["action"] = False
            self._run_slot(actor, state, slot="action")

    def _run_slot(self, actor: Actor, state: CombatState, slot: str) -> None:
        """Execute one turn slot (action or bonus_action) via the
        candidate-scoring pipeline. The Action Economy dial gates:

          - Main slot: optimality roll may downgrade the chosen action
            to the actor's default attack.
          - Bonus slot: per-action signature/tactical rate may skip the
            slot entirely.
        """
        candidates = pipeline.generate_candidates(actor, state, slot=slot)

        # Movement phase (main slot only): if no in-range candidates,
        # close on the dial-preferred enemy up to speed and try again.
        # Bonus slot doesn't move (movement is a main-slot resource).
        if not candidates and slot == "action":
            self._move_to_engage(actor, state)
            # Movement may have triggered OAs that dropped the actor —
            # skip cleanly if so.
            if not actor.is_alive():
                return
            candidates = pipeline.generate_candidates(actor, state, slot=slot)
            if not candidates:
                state.event_log.append({
                    "event": "passed_turn",
                    "actor": actor.id,
                    "slot": slot,
                    "reason": "out_of_range_after_movement",
                })
                return

        if not candidates:
            return
        pre_filter_count = len(candidates)
        candidates = pipeline.apply_hard_filters(candidates, actor, state)
        # §6.4 guaranteed-legal fallback: if hard filters emptied the set
        # (e.g., pacifist_strict on a creature with only attack actions),
        # PCs default to Dodge (RAW); monsters default to Pass turn.
        # Only applies to the main slot (Dodge is a main-action thing).
        if not candidates and pre_filter_count > 0:
            if actor.side == "pc" and slot == "action":
                # Execute the built-in Dodge action. The defensive
                # modifiers attach via the existing pipeline.
                fallback_chosen = {
                    "kind": "defensive_buff",
                    "actor": actor,
                    "target": actor,
                    "action": _BUILT_IN_DODGE_ACTION,
                }
                state.event_log.append({
                    "event": "dodge_fallback",
                    "actor": actor.id,
                    "slot": slot,
                    "reason": "rp_hard_filter_empty_set",
                })
                pipeline.execute(fallback_chosen, state, self.event_bus,
                                  self.primitives)
                return
            state.event_log.append({
                "event": "passed_turn",
                "actor": actor.id,
                "slot": slot,
                "reason": "rp_hard_filter_empty_set",
            })
            return
        candidates = pipeline.apply_forced_choices(candidates, actor, state)
        scored = pipeline.score_candidates(candidates, actor, state)
        chosen = pipeline.select_max(scored)
        if chosen is None:
            return

        if slot == "action":
            # Main slot: optimality roll may swap to default attack.
            chosen = pipeline.apply_action_economy(actor, chosen, state,
                                                     rng=self.rng)
        else:
            # Bonus slot: roll whether to use it at all (per signature /
            # tactical rate of the chosen bonus action).
            from engine.ai.action_economy import should_use_bonus_action
            if not should_use_bonus_action(actor, chosen["action"], self.rng):
                state.event_log.append({"event": "bonus_action_skipped",
                                          "actor": actor.id,
                                          "candidate": chosen["action"].get("id")})
                return

        pipeline.execute(chosen, state, self.event_bus, self.primitives)
        if chosen.get("downgraded_from"):
            state.event_log.append({"event": "action_downgraded",
                                      "actor": actor.id,
                                      "from": chosen["downgraded_from"],
                                      "to": chosen["action"].get("id")})

    def run(self, seed: int | None = None,
            encounters_remaining_today: int = 3) -> CombatState:
        """Run the encounter to termination. Returns final CombatState.

        `encounters_remaining_today` (default 3 = mid-day baseline)
        feeds the pace-aware AI: spell-slot opportunity cost (PR #22)
        and Action Surge activation gate (PR #42) both consult it.
        Session runners pass per-encounter values so the AI sees
        urgency decrease across the day. Single-encounter sims use
        the default.
        """
        if seed is not None:
            self.rng = random.Random(seed)
        state = CombatState(
            encounter=self.encounter,
            content_registry=self.content_registry,
            encounters_remaining_today=encounters_remaining_today,
        )
        self.event_bus.emit("round_start", {"round": 1})
        self.roll_initiative(state)
        state.round = 1
        while not state.terminated:
            self.tick(state)
            if state.current_turn_idx == 0:
                # round boundary
                self.event_bus.emit("round_end", {"round": state.round - 1})
                self.event_bus.emit("round_start", {"round": state.round})
            if self.check_termination(state):
                break
        return state


def run_encounter(encounter: Encounter, seed: int | None = None) -> CombatState:
    """Convenience: build a runner and execute one encounter."""
    runner = EncounterRunner.new(encounter, seed=seed)
    return runner.run(seed=seed)
