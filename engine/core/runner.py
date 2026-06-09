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

# Minimum optimization dial at which an enemy will MOVE to improve its area
# attack's coverage (the "breath chase", `_maybe_reposition_for_aoe`). Below
# this, the monster still AIMS its cone optimally from where it stands (that's
# coverage-aware candidate generation, always on) but won't relocate the apex —
# modelling the WoTC-baseline design intent of deliberately under-optimized AoE
# (~2 PCs per breath, anti-party-wipe). 3 = "above the dial-1/2 floor".
AOE_CHASE_MIN_DIAL = 3


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
        """Roll initiative for every actor; sort descending; resolve ties by DEX.

        PR #95: Initiative is a DEX ability check per PHB 2024 — Halfling
        Lucky applies. `lucky_d20` is a no-op for non-Halflings, so the
        call is cheap.
        """
        from engine.core.racial_traits import lucky_d20
        rolls: list[tuple[int, int, str]] = []  # (init_roll, dex_mod_tiebreak, actor_id)
        for a in self.encounter.actors:
            init_mod = a.template.get("combat", {}).get("initiative", {}).get("modifier", 0)
            # Jack of All Trades (Bard L2): add half Proficiency Bonus (round
            # down) to initiative — a DEX ability check the Bard isn't
            # proficient in. No-op for everyone else.
            features = a.template.get("features_known") or []
            if "f_jack_of_all_trades" in features:
                pb = int((a.template.get("cr") or {}).get(
                    "proficiency_bonus", 2))
                init_mod += pb // 2
            dex_mod = a.abilities.get("dex", {}).get("save", 0)
            d20 = self.rng.randint(1, 20)
            d20, _rerolled = lucky_d20(self.rng, d20, a)
            roll = d20 + init_mod
            a.initiative = roll
            rolls.append((roll, dex_mod, a.id))
            # Superior Inspiration (Bard L18): when you roll Initiative,
            # regain expended Bardic Inspiration uses until you have two (if
            # you have fewer).
            if "f_superior_inspiration" in features:
                cur = int(a.resources.get(
                    "bardic_inspiration_uses_remaining", 0))
                if cur < 2:
                    a.resources["bardic_inspiration_uses_remaining"] = 2
                    state.event_log.append({
                        "event": "superior_inspiration",
                        "actor": a.id, "restored_to": 2})
        # Tandem Footwork (College of Dance L6): a Dance Bard may expend a
        # Bardic Inspiration use at initiative to roll its Bardic die and add
        # the result to its own + nearby allies' initiative. Applied after the
        # base rolls (it bumps a.initiative directly); the sort below reads
        # the updated values.
        from engine.core.college_of_dance import apply_tandem_footwork
        apply_tandem_footwork(self.encounter.actors, self.rng, state)
        rolls = [(a.initiative,
                  a.abilities.get("dex", {}).get("save", 0), a.id)
                 for a in self.encounter.actors]
        rolls.sort(key=lambda x: (-x[0], -x[1]))
        state.turn_order = [r[2] for r in rolls]
        state.event_log.append({"event": "initiative_rolled",
                                "order": [(a.id, a.initiative) for a in self.encounter.actors]})

    def check_termination(self, state: CombatState) -> bool:
        """Encounter ends when one side has no living actors, or round cap hit."""
        sides = state.living_actors_by_side()
        # A Troll-rule regenerator downed at 0 HP isn't dead yet — it
        # revives at its next turn start unless it took acid/fire. Keep its
        # side "in the fight" so a solo troll's encounter doesn't end the
        # instant it's dropped to 0 (it must actually be burned down).
        from engine.core import regeneration as _regeneration
        for a in state.encounter.actors:
            if _regeneration.is_pending(a):
                sides.setdefault(a.side, [])
                if a not in sides[a.side]:
                    sides[a.side].append(a)
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
        # Regeneration resolves at the very start of the creature's turn —
        # BEFORE the is_alive gate, so a Troll-rule regenerator downed at 0
        # HP gets its revive-or-die resolution (a revived troll then takes
        # its turn; one that took acid/fire dies and is skipped). Normal
        # regenerators heal here too. No-op for non-regenerators.
        if actor is not None:
            from engine.core import regeneration as _regeneration
            _regeneration.resolve_turn_start(actor, state)
            # Death saves resolve at the start of a dying PC's turn — BEFORE
            # the is_alive gate (a dying actor is is_alive False and would
            # otherwise be skipped without ever rolling). 3 successes -> stable,
            # 3 failures -> dead, nat 20 -> revive at 1 HP and take a turn.
            from engine.core import death_saves as _death_saves
            _death_saves.resolve_turn_start(actor, state, self.rng)
        if actor is None or not actor.is_alive():
            state.advance_turn()
            return

        # Reset per-turn state + expire turn-start modifiers
        actor.reset_turn()
        modifiers.expire_modifiers(actor, {"turn_start"})

        # PR #92: source-caster-driven expiration. Modifiers tagged
        # with lifetime `until_source_caster_next_turn` (Help, future
        # Bardic Inspiration-shape buffs) expire at the SOURCE
        # CASTER's turn-start, not the owner's. The standard
        # expire_modifiers above only scans `actor`'s own modifiers;
        # this scrub walks every actor's modifiers and removes those
        # whose source.caster_id matches the current actor (i.e.,
        # "Help I cast on the Fighter expires now that MY turn has
        # come back around"). See engine.core.modifiers.scrub_source_
        # caster_turn_start_modifiers for the helper.
        modifiers.scrub_source_caster_turn_start_modifiers(
            actor.id, state)

        # Source-timed conditions (Monk Stunning Strike's Stunned, etc.)
        # expire at the start of the source actor's next turn. Remove the
        # condition from each target + drop the tracking entry.
        if state.timed_conditions:
            from engine.primitives import remove_condition
            still_pending = []
            for entry in state.timed_conditions:
                if entry.get("source_id") == actor.id:
                    tgt = state._actor_by_id(entry.get("target_id"))
                    if tgt is not None:
                        remove_condition(tgt, entry.get("condition_id"),
                                          entry.get("source_id"))
                        state.event_log.append({
                            "event": "timed_condition_expired",
                            "target": entry.get("target_id"),
                            "condition": entry.get("condition_id"),
                            "source": actor.id})
                else:
                    still_pending.append(entry)
            state.timed_conditions = still_pending

        # PR #86: forward the readied-action discard event from
        # reset_turn. Actor.reset_turn clears `readied_action` but
        # stashes the discarded entry on a sentinel attr; we log it
        # here in the runner where we have a state reference. The
        # event records why the Ready was wasted (no trigger fired
        # before next turn).
        discarded = getattr(actor, "_ready_discarded_this_reset", None)
        if discarded:
            state.event_log.append({
                "event": "ready_action_discarded",
                "actor": actor.id,
                "sub_action": discarded.get("action_id"),
                "trigger": discarded.get("trigger"),
                "reason": "turn_start",
                "round": state.round,
            })
            actor._ready_discarded_this_reset = None

        # PR #58: expire Slow weapon-mastery effects whose source is
        # the actor whose turn is starting. Slow says "until start of
        # actor's next turn" — when that turn begins, slowed creatures
        # the actor previously slowed get their speed back.
        from engine.core.weapon_masteries import expire_slow_from_source
        expire_slow_from_source(actor.id, state)

        self.event_bus.emit("turn_start", {"actor": actor, "round": state.round})
        state.event_log.append({"event": "turn_start", "actor": actor.id, "round": state.round})

        # Recharge abilities (monster Breath Weapon / Web / Boulder Toss).
        # At the start of the creature's turn, roll a d6 for each spent
        # die-based recharge ability; one whose roll lands in range becomes
        # available again this turn. Fires right after turn_start so the
        # ability is back in the candidate pool when the turn's actions are
        # chosen below. See engine/core/recharge.py.
        from engine.core import recharge as _recharge
        _recharge.roll_recharges_at_turn_start(actor, state, self.rng)

        # Vitality of the Tree — Life-Giving Force (World Tree L3): at the
        # start of a raging World Tree barbarian's turn, grant an ally within
        # 10 ft Temp HP (Nd6, N = Rage Damage bonus). No-op for everyone else.
        from engine.core import world_tree as _world_tree
        _world_tree.resolve_life_giving_force(actor, state, self.rng)

        # Branches of the Tree (World Tree L6): first restore any walk Speed
        # that Branches reduced to 0 on this actor last turn, then let raging
        # World Tree barbarians react to this creature starting its turn
        # within 30 ft (STR save or teleport-pull adjacent + Speed 0). The
        # condition filters to enemies of each reactor, so allies'/own turn-
        # starts are no-ops.
        _world_tree.restore_branches_speed(actor, state)
        from engine.core.reactions import resolve_reaction_triggers as _rtrig
        _rtrig("creature_turn_start", {"mover": actor, "target": actor},
                state, self.event_bus)

        # Legendary Actions: a legendary creature regains all its uses at
        # the start of its turn. (Spent between other creatures' turns via
        # _resolve_legendary_actions.) See engine/core/legendary_actions.py.
        from engine.core import legendary_actions as _legendary_actions
        _legendary_actions.reset_budget(actor, state)

        # Swallow: a creature that has swallowed someone deals its ongoing
        # acid to the victim at the start of its turn. See
        # engine/core/swallow.py. Also reset the regurgitate damage
        # accumulator at a swallowed creature's turn start (it measures
        # damage-from-inside over this turn only).
        from engine.core import swallow as _swallow
        _swallow.tick(actor, state, self.primitives, self.event_bus)
        _swallow.reset_turn_damage(actor, state)

        # PR #43: persistent aura triggers (Spirit Guardians-shape).
        # Fires AFTER turn_start so the event log shows turn_start first,
        # then any aura damage. Skip if the actor died from the aura
        # (the run_actor_turn check below will catch it again).
        self._resolve_persistent_aura_triggers(actor, state)

        # PR #89: recurring damage ticks (Searing Smite burn; future
        # Heat Metal). Fires at the affected creature's turn-start.
        # Runs AFTER persistent_aura so ordering is consistent (auras
        # first, then per-creature ongoing damage).
        if actor.is_alive():
            self._resolve_recurring_damage(actor, state)

        # Recurring saves at turn-start (Searing Smite co_ignited:
        # target takes burn damage THEN makes CON save to end the
        # spell). Fires AFTER recurring_damage so the save is post-
        # damage per RAW.
        if actor.is_alive():
            self._resolve_recurring_saves(
                actor, state, trigger_event="target_turn_start")

        # PR #94: recurring temp HP grants (Heroism; future Aid-shape
        # spells). Dual of recurring damage. Fires at the affected
        # creature's turn-start, AFTER damage ticks so any damage
        # that would have wiped the temp HP this turn lands first.
        # (Net: recurring damage gets full benefit of the temp HP
        # from the PREVIOUS round's grant; the new grant happens
        # after the damage absorption.)
        if actor.is_alive():
            self._resolve_recurring_temp_hp(actor, state)

        # Run the 8-step decision pipeline
        if actor.is_alive():
            self._run_actor_turn(actor, state)

        # Resolve any recurring saves registered against this actor's turn_end
        self._resolve_recurring_saves(actor, state)

        # PR #71: Rage end-of-turn check. If the actor is raging AND
        # neither attacked a hostile nor took damage this turn, rage
        # ends per RAW. Skipped on the entry turn (the grace check
        # lives inside check_rage_end_of_turn).
        from engine.core.rage import check_rage_end_of_turn
        check_rage_end_of_turn(actor, state)

        self.event_bus.emit("turn_end", {"actor": actor, "round": state.round})
        state.event_log.append({"event": "turn_end", "actor": actor.id,
                                "hp_remaining": actor.hp_current})

        # Inspiring Movement (College of Dance L6): a Dance Bard may react to
        # an enemy ENDING its turn within 5 ft. Dispatched here at turn-end
        # (the twin of the turn-start trigger used by World Tree Branches).
        # The condition filters to enemies of each reactor, so allies'/own
        # turn-ends are no-ops.
        if actor.is_alive():
            from engine.core.reactions import resolve_reaction_triggers as _rt
            _rt("creature_turn_end", {"mover": actor, "target": actor},
                state, self.event_bus)

        # Swallow regurgitate: if `actor` is swallowed and dealt enough
        # damage to its swallower this turn, the swallower saves or expels
        # it (freed + Prone). Checked at the victim's turn end.
        from engine.core import swallow as _swallow_re
        _swallow_re.check_regurgitate(actor, state, self.primitives,
                                        self.event_bus)

        # Legendary Actions fire "immediately after another creature's
        # turn ends": every OTHER eligible legendary creature may spend
        # one use now. Skipped cleanly if the encounter terminated this
        # turn. See engine/core/legendary_actions.py.
        if not state.terminated:
            self._resolve_legendary_actions(actor, state)

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

    def _maybe_activate_reckless_attack(self, actor: Actor,
                                          state: CombatState) -> None:
        """Decide whether `actor` activates Reckless Attack this turn
        (PR #85).

        RAW (Barbarian L2, PHB 2024): a free declaration made at the
        first attack roll. The engine collapses this to a pre-action
        hook so the AI commits before the first swing — functionally
        identical for v1 since no engine code path lets the player
        un-decide mid-roll.

        Eligibility:
          1. Actor has `f_reckless_attack` in features_known
          2. Actor has at least one STR-melee weapon_attack action
          3. At least one enemy is alive
          4. Not already activated this turn

        Decision: delegates to `reckless_attack.should_activate`
        which applies archetype overrides (mindless / fanatic always
        commit; cowardly never) and otherwise compares expected DPR
        gain to expected incoming-damage cost.

        Side effects when activated:
          - Sets `actor.reckless_active = True`
          - Sets `actor.reckless_grants_advantage_until_next_turn = True`
          - Logs `reckless_attack_activated`

        When skipped, logs `reckless_attack_skipped` with the reason
        (eligibility / heuristic). Logging-only for non-Barbarians is
        suppressed (the `no_feature` reason fires every turn for every
        non-Barbarian and would flood the log).
        """
        from engine.core import reckless_attack as _ra
        activate, reason = _ra.should_activate(actor, state)
        if activate:
            _ra.activate(actor, state)
            return
        # Only log skips that are decision-meaningful — suppress the
        # non-Barbarian "no_feature" sentinel that fires every turn.
        if reason not in ("no_feature", "already_active"):
            state.event_log.append({
                "event": "reckless_attack_skipped",
                "actor": actor.id,
                "reason": reason,
            })

    def _maybe_aoe_decluster(self, actor: Actor, state: CombatState) -> bool:
        """AoE-aware safety reposition (Phase 1c-ii). If a living enemy has an
        area attack and this PC (with allies) can act from a SAFER square,
        step there. Returns True if it moved.

        Self-gated by `best_position` (returns None unless: an AoE threat
        exists, the PC has allies to de-cluster from, AND it can already act
        from a better-utility square). Crucially this is now run at TURN START
        for every PC — not only on the move-to-engage path — so a RANGED caster
        that already has an in-range target (and so never triggers move-to-
        engage) still steps out of the dragon's breath cone. A melee actor
        whose offense is position-locked won't flee: position_utility =
        offense - exposure, and losing its melee offense outweighs the breath,
        so only safely-repositionable actors actually move."""
        if actor.moved_this_turn or actor.side != "pc":
            return False
        from engine.ai.positioning import best_position
        from engine.core.geometry import distance_ft
        spread = best_position(actor, state)
        if spread is None:
            return False
        from_pos = actor.position
        actor.position = spread
        actor.moved_this_turn = True
        state.event_log.append({
            "event": "moved", "actor": actor.id,
            "from": list(from_pos), "to": list(spread),
            "ft": distance_ft(from_pos, spread),
            "reason": "aoe_spacing",
        })
        from engine.core import reactions
        reactions.resolve_opportunity_attacks(
            actor, from_pos, state, self.event_bus, self.primitives, self.rng)
        if actor.is_alive():
            from engine.core import ready_action as _ra
            _ra.on_movement_completed(
                actor, from_pos, state, self.event_bus, self.primitives)
        return True

    def _maybe_reposition_for_aoe(self, actor: Actor,
                                  state: CombatState) -> bool:
        """Monster-side AoE chase — the offensive counterpart to the PC
        de-cluster. An enemy with a breath/area attack available this turn
        relocates its apex to a reachable square that catches more PCs (the PCs
        having just spread out via `_maybe_aoe_decluster`). Returns True if it
        moved.

        Triple-gated: (1) PC-side-out (this is the monster mirror, so PCs are
        excluded — they run `_maybe_aoe_decluster` instead); (2) by the
        optimization dial — only an ABOVE-baseline enemy chases, so the dial-1
        'WoTC floor' boss stays deliberately naive (under-optimized AoE is the
        intended baseline behavior, and this keeps every enemy-dial-1 sim
        unchanged); (3) by `best_aoe_attack_position`, which needs an AoE
        available this turn, ≥2 living enemies, and a strictly-better square.
        Mirrors `_maybe_aoe_decluster`'s move/OA/ready-action plumbing."""
        if actor.moved_this_turn or actor.side == "pc":
            return False
        from engine.core.optimization_dial import dial_for
        if dial_for(actor, state) < AOE_CHASE_MIN_DIAL:
            return False
        from engine.ai.positioning import best_aoe_attack_position
        from engine.core.geometry import distance_ft
        dest = best_aoe_attack_position(actor, state)
        if dest is None:
            return False
        from_pos = actor.position
        actor.position = dest
        actor.moved_this_turn = True
        state.event_log.append({
            "event": "moved", "actor": actor.id,
            "from": list(from_pos), "to": list(dest),
            "ft": distance_ft(from_pos, dest),
            "reason": "aoe_reposition",
        })
        from engine.core import reactions
        reactions.resolve_opportunity_attacks(
            actor, from_pos, state, self.event_bus, self.primitives, self.rng)
        if actor.is_alive():
            from engine.core import ready_action as _ra
            _ra.on_movement_completed(
                actor, from_pos, state, self.event_bus, self.primitives)
        return True

    def _maybe_choose_elevation(self, actor: Actor,
                                state: CombatState) -> bool:
        """Set a flier's elevation for the turn (aerial kiting, Stage 2).
        `choose_flier_elevation` decides a safe hover (out of grounded-melee
        reach, when the flier has working airborne offense and the dial allows
        it) vs grounded (0). Returns True if the elevation changed. Changing
        elevation is vertical movement spent from the fly budget; v1 doesn't
        debit the horizontal move (an 80-ft flier easily affords a ~10-ft
        hover plus a reposition), so it does NOT set moved_this_turn — the
        horizontal AoE-chase / engage still run."""
        from engine.ai.altitude import choose_flier_elevation, has_fly
        if not has_fly(actor):
            return False
        target = choose_flier_elevation(actor, state)
        if target == actor.elevation:
            return False
        from_elev = actor.elevation
        actor.elevation = target
        state.event_log.append({
            "event": "elevation_changed", "actor": actor.id,
            "from": from_elev, "to": target,
            "reason": "kite" if target > 0 else "descend",
        })
        return True

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

        # AoE-aware de-cluster (PCs): reposition to a safer square if one helps.
        if self._maybe_aoe_decluster(actor, state):
            return

        enemies = [a for a in state.encounter.actors
                    if a.side != actor.side and a.is_alive()]
        if not enemies:
            return
        preset = resolve_targeting_preset(actor)
        target = pick_target(actor, enemies, state, preset)
        if target is None:
            return

        # Best open-field speed (max of walk/fly) so a flier CLOSES at its fly
        # speed, not just repositions at it — an Adult Dragon engages at 80 ft,
        # not 40. Shared with reachable_squares via best_move_speed_ft. Not
        # dial-gated: closing distance is basic movement, available at every
        # optimization level (only the AoE *chase* is dial-gated).
        from engine.core.geometry import best_move_speed_ft
        speed_ft = best_move_speed_ft(actor)
        # PR #74: Dash doubles speed for this turn's move (RAW: Dash grants
        # extra movement equal to your Speed). Read off `actor.dashed_this_turn`,
        # set by the dash primitive.
        if getattr(actor, "dashed_this_turn", False):
            speed_ft *= 2
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
        from_elev = actor.elevation
        from_dist = distance_ft(actor, target)

        # 3-D engage: a FLIER first closes the VERTICAL gap to its target —
        # ascending to an airborne enemy (a Fly-buffed Fighter rising to the
        # hovering dragon) or descending to a grounded one — spending fly
        # movement, so melee reach can connect in Chebyshev-3D. Grounded movers
        # (no fly) and same-elevation targets skip this entirely. Vertical is
        # closed first; the remaining budget feeds the horizontal move. Doesn't
        # undo kiting: a kiter has its breath in range, so move-to-engage never
        # fires for it.
        from engine.core.geometry import SQUARE_SIZE_FT
        from engine.ai.altitude import has_fly
        elev_moved = 0
        if (has_fly(actor) and actor.elevation != target.elevation
                and speed_ft > 0):
            gap = abs(target.elevation - actor.elevation)
            climb = (min(gap, speed_ft) // SQUARE_SIZE_FT) * SQUARE_SIZE_FT
            if climb > 0:
                up = target.elevation > actor.elevation
                actor.elevation += climb if up else -climb
                elev_moved = climb
                speed_ft -= climb

        # Barriers (Wall of Force) stop movement: the mover halts at the
        # wall rather than passing through it. Gated inside move_toward —
        # an empty wall list is the open-battlefield no-op.
        moved_ft = move_toward(actor, target, speed_ft, stop_at_ft=stop_at,
                                blockers=getattr(state, "walls", None))
        if moved_ft <= 0 and elev_moved <= 0:
            return
        actor.moved_this_turn = True
        state.event_log.append({
            "event": "moved",
            "actor": actor.id,
            "from": list(from_pos),
            "to": list(actor.position),
            "ft": moved_ft,
            "toward": target.id,
            "from_elev": from_elev,
            "to_elev": actor.elevation,
            "elev_ft": elev_moved,
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

        # PR #86: Ready Action `enemy_enters_reach` trigger. Fires
        # AFTER OAs so the "leaving reach" reactions resolve before
        # the "entering reach" readied actions. The mover may have
        # died from an OA — `try_fire` checks `target.is_alive()`
        # and short-circuits.
        if actor.is_alive():
            from engine.core import ready_action as _ra
            _ra.on_movement_completed(
                actor, from_pos, state,
                self.event_bus, self.primitives,
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
            # Per-encounter immunity (Stench: "immune for 24 hours" on a
            # successful save). Guarded by immune_on_success so spell auras
            # are unaffected.
            if actor.id in aura.get("_immune_ids", ()):
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
            # PR #77: propagate the aura's captured upcast metadata so
            # _resolve_upcast_extra_dice in _damage can apply per-turn
            # upcast bonus damage (HoH, Cloudkill, etc.). The aura's
            # `action` synthetic-dict carries the original action's
            # spell_slot_level + upcast_scaling for the upcast helper
            # to read off state.current_attack.action.
            synthetic_action = {
                "id": aura["action_id"],
                "named_effect": aura.get("named_effect"),
                "spell_slot_level": aura.get("spell_slot_level", 0),
            }
            if aura.get("upcast_scaling"):
                synthetic_action["upcast_scaling"] = aura["upcast_scaling"]
            state.current_attack = {
                "actor": caster, "target": actor,
                "action": synthetic_action,
                "state": None,
                "had_advantage": False, "had_disadvantage": False,
                "area_origin": tuple(origin), "area_direction": None,
                "chosen_slot_level": aura.get("chosen_slot_level", 0),
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
                    # Trait aura with per-encounter immunity: a creature
                    # that succeeds becomes immune for the rest of the
                    # fight (Stench's 24h immunity).
                    if (aura.get("immune_on_success")
                            and (state.current_save or {}).get("outcome")
                            == "success"):
                        aura.setdefault("_immune_ids", set()).add(actor.id)
            finally:
                state.current_attack = saved_attack
            # If the actor died from the aura, stop processing further
            # auras on them this turn (defensive).
            if not actor.is_alive():
                break

    def _resolve_recurring_damage(self, actor: Actor,
                                      state: CombatState) -> None:
        """Fire recurring damage ticks targeting `actor` at their turn-
        start (PR #89).

        Used by ongoing-damage conditions like Searing Smite's Ignited.
        Each entry deals dice damage of the declared type. The entry
        stays registered until concentration ends or the host condition
        is removed.

        Resistance/vulnerability/immunity are applied by the _damage
        primitive as usual (target template's damage_resistances etc.).
        """
        if not state.recurring_damage:
            return
        for entry in list(state.recurring_damage):
            if entry.get("target_id") != actor.id:
                continue
            if entry.get("trigger_event") != "target_turn_start":
                continue
            caster = state._actor_by_id(entry.get("source_id"))
            if caster is None:
                # Source caster gone; orphan tick — drop it.
                state.recurring_damage.remove(entry)
                continue
            # Set up state.current_attack so _damage can read actor +
            # target. Mirrors persistent_aura's synthetic-attack pattern.
            saved_attack = state.current_attack
            synthetic_action = {
                "id": entry.get("source_action_id"),
                "spell_slot_level": 0,
            }
            state.current_attack = {
                "actor": caster, "target": actor,
                "action": synthetic_action,
                "state": "hit",   # treat as a hit so on-hit damage applies
                "had_advantage": False, "had_disadvantage": False,
            }
            try:
                self.primitives.invoke("damage", {
                    "dice": entry.get("dice", "1d6"),
                    "modifier": 0,
                    "type": entry.get("damage_type", "untyped"),
                }, state, self.event_bus)
                state.event_log.append({
                    "event": "recurring_damage_tick",
                    "target": actor.id,
                    "source": caster.id,
                    "source_action": entry.get("source_action_id"),
                    "dice": entry.get("dice"),
                    "type": entry.get("damage_type"),
                })
            finally:
                state.current_attack = saved_attack
            # If the actor died from the tick, stop further ticks on them
            if not actor.is_alive():
                break

    def _resolve_recurring_temp_hp(self, actor: Actor,
                                       state: CombatState) -> None:
        """Fire recurring temp HP grants targeting `actor` at their
        turn-start (PR #94). Dual of _resolve_recurring_damage.

        Used by ongoing-grant spells like Heroism. Each entry grants
        the declared amount via max-semantics (RAW: gaining temp HP
        replaces if greater, keeps if lower). Re-grants every turn
        so the temp HP buffer refills if the previous turn's grant
        was burned off by damage.

        Source remains registered until concentration ends or the
        host condition is removed.
        """
        if not state.recurring_temp_hp:
            return
        for entry in list(state.recurring_temp_hp):
            if entry.get("target_id") != actor.id:
                continue
            if entry.get("trigger_event") != "target_turn_start":
                continue
            caster = state._actor_by_id(entry.get("source_id"))
            if caster is None:
                state.recurring_temp_hp.remove(entry)
                continue
            saved_attack = state.current_attack
            synthetic_action = {
                "id": entry.get("source_action_id"),
            }
            state.current_attack = {
                "actor": caster, "target": actor,
                "action": synthetic_action,
                "state": None,
                "had_advantage": False, "had_disadvantage": False,
            }
            try:
                self.primitives.invoke("temp_hp_grant", {
                    "amount": entry.get("amount", 0),
                }, state, self.event_bus)
                state.event_log.append({
                    "event": "recurring_temp_hp_tick",
                    "target": actor.id,
                    "source": caster.id,
                    "source_action": entry.get("source_action_id"),
                    "amount": entry.get("amount"),
                })
            finally:
                state.current_attack = saved_attack

    def _resolve_recurring_saves(self, actor: Actor,
                                      state: CombatState,
                                      trigger_event: str = "target_turn_end"
                                      ) -> None:
        """Roll recurring saves for `actor` matching `trigger_event`.

        Used by Hold Person (target_turn_end) and Searing Smite's
        co_ignited (target_turn_start — fires AFTER the burn tick).
        On success with on_success == 'end_spell_on_target': removes
        the condition, its recurring_damage entries, and the save entry.
        """
        if not state.recurring_saves:
            return
        remaining: list = []
        for entry in state.recurring_saves:
            if entry.get("target_id") != actor.id:
                remaining.append(entry)
                continue
            if entry.get("trigger_event") != trigger_event:
                remaining.append(entry)
                continue
            # Roll the save
            from engine.core.state import ability_modifier as _am
            ability = entry.get("ability", "wisdom")
            short_ab = {"strength": "str", "dexterity": "dex", "constitution": "con",
                         "intelligence": "int", "wisdom": "wis", "charisma": "cha"}.get(ability, ability)
            # PR #75: stash save-source context so racial trait save
            # advantages (Brave / Fey Ancestry / Dwarven Resilience)
            # fire correctly on recurring saves too. Recurring saves
            # are "would END condition X on success" — treat as if
            # X is in the on_fail set for racial-trait purposes
            # (same polarity from the trait's perspective).
            from engine.core.racial_traits import (
                build_save_context_for_condition, lucky_d20)
            saved_save_context = state.current_save_context
            cond_id = entry.get("condition_id")
            if cond_id:
                state.current_save_context = \
                    build_save_context_for_condition(cond_id)
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
                # PR #75: Lucky reroll on nat 1
                d20, _rerolled = lucky_d20(self.rng, d20, actor)
                total = d20 + save_bonus + save_mods.save_bonus_modifier
                outcome = "success" if total >= entry["dc"] else "fail"
            # PR #75: restore prior save context
            state.current_save_context = saved_save_context
            state.event_log.append({
                "event": "recurring_save", "target": actor.id,
                "ability": ability, "dc": entry["dc"],
                "d20": d20, "total": total, "outcome": outcome,
                "for_condition": entry.get("condition_id"),
            })
            if outcome == "success" and entry.get("on_success") == "end_spell_on_target":
                cond_id = entry.get("condition_id")
                if cond_id:
                    remove_condition(actor, cond_id, entry.get("source_id"))
                    state.recurring_damage = [
                        rd for rd in state.recurring_damage
                        if not (rd.get("target_id") == actor.id
                                and rd.get("condition_id") == cond_id)
                    ]
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

        # ---- PR #85: Reckless Attack pre-action activation ----
        # Barbarian L2 free declaration: "When you make your first
        # attack roll on your turn, you can decide to attack
        # recklessly." Engine collapses to a pre-action decision so
        # advantage applies to the first swing and the AI commits
        # before seeing any rolls. Cost (advantage to incoming
        # attackers) opens immediately and lasts until reset_turn at
        # start of next own turn.
        self._maybe_activate_reckless_attack(actor, state)

        # ---- Flier elevation choice (turn start) ----
        # A flier picks its altitude BEFORE horizontal repositioning: an
        # above-baseline flier hovers out of grounded-melee reach when it has
        # working airborne offense (breath/ranged), else descends to melee (a
        # swoop). Dial-gated; grounded creatures are untouched. Sets elevation
        # only — horizontal AoE-chase / engage still run below.
        if actor.is_alive() and not state.terminated:
            self._maybe_choose_elevation(actor, state)

        # ---- AoE-aware safety reposition (turn start) ----
        # Step out of enemy area attacks (the dragon's breath cone) BEFORE
        # acting. Run here — not only on the move-to-engage path — so a ranged
        # caster that already has an in-range target (and thus never triggers
        # move-to-engage) still de-clusters. Self-gated + offense-aware, so a
        # melee actor that needs to stay adjacent won't flee. moved_this_turn
        # then suppresses any later move this turn.
        if actor.is_alive() and not state.terminated:
            self._maybe_aoe_decluster(actor, state)

        # ---- Monster AoE chase (turn start) ----
        # Offensive counterpart to the PC de-cluster: an above-baseline enemy
        # relocates its breath apex to catch more PCs before breathing. Dial-
        # gated (the WoTC-floor boss stays naive) and PC-side-out, so this and
        # the de-cluster above are mutually exclusive per actor. moved_this_turn
        # then suppresses any later move-to-engage this turn.
        if actor.is_alive() and not state.terminated:
            self._maybe_reposition_for_aoe(actor, state)

        # ---- Main slot ----
        self._run_slot(actor, state, slot="action")

        # ---- Free phase (PR #57) ----
        # Auto-fire any slot='free' actions that are eligible. Used by
        # Nick weapon mastery (off-hand attack happens as part of the
        # Attack action). No AI scoring / selection — all eligible
        # free actions fire automatically. Skipped if the main slot
        # killed the actor or the encounter terminated.
        if actor.is_alive() and not state.terminated:
            self._run_free_phase(actor, state)

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

        # ---- PR #74: Dash post-BA second-move pass ----
        # If the actor Dashed (via Cunning Action BA or future
        # main-slot Dash) AND still has out-of-reach enemies AND
        # hasn't already used this pass, run _move_to_engage one more
        # time. The _dash primitive cleared `moved_this_turn` so this
        # pass can fire even if the actor had moved earlier; the
        # `_dash_post_move_done` flag prevents recursion.
        if (actor.dashed_this_turn
                and not getattr(actor, "_dash_post_move_done", False)
                and actor.is_alive() and not state.terminated):
            actor._dash_post_move_done = True
            self._move_to_engage(actor, state)

    def _resolve_legendary_actions(self, ended_actor: Actor,
                                     state: CombatState) -> None:
        """Give every OTHER eligible legendary creature one window to spend
        a Legendary Action use, now that `ended_actor`'s turn has ended.

        Selection reuses the normal decision machinery: the creature's
        legendary `options` are temporarily exposed as its slot-'action'
        actions and run through generate_candidates → score → select →
        execute, so range / cover / recharge filtering and eHP scoring all
        apply. One use is spent per window (RAW); the option's cost is
        deducted from the pool. See engine/core/legendary_actions.py.
        """
        from engine.core import legendary_actions as la
        for creature in list(state.encounter.actors):
            if creature.id == ended_actor.id:
                continue                      # not after one's own turn
            if not la.is_eligible(creature):
                continue
            options = la.affordable_options(creature)
            if not options:
                continue
            option_ids = {o["id"] for o in options}
            # Expose the legendary options as the creature's action-slot
            # actions for one candidate-generation pass, then restore.
            saved_actions = creature.template.get("actions")
            creature.template["actions"] = options
            try:
                cands = pipeline.generate_candidates(
                    creature, state, slot="action")
            finally:
                creature.template["actions"] = saved_actions
            cands = [c for c in cands
                      if c["action"].get("id") in option_ids]
            if not cands:
                continue
            cands = pipeline.apply_hard_filters(cands, creature, state)
            cands = pipeline.apply_forced_choices(cands, creature, state)
            scored = pipeline.score_candidates(cands, creature, state)
            # Only spend a use on a worthwhile option (positive eHP value);
            # a legendary creature won't burn a use on a no-op.
            scored = [(s, c) for (s, c) in scored if s > 0]
            chosen = pipeline.select_max(scored)
            if chosen is None:
                continue
            chosen_option = next(
                o for o in options
                if o["id"] == chosen["action"].get("id"))
            pipeline.execute(chosen, state, self.event_bus, self.primitives)
            la.consume(creature, chosen_option, state)
            if state.terminated:
                break

    def _run_free_phase(self, actor: Actor, state: CombatState) -> None:
        """Auto-fire any slot='free' actions on the actor (PR #57 +
        PR #70 scoring).

        Free-slot actions fire automatically if eligible. Currently
        only used by Nick weapon mastery (off-hand attack as part
        of the Attack action), but the phase is generic so future
        "auto-trigger" mechanics (Cleave, Sneak Attack auto-
        application, etc.) can reuse it when they land.

        Eligibility check per action:
          - action.slot == 'free'
          - action.type == 'weapon_attack' (v1 only — other free
            action types deferred until a non-attack free action
            exists)
          - At least one in-reach living enemy

        **PR #70: scoring + optional gate.** Each candidate is
        scored via `score_candidate` before firing. The eHP value
        is logged in the `free_action_fired` event for telemetry.
        If the action declares `min_score_to_fire: <float>`, the
        candidate is skipped with `free_action_skipped`
        (reason=below_min_score) when the score is below that
        threshold. Default 0 → always-fire (preserves v1 Nick
        semantics; the off-hand attack always swings against an
        in-reach enemy, since the only cost is the swing itself
        and Nick is RAW free).

        Fires each eligible free action ONCE per turn. The action's
        `slot` ('free') is not tracked in actions_used_this_turn,
        so this method maintains its own per-turn dedup set to
        avoid re-firing in a multi-pass turn (e.g., if Action Surge
        triggers another action phase).
        """
        from engine.core.geometry import distance_ft
        from engine.core.pipeline import _action_reach_ft
        from engine.ai.behavior_profile import resolve_targeting_preset
        from engine.ai.targeting import pick_target
        from engine.ai.ehp_scoring import score_candidate

        if not hasattr(actor, "_free_actions_fired_this_turn"):
            actor._free_actions_fired_this_turn = set()
        already_fired = actor._free_actions_fired_this_turn

        free_actions = [
            a for a in (actor.template.get("actions") or [])
            if a.get("slot") == "free"
            and a.get("type") == "weapon_attack"
            and a.get("id") not in already_fired
        ]
        if not free_actions:
            return

        enemies = [a for a in state.encounter.actors
                    if a.side != actor.side and a.is_alive()]
        if not enemies:
            return

        preset = resolve_targeting_preset(actor)
        for action in free_actions:
            reach = _action_reach_ft(action)
            in_reach = [e for e in enemies
                          if distance_ft(actor, e) <= reach
                          and e.is_alive()]
            if not in_reach:
                state.event_log.append({
                    "event": "free_action_skipped",
                    "actor": actor.id,
                    "action": action.get("id"),
                    "reason": "no_in_reach_enemy",
                })
                continue
            target = pick_target(actor, in_reach, state, preset)
            if target is None:
                continue
            chosen = {
                "kind": "weapon_attack",
                "actor": actor,
                "target": target,
                "action": action,
            }
            # PR #70: score before firing. Log the value for
            # telemetry + optionally skip via min_score_to_fire.
            score = score_candidate(chosen, state)
            min_score = float(action.get("min_score_to_fire", 0.0) or 0.0)
            if score < min_score:
                state.event_log.append({
                    "event": "free_action_skipped",
                    "actor": actor.id,
                    "action": action.get("id"),
                    "target": target.id,
                    "reason": "below_min_score",
                    "score": round(score, 2),
                    "min_score": min_score,
                })
                continue
            state.event_log.append({
                "event": "free_action_fired",
                "actor": actor.id,
                "action": action.get("id"),
                "target": target.id,
                "score": round(score, 2),
            })
            pipeline.execute(chosen, state, self.event_bus, self.primitives)
            already_fired.add(action.get("id"))
            # Stop iterating if this action killed the actor / ended
            # the encounter.
            if not actor.is_alive() or state.terminated:
                return

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
        # Move-to-engage when the actor has NO candidate that acts on an
        # ENEMY from here — not merely when the set is empty. A self-targeted
        # option (e.g. a Ready-for-when-an-enemy-enters-reach) must not freeze
        # a melee actor at range: it should advance toward the enemy and then
        # act. We re-generate after moving — if an in-reach attack now exists
        # we use it; otherwise the pre-move defensive/Ready candidates remain
        # selectable. Actors that already have an offensive candidate skip
        # this entirely (the common path is unchanged).
        def _targets_enemy(cand):
            t = cand.get("target")
            return t is not None and getattr(t, "side", actor.side) != actor.side
        if slot == "action" and not any(_targets_enemy(c) for c in candidates):
            had_any = bool(candidates)
            self._move_to_engage(actor, state)
            # Movement may have triggered OAs that dropped the actor.
            if not actor.is_alive():
                return
            regen = pipeline.generate_candidates(actor, state, slot=slot)
            if regen:
                candidates = regen
            elif not had_any:
                state.event_log.append({
                    "event": "passed_turn",
                    "actor": actor.id,
                    "slot": slot,
                    "reason": "out_of_range_after_movement",
                })
                return
            # else: keep the pre-move non-offensive candidates (Ready / buff)

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
            encounters_remaining_today: int = 3,
            optimization_dials: dict | None = None) -> CombatState:
        """Run the encounter to termination. Returns final CombatState.

        `encounters_remaining_today` (default 3 = mid-day baseline)
        feeds the pace-aware AI: spell-slot opportunity cost (PR #22)
        and Action Surge activation gate (PR #42) both consult it.
        Session runners pass per-encounter values so the AI sees
        urgency decrease across the day. Single-encounter sims use
        the default.

        `optimization_dials` ({side: 1-5}) sets each side's play-skill dial
        (engine.core.optimization_dial). Default/absent → dial 1 (casual: no
        focus-fire), preserving prior behavior; sims set it to measure the
        power-level curve.
        """
        if seed is not None:
            self.rng = random.Random(seed)
        state = CombatState(
            encounter=self.encounter,
            content_registry=self.content_registry,
            encounters_remaining_today=encounters_remaining_today,
            optimization_dials=dict(optimization_dials or {}),
        )
        self.event_bus.emit("round_start", {"round": 1})
        self.roll_initiative(state)
        # Register always-on aura traits (Ghast Stench, etc.) as
        # caster-anchored persistent_auras so the turn-start resolver fires
        # them. See engine/core/aura_traits.py.
        from engine.core import aura_traits as _aura_traits
        _aura_traits.register(state)
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
