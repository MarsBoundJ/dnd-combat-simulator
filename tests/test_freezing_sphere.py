"""Freezing Sphere tests — SRD spell batch 4 (60-ft sphere, CON save 10d6 cold)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class FreezingSphereTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_freezing_sphere")
        self.assertEqual(a["area"]["radius_ft"], 60)
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["params"]["dice"], "10d6")

    def test_burst_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={6: 1})
        foe = H.enemy(eid="foe", position=(4, 0), con=-10, hp=90)
        st = H.state([wiz, foe])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_freezing_sphere"),
                    "target": foe, "origin_point": (4, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 90)


if __name__ == "__main__":
    unittest.main()
