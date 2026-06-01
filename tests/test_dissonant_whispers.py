"""Dissonant Whispers tests — SRD spell batch 2 (WIS save-for-half, 3d6 psychic)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.ai.ehp_scoring import offensive_ehp_save_attack
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class DissonantWhispersTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_dissonant_whispers")
        self.assertEqual(a["type"], "save_attack")
        self.assertTrue(a["half_on_success"])

    def test_scores_and_damages(self):
        bard = H.caster(cid="bard", ability="charisma", slots={1: 1})
        foe = H.enemy(wis=-10, hp=40)
        st = H.state([bard, foe])
        self.assertGreater(offensive_ehp_save_attack(
            bard, foe, H.action_template("f_dissonant_whispers"), st), 0.0)
        chosen = {"kind": "save_attack", "action": H.action_template("f_dissonant_whispers"),
                    "target": foe, "actor": bard}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 40 - foe.hp_current
        self.assertGreaterEqual(dealt, 3)
        self.assertLessEqual(dealt, 18)


if __name__ == "__main__":
    unittest.main()
