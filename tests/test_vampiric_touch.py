"""Vampiric Touch tests — SRD spell batch 4 (pc_builder spell_attack, 3d6 necrotic melee)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.pc_schema import _dispatch_pc_builder
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


def _action():
    feat = H.registry().get("feature", "f_vampiric_touch")
    return _dispatch_pc_builder(feat, level=5, ability_scores={"int": {"score": 18}},
                                  proficiency_bonus=3, class_id="c_wizard")


class VampiricTouchTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        feat = H.registry().get("feature", "f_vampiric_touch")
        self.assertEqual(feat["spell"]["level"], 3)
        a = _action()
        self.assertEqual(a["pipeline"][0]["params"]["range_ft"], 5)   # melee reach
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "3d6")
        self.assertEqual(a["pipeline"][1]["params"]["type"], "necrotic")

    def test_hits_and_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", score=18, pb=3, slots={3: 1})
        foe = H.enemy(ac=5, hp=40, position=(1, 0))
        st = H.state([wiz, foe])
        chosen = {"kind": "weapon_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
