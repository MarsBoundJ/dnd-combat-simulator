"""Vitriolic Sphere tests — SRD spell batch 3 (20-ft sphere, DEX save 10d4 acid)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class VitriolicSphereTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_vitriolic_sphere")
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["params"]["type"], "acid")
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "2d4")

    def test_burst_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=3, slots={4: 1})
        foe = H.enemy(eid="foe", position=(3, 0), dex=-10, hp=60)
        st = H.state([wiz, foe])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_vitriolic_sphere"),
                    "target": foe, "origin_point": (3, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLessEqual(foe.hp_current, 60 - 10)


if __name__ == "__main__":
    unittest.main()
