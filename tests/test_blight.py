"""Blight tests — SRD spell batch 3 (single-target CON save-for-half 8d8)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.ai.ehp_scoring import offensive_ehp_save_attack
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class BlightTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_blight")
        self.assertEqual(a["type"], "save_attack")
        self.assertTrue(a["half_on_success"])
        self.assertEqual(a["upcast_scaling"]["damage_type"], "necrotic")

    def test_scores_and_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=3, slots={4: 1})
        foe = H.enemy(con=-10, hp=80)
        st = H.state([wiz, foe])
        self.assertGreater(offensive_ehp_save_attack(wiz, foe, H.action_template("f_blight"), st), 0.0)
        chosen = {"kind": "save_attack", "action": H.action_template("f_blight"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 80 - foe.hp_current
        self.assertGreaterEqual(dealt, 8)
        self.assertLessEqual(dealt, 64)


if __name__ == "__main__":
    unittest.main()
