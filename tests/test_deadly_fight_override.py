"""Early-deadly-fight danger override (backlog #c).

The nova-late slot-cost formula (`slot_cost_ehp`) makes slots EXPENSIVE early
in the day so casters conserve for the climax. But if an EARLY fight turns
genuinely deadly, conserving a slot for a future encounter is a false economy
— a PC may die now and never see that fight. `encounter_danger` measures the
current fight's acute danger; `candidate_slot_cost` scales the conserve-early
penalty by `(1 - danger)` so casters nova NOW when survival demands it.

Layers:
  1. encounter_danger signal — 0 when safe / fight won; ramps with party
     depletion; spikes on a single near-dead ally.
  2. candidate_slot_cost override — collapses toward 0 under full danger;
     unchanged under no danger; no-op at the climax (base already 0).

Run via:
    python -m unittest tests.test_deadly_fight_override
"""
from __future__ import annotations

import unittest

from engine.core.spell_slots import (
    encounter_danger, candidate_slot_cost, slot_cost_ehp,
    DANGER_PARTY_HP_HIGH, DANGER_PARTY_HP_LOW, DANGER_ALLY_CRITICAL_FRAC,
)
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _actor(actor_id: str, side: str = "pc", hp: int = 100, hp_max: int = 100,
           spell_slots: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 14, "save": 2}, "dex": {"score": 12, "save": 1},
        "con": {"score": 12, "save": 1}, "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2}, "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id, "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                 hp_current=hp, hp_max=hp_max, ac=14, position=(0, 0),
                 abilities=abilities, spell_slots=dict(spell_slots or {}))


def _state(actors: list[Actor], encounters_remaining: int = 3) -> CombatState:
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc,
                        encounters_remaining_today=encounters_remaining)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _spell(level: int = 3) -> dict:
    return {"id": "a_fireball", "name": "Fireball", "spell_slot_level": level}


# ============================================================================
# encounter_danger signal
# ============================================================================

class EncounterDangerTest(unittest.TestCase):

    def test_full_hp_party_is_safe(self):
        pc, foe = _actor("pc"), _actor("foe", side="enemy")
        self.assertEqual(encounter_danger(pc, _state([pc, foe])), 0.0)

    def test_no_living_enemies_is_safe_even_if_hurt(self):
        # Fight won — nothing left to nova for, so danger is 0 regardless.
        pc = _actor("pc", hp=5)
        dead_foe = _actor("foe", side="enemy", hp=0)
        self.assertEqual(encounter_danger(pc, _state([pc, dead_foe])), 0.0)

    def test_no_living_allies_is_safe(self):
        # Degenerate guard: the casting actor must have living allies (itself
        # at least) for the signal to mean anything.
        downed = _actor("pc", hp=0)
        foe = _actor("foe", side="enemy")
        self.assertEqual(encounter_danger(downed, _state([downed, foe])), 0.0)

    def test_aggregate_depletion_full_at_low_threshold(self):
        # Party at/below 15% aggregate HP -> full danger.
        pc = _actor("pc", hp=int(100 * DANGER_PARTY_HP_LOW))   # 15
        foe = _actor("foe", side="enemy")
        self.assertAlmostEqual(encounter_danger(pc, _state([pc, foe])), 1.0)

    def test_aggregate_depletion_zero_at_high_threshold(self):
        # Party at the 50% line -> no aggregate danger yet.
        pc = _actor("pc", hp=int(100 * DANGER_PARTY_HP_HIGH))  # 50
        foe = _actor("foe", side="enemy")
        self.assertAlmostEqual(encounter_danger(pc, _state([pc, foe])), 0.0)

    def test_aggregate_depletion_ramps_linearly(self):
        # Midpoint between HIGH (0.5) and LOW (0.15) -> ~0.5 danger.
        mid = (DANGER_PARTY_HP_HIGH + DANGER_PARTY_HP_LOW) / 2  # 0.325
        pc = _actor("pc", hp=int(100 * mid))                   # 32 (rounds)
        foe = _actor("foe", side="enemy")
        d = encounter_danger(pc, _state([pc, foe]))
        self.assertTrue(0.45 < d < 0.55, f"midpoint danger {d} not ~0.5")

    def test_acute_single_ally_peril_dominates_healthy_aggregate(self):
        # One ally near death (10% own HP) while the party's AGGREGATE HP
        # still looks healthy (>50%) -> danger driven by acute peril, not
        # aggregate. peril = (0.25 - 0.10)/0.25 = 0.6.
        dying = _actor("wizard", hp=10, hp_max=100)            # 10%
        tank = _actor("fighter", hp=100, hp_max=100)
        foe = _actor("foe", side="enemy")
        d = encounter_danger(dying, _state([dying, tank, foe]))
        self.assertAlmostEqual(d, 0.6, places=2)
        # And it's strictly above what aggregate alone (frac ~0.55) gives (0).
        self.assertGreater(d, 0.0)

    def test_acute_peril_full_as_ally_nears_zero(self):
        dying = _actor("wizard", hp=1, hp_max=100)
        tank = _actor("fighter", hp=100, hp_max=100)
        foe = _actor("foe", side="enemy")
        d = encounter_danger(dying, _state([dying, tank, foe]))
        self.assertGreater(d, 0.95)

    def test_ally_above_critical_frac_no_acute(self):
        # Ally at 30% (> 25% critical) and aggregate healthy -> no danger.
        a = _actor("a", hp=30, hp_max=100)
        tank = _actor("tank", hp=100, hp_max=100)
        foe = _actor("foe", side="enemy")
        self.assertEqual(
            encounter_danger(a, _state([a, tank, foe])), 0.0)


