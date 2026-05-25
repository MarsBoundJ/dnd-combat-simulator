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

from engine.core.events import EventBus
from engine.core.state import Actor, Encounter, CombatState
from engine.core import pipeline
from engine.primitives import PrimitiveRegistry


# Safety cap — don't loop forever if termination logic has a bug
MAX_ROUNDS = 50


@dataclass
class EncounterRunner:
    encounter: Encounter
    event_bus: EventBus
    primitives: PrimitiveRegistry
    rng: random.Random

    @classmethod
    def new(cls, encounter: Encounter, seed: int | None = None) -> "EncounterRunner":
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        rng = random.Random(seed) if seed is not None else random.Random()
        return cls(encounter=encounter, event_bus=bus, primitives=prims, rng=rng)

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

        # Reset per-turn state
        actor.reset_turn()
        self.event_bus.emit("turn_start", {"actor": actor, "round": state.round})
        state.event_log.append({"event": "turn_start", "actor": actor.id, "round": state.round})

        # Run the 8-step decision pipeline
        self._run_actor_turn(actor, state)

        self.event_bus.emit("turn_end", {"actor": actor, "round": state.round})
        state.event_log.append({"event": "turn_end", "actor": actor.id,
                                "hp_remaining": actor.hp_current})

        state.advance_turn()

    def _run_actor_turn(self, actor: Actor, state: CombatState) -> None:
        """Execute one actor's turn via the decision pipeline."""
        # Step 0: resolve effective profile
        profile = pipeline.resolve_effective_profile(actor, state)
        # Step 1: retreat trigger
        retreat = pipeline.check_retreat_trigger(actor, state)
        if retreat:
            actor.is_fled = True
            state.event_log.append({"event": "fled", "actor": actor.id})
            return
        # Step 2-6: decision pipeline
        candidates = pipeline.generate_candidates(actor, state)
        candidates = pipeline.apply_hard_filters(candidates, actor, state)
        candidates = pipeline.apply_forced_choices(candidates, actor, state)
        scored = pipeline.score_candidates(candidates, actor, state)
        chosen = pipeline.select_max(scored)
        # Step 7: action economy
        chosen = pipeline.apply_action_economy(actor, chosen, state) if chosen else None
        # Step 8: execute
        if chosen:
            pipeline.execute(chosen, state, self.event_bus, self.primitives)

    def run(self, seed: int | None = None) -> CombatState:
        """Run the encounter to termination. Returns final CombatState."""
        if seed is not None:
            self.rng = random.Random(seed)
        state = CombatState(encounter=self.encounter)
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
