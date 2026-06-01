"""Mind Spike tests — SRD spell batch 4 (single-target WIS save-for-half 3d8)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.ai.ehp_scoring import offensive_ehp_save_attack
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class MindSpikeTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_mind_spike")
        self.assertEqual(a["type"], "save_attack")
        self.assertTrue(a["half_on_success"])
        self.assertTrue(a["concentration"])

    def test_scores_and_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={2: 1})
        foe = H.enemy(wis=-10, hp=50)
        st = H.state([wiz, foe])
        self.assertGreater(offensive_ehp_save_attack(wiz, foe, H.action_template("f_mind_spike"), st), 0.0)
        chosen = {"kind": "save_attack", "action": H.action_template("f_mind_spike"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 50 - foe.hp_current
        self.assertGreaterEqual(dealt, 3)
        self.assertLessEqual(dealt, 24)


if __name__ == "__main__":
    unittest.main()
