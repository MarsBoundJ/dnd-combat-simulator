"""Ray of Sickness tests — SRD spell batch 4 (pc_builder spell_attack, 2d8 poison)."""
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
    feat = H.registry().get("feature", "f_ray_of_sickness")
    return _dispatch_pc_builder(feat, level=1, ability_scores={"int": {"score": 16}},
                                  proficiency_bonus=2, class_id="c_wizard")


class RayOfSicknessTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        feat = H.registry().get("feature", "f_ray_of_sickness")
        self.assertEqual(feat["spell"]["level"], 1)
        a = _action()
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "2d8")
        self.assertEqual(a["pipeline"][1]["params"]["type"], "poison")
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d8")

    def test_hits_and_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", score=16, slots={1: 1})
        foe = H.enemy(ac=5, hp=30)
        st = H.state([wiz, foe])
        chosen = {"kind": "weapon_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 30)


if __name__ == "__main__":
    unittest.main()
