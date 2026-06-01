"""Cone of Cold tests — SRD spell batch 3 (60-ft cone, CON save 8d8 cold)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class ConeOfColdTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_cone_of_cold")
        self.assertEqual(a["area"]["shape"], "cone")
        self.assertEqual(a["area"]["length_ft"], 60)
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "constitution")

    def test_cone_damages_inline(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={5: 1})
        inline = H.enemy(eid="inline", position=(4, 0), con=-10, hp=80)
        st = H.state([wiz, inline])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_cone_of_cold"),
                    "target": inline, "origin_point": (0, 0), "direction": (1, 0),
                    "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(inline.hp_current, 80)


if __name__ == "__main__":
    unittest.main()
