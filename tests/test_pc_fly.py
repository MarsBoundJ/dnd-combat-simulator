"""Altitude Stage 3b: the Fly spell (grant fly speed + concentration revert +
trade-aware valuation).

The Wizard's Fly grants a willing ally a 60-ft fly speed (concentration); 3-D
engage (Stage 3a) then carries the ally up to an airborne enemy. The AI values
Fly by the offense it UNLOCKS — but only when the ally would favorably trade
with the airborne foe (don't fly a 30-DPR Fighter into a 50-DPR dragon).

Run via:
    python -m unittest tests.test_pc_fly
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.ehp_scoring import offensive_ehp_fly_reach
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.state import Encounter, CombatState
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _party():
    from sims.adventuring_day import _build_party
    return _build_party(_registry())


def _mon(mid):
    from sims.adventuring_day import _build_monsters
    return _build_monsters(_registry(), [(mid, 1)])[0]


class FlyContentTest(unittest.TestCase):
    def test_wizard_has_fly_action(self):
        wiz = next(a for a in _party() if a.id == "Wizard_Evoker")
        self.assertTrue(any(a.get("id") == "a_fly"
                            for a in (wiz.template.get("actions") or [])))


class GrantSpeedTest(unittest.TestCase):
    def _cast_fly(self, caster, target, actors):
        st = CombatState(encounter=Encounter(id="t", actors=actors))
        st.content_registry = _registry()
        fly = next(a for a in caster.template["actions"] if a["id"] == "a_fly")
        st.current_attack = {"actor": caster, "target": target, "action": fly}
        apply_concentration(caster, fly, st)
        PrimitiveRegistry.with_defaults().invoke(
            "grant_speed", {"target": "ally", "speed_type": "fly",
                            "amount": 60}, st, None)
        return st, fly

    def test_grant_then_revert_on_concentration_end(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        fig = next(a for a in party if a.id == "Fighter_Champion")
        self.assertIsNone(fig.speed.get("fly"))
        st, _ = self._cast_fly(wiz, fig, party)
        self.assertEqual(fig.speed.get("fly"), 60)        # granted
        self.assertEqual(len(fig.active_speed_grants), 1)
        end_concentration(wiz, st, reason="test")
        self.assertIsNone(fig.speed.get("fly"))           # reverted (no prior)
        self.assertEqual(fig.active_speed_grants, [])

    def test_no_stack_on_recast(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        fig = next(a for a in party if a.id == "Fighter_Champion")
        st, fly = self._cast_fly(wiz, fig, party)
        # second grant from the same named_effect is a no-op (no stacking)
        PrimitiveRegistry.with_defaults().invoke(
            "grant_speed", {"target": "ally", "speed_type": "fly",
                            "amount": 60}, st, None)
        self.assertEqual(len(fig.active_speed_grants), 1)


class FlyValuationTest(unittest.TestCase):
    def _state(self, actors):
        st = CombatState(encounter=Encounter(id="t", actors=actors))
        st.content_registry = _registry()
        return st

    def test_zero_when_no_airborne_enemy(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        fig = next(a for a in party if a.id == "Fighter_Champion")
        dragon = _mon("m_adult_red_dragon")          # grounded (elev 0)
        st = self._state(party + [dragon])
        self.assertEqual(offensive_ehp_fly_reach(wiz, fig, st), 0.0)

    def test_zero_vs_superior_melee_flyer(self):
        # Don't fly the Fighter into a dragon it can't out-trade.
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        fig = next(a for a in party if a.id == "Fighter_Champion")
        dragon = _mon("m_adult_red_dragon")
        dragon.elevation = 10
        st = self._state(party + [dragon])
        self.assertEqual(offensive_ehp_fly_reach(wiz, fig, st), 0.0)

    def test_positive_vs_weak_airborne_flyer(self):
        # A weak flyer the Fighter out-DPRs → Fly unlocks real offense.
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        fig = next(a for a in party if a.id == "Fighter_Champion")
        stirge = _mon("m_stirge")
        stirge.elevation = 20
        st = self._state(party + [stirge])
        self.assertGreater(offensive_ehp_fly_reach(wiz, fig, st), 0.0)

    def test_zero_for_ranged_ally(self):
        # A ranged ally already reaches airborne foes → Fly unlocks nothing.
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        stirge = _mon("m_stirge")
        stirge.elevation = 20
        st = self._state(party + [stirge])
        self.assertEqual(offensive_ehp_fly_reach(wiz, wiz, st), 0.0)


if __name__ == "__main__":
    unittest.main()
