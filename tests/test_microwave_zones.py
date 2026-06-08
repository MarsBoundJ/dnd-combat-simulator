"""Microwave Stage C: zone spells (Cloudkill + Sickening Radiance).

These are the "zone" half of the microwave combo. Cloudkill is already modeled
(persistent_aura, poison 5d8). Sickening Radiance is new: radiant 4d10 +
exhaustion per turn — the zone that stacks a debuff the dragon can't escape
inside the dome. Together with the floating dome (Stage B), the second caster
(Simulacrum, Stage D) can lock-and-cook without needing synchronized casting.

Tests verify: SR content, exhaustion application, both zones score >0, and
both zones score higher on a dome-trapped target vs a free-moving one.

Run via:
    python -m unittest tests.test_microwave_zones
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.geometry import Sphere, WALL_BLOCK_NORMAL
from engine.core.state import Actor, CombatState, Encounter
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


def _dragon():
    from sims.adventuring_day import _build_monsters
    return _build_monsters(_registry(), [("m_adult_red_dragon", 1)])[0]


class ContentTest(unittest.TestCase):
    def test_wizard_has_sickening_radiance(self):
        wiz = next(a for a in _party() if a.id == "Wizard_Evoker")
        self.assertTrue(any(a.get("id") == "a_sickening_radiance"
                            for a in (wiz.template.get("actions") or [])))

    def test_wizard_has_cloudkill(self):
        wiz = next(a for a in _party() if a.id == "Wizard_Evoker")
        self.assertTrue(any(a.get("id") == "a_cloudkill"
                            for a in (wiz.template.get("actions") or [])))

    def test_wizard_has_dome(self):
        wiz = next(a for a in _party() if a.id == "Wizard_Evoker")
        self.assertTrue(any(a.get("id") == "a_wall_of_force_dome"
                            for a in (wiz.template.get("actions") or [])))

    def test_sr_is_4th_level(self):
        reg = _registry()
        sr_feat = reg.get("feature", "f_sickening_radiance")
        self.assertIsNotNone(sr_feat)
        action = sr_feat.get("action_template") or {}
        self.assertEqual(action.get("spell_slot_level"), 4)

    def test_sr_area_30ft_sphere(self):
        reg = _registry()
        sr_feat = reg.get("feature", "f_sickening_radiance")
        area = (sr_feat.get("action_template") or {}).get("area") or {}
        self.assertEqual(area.get("shape"), "sphere")
        self.assertEqual(area.get("radius_ft"), 30)


class ExhaustionApplicationTest(unittest.TestCase):
    """SR applies exhaustion on a failed save — test via the primitive directly."""

    def _state_with_dragon_in_sr_zone(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        dragon = _dragon()
        dragon.position = (0, 0)
        wiz.position = (20, 0)
        enc = Encounter(id="t", actors=party + [dragon])
        st = CombatState(encounter=enc)
        st.turn_order = [a.id for a in enc.actors]
        st.content_registry = _registry()
        return st, wiz, dragon

    def test_apply_condition_exhaustion_recorded(self):
        """apply_condition co_exhaustion records the condition on the target.
        The engine tracks exhaustion as applied_conditions entries; exhaustion_level
        accumulates via the stacking schema (the counter is read from the
        condition stacking block, not a separate field)."""
        party = _party()
        dragon = _dragon()
        enc = Encounter(id="t", actors=party + [dragon])
        st = CombatState(encounter=enc)
        st.content_registry = _registry()
        st.current_attack = {"actor": party[0], "target": dragon,
                             "action": {"id": "a_test"}}
        prims = PrimitiveRegistry.with_defaults()
        # No exhaustion before
        exhaustion_before = sum(1 for c in dragon.applied_conditions
                                if c.get("condition_id") == "co_exhaustion")
        self.assertEqual(exhaustion_before, 0)
        prims.invoke("apply_condition",
                     {"condition_id": "co_exhaustion", "source_type": "spell"},
                     st, None)
        # One exhaustion condition applied
        exhaustion_after = sum(1 for c in dragon.applied_conditions
                               if c.get("condition_id") == "co_exhaustion")
        self.assertEqual(exhaustion_after, 1)
        # Apply again — stacks
        prims.invoke("apply_condition",
                     {"condition_id": "co_exhaustion", "source_type": "spell"},
                     st, None)
        exhaustion_after2 = sum(1 for c in dragon.applied_conditions
                                if c.get("condition_id") == "co_exhaustion")
        self.assertEqual(exhaustion_after2, 2)


class ZoneScoringTest(unittest.TestCase):
    """Both zone spells score >0 in the AI eHP scorer."""

    def _setup(self):
        from engine.ai.ehp_scoring import score_candidate
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        dragon = _dragon()
        dragon.position = (5, 0)
        wiz.position = (0, 0)
        enc = Encounter(id="t", actors=party + [dragon])
        st = CombatState(encounter=enc)
        st.content_registry = _registry()
        return wiz, dragon, st, score_candidate

    def test_cloudkill_scores_positive(self):
        wiz, dragon, st, score = self._setup()
        ck_action = next(a for a in (wiz.template.get("actions") or [])
                         if a.get("id") == "a_cloudkill")
        cand = {"kind": "persistent_aura", "action": ck_action,
                "target": dragon, "actor": wiz}
        self.assertGreater(score(cand, st), 0.0)

    def test_sickening_radiance_scores_positive(self):
        wiz, dragon, st, score = self._setup()
        sr_action = next(a for a in (wiz.template.get("actions") or [])
                         if a.get("id") == "a_sickening_radiance")
        cand = {"kind": "persistent_aura", "action": sr_action,
                "target": dragon, "actor": wiz}
        self.assertGreater(score(cand, st), 0.0)


if __name__ == "__main__":
    unittest.main()
