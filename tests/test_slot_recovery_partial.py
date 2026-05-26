"""slot_recovery_partial primitive tests (PR #37).

Layers:
  1. No-op when actor has no spell_slots_max
  2. Restores up to max_combined_level budget
  3. Caps individual restoration at max_slot_level
  4. Never exceeds spell_slots_max[level]
  5. Greedy high-first: prefers higher-level slots
  6. Multiple slots at same level restorable if expended

Run via:
    python -m unittest tests.test_slot_recovery_partial
"""
from __future__ import annotations

import unittest

from engine.primitives import _slot_recovery_partial
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_caster(actor_id: str = "wizard",
                  spell_slots: dict | None = None,
                  spell_slots_max: dict | None = None) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side="pc",
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities,
                  spell_slots=dict(spell_slots or {}),
                  spell_slots_max=dict(spell_slots_max or {}))


def _state_with(actor: Actor) -> CombatState:
    state = CombatState(encounter=Encounter(id="t", actors=[actor]))
    state.current_attack = {"actor": actor}
    state.turn_order = [actor.id]
    return state


# ============================================================================
# Tests
# ============================================================================

class SlotRecoveryPartialTest(unittest.TestCase):

    def test_no_max_means_noop(self) -> None:
        actor = _make_caster(spell_slots={}, spell_slots_max={})
        state = _state_with(actor)
        result = _slot_recovery_partial(
            {"max_combined_level": 5}, state, None)
        self.assertEqual(result["restored"], [])

    def test_restores_single_third_level_slot(self) -> None:
        """Budget 3, has expended L3 slot → restore one L3."""
        actor = _make_caster(spell_slots={3: 0},
                              spell_slots_max={3: 1})
        state = _state_with(actor)
        result = _slot_recovery_partial(
            {"max_combined_level": 3, "max_slot_level": 5}, state, None)
        self.assertEqual(actor.spell_slots[3], 1)
        self.assertEqual(result["restored"], [{"level": 3, "count": 1}])

    def test_greedy_prefers_higher_level(self) -> None:
        """Budget 3, L1 and L3 both expended → restore the L3 first
        (greedy high-first)."""
        actor = _make_caster(
            spell_slots={1: 0, 3: 0},
            spell_slots_max={1: 3, 3: 1},
        )
        state = _state_with(actor)
        _slot_recovery_partial(
            {"max_combined_level": 3, "max_slot_level": 5}, state, None)
        self.assertEqual(actor.spell_slots[3], 1)
        self.assertEqual(actor.spell_slots[1], 0,
                          "Budget spent entirely on L3; L1 untouched")

    def test_max_slot_level_caps(self) -> None:
        """Budget 5, L3 and L5 both expended, max_slot_level=3 → only
        restore L3 (L5 above cap)."""
        actor = _make_caster(
            spell_slots={3: 0, 5: 0},
            spell_slots_max={3: 1, 5: 1},
        )
        state = _state_with(actor)
        _slot_recovery_partial(
            {"max_combined_level": 5, "max_slot_level": 3}, state, None)
        self.assertEqual(actor.spell_slots[3], 1)
        self.assertEqual(actor.spell_slots[5], 0,
                          "L5 above max_slot_level cap — not restored")

    def test_never_exceeds_spell_slots_max(self) -> None:
        """Already at max → no restoration even if budget remains."""
        actor = _make_caster(
            spell_slots={1: 3},          # at max
            spell_slots_max={1: 3},
        )
        state = _state_with(actor)
        result = _slot_recovery_partial(
            {"max_combined_level": 5, "max_slot_level": 5}, state, None)
        self.assertEqual(actor.spell_slots[1], 3)
        self.assertEqual(result["restored"], [])

    def test_restores_multiple_slots_same_level_until_budget(self) -> None:
        """Budget 3, two L1 slots expended (max 2 at L1) → restore both,
        then budget=1 has no higher slot to use."""
        actor = _make_caster(
            spell_slots={1: 0, 2: 1},      # L1 fully expended, L2 fine
            spell_slots_max={1: 2, 2: 1},
        )
        state = _state_with(actor)
        result = _slot_recovery_partial(
            {"max_combined_level": 3, "max_slot_level": 5}, state, None)
        # Greedy high-first picks no L3+ (none expended), no L2 (already at
        # max), then walks down. Restores L1 first (level=1 ≤ budget=3),
        # budget→2, L1 still missing 1, restores another L1, budget→1.
        # L1 now at max. Budget 1 < min remaining slot level, loop ends.
        self.assertEqual(actor.spell_slots[1], 2)
        self.assertEqual(result["restored"], [{"level": 1, "count": 2}])

    def test_budget_zero_means_noop(self) -> None:
        actor = _make_caster(spell_slots={1: 0}, spell_slots_max={1: 2})
        state = _state_with(actor)
        result = _slot_recovery_partial(
            {"max_combined_level": 0, "max_slot_level": 5}, state, None)
        self.assertEqual(actor.spell_slots[1], 0)
        self.assertEqual(result["restored"], [])

    def test_logs_event(self) -> None:
        actor = _make_caster(spell_slots={3: 0}, spell_slots_max={3: 1})
        state = _state_with(actor)
        _slot_recovery_partial(
            {"max_combined_level": 3, "max_slot_level": 5}, state, None)
        events = [e for e in state.event_log
                   if e.get("event") == "slot_recovery_partial"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "wizard")
        self.assertEqual(events[0]["restored"],
                          [{"level": 3, "count": 1}])

    def test_canonical_arcane_recovery_L5_wizard(self) -> None:
        """L5 wizard: budget = ceil(5/2) = 3, cap = 5. Spent all slots
        in a tough fight: 4× L1, 3× L2, 2× L3. Short rest → restore
        one L3 (best use of 3 budget). Subsequent uses would need
        another short rest / long rest."""
        actor = _make_caster(
            spell_slots={1: 0, 2: 0, 3: 0},
            spell_slots_max={1: 4, 2: 3, 3: 2},
        )
        state = _state_with(actor)
        result = _slot_recovery_partial(
            {"max_combined_level": 3, "max_slot_level": 5}, state, None)
        self.assertEqual(actor.spell_slots[3], 1)
        self.assertEqual(actor.spell_slots[2], 0)
        self.assertEqual(actor.spell_slots[1], 0)
        self.assertEqual(result["restored"], [{"level": 3, "count": 1}])


if __name__ == "__main__":
    unittest.main()
