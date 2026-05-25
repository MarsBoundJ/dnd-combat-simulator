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

        # Run the 8-step decision pipeline
        self._run_actor_turn(actor, state)

        # Resolve any recurring saves registered against this actor's turn_end
        self._resolve_recurring_saves(actor, state)

        self.event_bus.emit("turn_end", {"actor": actor, "round": state.round})
        state.event_log.append({"event": "turn_end", "actor": actor.id,
                                "hp_remaining": actor.hp_current})

        state.advance_turn()

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
        """
        # Step 0: resolve effective profile
        profile = pipeline.resolve_effective_profile(actor, state)
        # Step 1: retreat trigger
        retreat = pipeline.check_retreat_trigger(actor, state)
        if retreat:
            actor.is_fled = True
            state.event_log.append({"event": "fled", "actor": actor.id})
            return

        # ---- Main slot ----
        self._run_slot(actor, state, slot="action")

        # ---- Bonus slot ----
        # Skip if the main slot killed the actor or terminated the encounter.
        if actor.is_alive() and not state.terminated:
            self._run_slot(actor, state, slot="bonus_action")

    def _run_slot(self, actor: Actor, state: CombatState, slot: str) -> None:
        """Execute one turn slot (action or bonus_action) via the
        candidate-scoring pipeline. The Action Economy dial gates:

          - Main slot: optimality roll may downgrade the chosen action
            to the actor's default attack.
          - Bonus slot: per-action signature/tactical rate may skip the
            slot entirely.
        """
        candidates = pipeline.generate_candidates(actor, state, slot=slot)
        if not candidates:
            return
        candidates = pipeline.apply_hard_filters(candidates, actor, state)
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

    def run(self, seed: int | None = None) -> CombatState:
        """Run the encounter to termination. Returns final CombatState."""
        if seed is not None:
            self.rng = random.Random(seed)
        state = CombatState(encounter=self.encounter,
                             content_registry=self.content_registry)
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