# ============================================================================
# candidate_slot_cost override
# ============================================================================

class SlotCostOverrideTest(unittest.TestCase):

    def test_no_danger_cost_equals_base(self):
        pc = _actor("pc", spell_slots={3: 2})
        foe = _actor("foe", side="enemy")
        state = _state([pc, foe], encounters_remaining=3)
        base = slot_cost_ehp(3, 2, 3)
        self.assertGreater(base, 0.0)
        self.assertAlmostEqual(candidate_slot_cost(pc, _spell(3), state), base)

    def test_full_danger_collapses_cost_to_zero(self):
        # Party near death mid-day: the conserve-early penalty vanishes.
        pc = _actor("pc", hp=10, hp_max=100, spell_slots={3: 2})
        foe = _actor("foe", side="enemy")
        state = _state([pc, foe], encounters_remaining=3)
        self.assertEqual(encounter_danger(pc, state), 1.0)
        self.assertAlmostEqual(candidate_slot_cost(pc, _spell(3), state), 0.0)

    def test_partial_danger_reduces_but_not_zero(self):
        # ~0.5 danger -> cost roughly halved vs base.
        mid = (DANGER_PARTY_HP_HIGH + DANGER_PARTY_HP_LOW) / 2
        pc = _actor("pc", hp=int(100 * mid), hp_max=100, spell_slots={3: 2})
        foe = _actor("foe", side="enemy")
        state = _state([pc, foe], encounters_remaining=3)
        base = slot_cost_ehp(3, 2, 3)
        cost = candidate_slot_cost(pc, _spell(3), state)
        self.assertTrue(base * 0.45 < cost < base * 0.55,
                        f"partial-danger cost {cost} not ~half of base {base}")
        self.assertGreater(cost, 0.0)

    def test_override_is_noop_at_climax(self):
        # encounters_remaining = 0 -> base already 0 -> override changes
        # nothing (the FINDINGS note: danger-override is moot at the climax).
        pc = _actor("pc", hp=10, hp_max=100, spell_slots={3: 2})
        foe = _actor("foe", side="enemy")
        state = _state([pc, foe], encounters_remaining=0)
        self.assertEqual(slot_cost_ehp(3, 2, 0), 0.0)
        self.assertEqual(candidate_slot_cost(pc, _spell(3), state), 0.0)

    def test_deadly_early_fight_is_cheaper_than_safe_early_fight(self):
        # Same early-day slot (rem=3); the deadly version costs strictly less,
        # so the caster is more willing to nova in the deadly fight.
        foe1 = _actor("foe1", side="enemy")
        safe = _actor("safe", hp=100, hp_max=100, spell_slots={3: 2})
        deadly = _actor("deadly", hp=20, hp_max=100, spell_slots={3: 2})
        cost_safe = candidate_slot_cost(
            safe, _spell(3), _state([safe, foe1], encounters_remaining=3))
        foe2 = _actor("foe2", side="enemy")
        cost_deadly = candidate_slot_cost(
            deadly, _spell(3), _state([deadly, foe2], encounters_remaining=3))
        self.assertLess(cost_deadly, cost_safe)

    def test_cantrip_still_free_under_danger(self):
        pc = _actor("pc", hp=5, hp_max=100, spell_slots={3: 2})
        foe = _actor("foe", side="enemy")
        state = _state([pc, foe], encounters_remaining=3)
        self.assertEqual(candidate_slot_cost(pc, _spell(0), state), 0.0)


if __name__ == "__main__":
    unittest.main()
