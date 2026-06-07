"""Animate Objects (Lever B Stage 2d) — the Bard's big concentration summon.

Ten Tiny animated objects, each a Slam attacker, deal a large recurring Force
stream every round WHILE the Bard's own action drops a Synaptic Static. Reuses
the Bigby's-Hand (2c) summon pipeline wholesale — only monster id + count
differ — and plugs into the Stage 2a lifecycle (all ten vanish at concentration
end) + the Stage 2b summon scorer.

Run via:
    python -m unittest tests.test_animate_objects
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.defensive_ehp import estimate_dpr
from engine.ai.ehp_scoring import offensive_ehp_summon
from engine.cli import _build_actor
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.state import Encounter, CombatState
from engine.loader import load_content
from engine.pc_schema import build_pc_template
from engine.primitives import _summon

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _actions(cls, level):
    spec = {"class": cls, "level": level,
            "ability_scores": {"str": 8, "dex": 12, "con": 14,
                                "int": 14, "wis": 12, "cha": 18}}
    return {a.get("id"): a for a in build_pc_template(spec, _registry())
            .get("actions", [])}


class AnimateObjectsContentTest(unittest.TestCase):

    def test_on_bard_sorcerer_wizard_at_l13(self):
        self.assertIn("a_animate_objects", _actions("c_bard", 13))
        self.assertIn("a_animate_objects", _actions("c_sorcerer", 13))
        self.assertIn("a_animate_objects", _actions("c_wizard", 13))

    def test_gated_to_char_level_9(self):
        self.assertNotIn("a_animate_objects", _actions("c_bard", 8))
        self.assertIn("a_animate_objects", _actions("c_bard", 9))

    def test_shape_is_concentration_summon_of_ten(self):
        ao = _actions("c_bard", 13)["a_animate_objects"]
        self.assertEqual(ao["type"], "summon")
        self.assertEqual(ao["spell_slot_level"], 5)
        self.assertTrue(ao.get("concentration"))
        params = ao["pipeline"][0]["params"]
        self.assertEqual(params["monster"], "m_animated_object")
        self.assertEqual(params["count"], 10)
        self.assertEqual(params["max_total"], 10)

    def test_object_stat_block_slam(self):
        obj = _build_actor(
            {"template_ref": {"entity_type": "monster",
                              "id": "m_animated_object"},
             "instance_id": "__obj__", "position": [0, 0]}, _registry())
        ids = {a.get("id") for a in (obj.template.get("actions") or [])}
        self.assertIn("a_animated_slam", ids)
        self.assertGreater(estimate_dpr(obj), 0.0)


class AnimateObjectsIntegrationTest(unittest.TestCase):

    def _bard(self):
        return _build_actor(
            {"instance_id": "bard", "side": "pc",
             "pc": {"class": "c_bard", "level": 13,
                    "ability_scores": {"str": 8, "dex": 12, "con": 14,
                                        "int": 14, "wis": 12, "cha": 18}}},
            _registry())

    def _foe(self):
        return _build_actor(
            {"instance_id": "foe", "side": "enemy", "position": [4, 0],
             "template_ref": {"entity_type": "monster",
                              "id": "m_fire_giant"}}, _registry())

    def _state(self, actors):
        st = CombatState(encounter=Encounter(id="t", actors=list(actors)))
        st.turn_order = [a.id for a in actors]
        st.round = 1
        st.content_registry = _registry()
        return st

    def test_cast_summons_ten_and_concentration_dismisses_all(self):
        bard, foe = self._bard(), self._foe()
        st = self._state([bard, foe])
        ao = {a.get("id"): a for a in bard.template.get("actions", [])}[
            "a_animate_objects"]

        apply_concentration(bard, ao, st)
        st.current_attack = {"actor": bard, "action": ao}
        _summon(ao["pipeline"][0]["params"], st, EventBus())

        objs = [a for a in st.encounter.actors if a.summoned_by == "bard"]
        self.assertEqual(len(objs), 10)
        for o in objs:
            self.assertEqual(o.summon_concentration,
                             {"caster_id": "bard",
                              "action_id": "a_animate_objects"})
            self.assertIn(o.id, st.turn_order)

        end_concentration(bard, st, reason="dropped")
        roster = {a.id for a in st.encounter.actors}
        for o in objs:
            self.assertNotIn(o.id, roster)
            self.assertNotIn(o.id, st.turn_order)

    def test_ai_values_the_summon_highly(self):
        bard, foe = self._bard(), self._foe()
        st = self._state([bard, foe])
        ao = {a.get("id"): a for a in bard.template.get("actions", [])}[
            "a_animate_objects"]
        # Ten attackers → a large recurring stream; comfortably positive.
        self.assertGreater(offensive_ehp_summon(bard, ao, st), 0.0)


if __name__ == "__main__":
    unittest.main()
