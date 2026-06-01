"""Finger of Death tests — SRD spell batch 3 (CON save-for-half 7d8+30)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class FingerOfDeathTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_finger_of_death")
        on_fail = a["pipeline"][0]["params"]["on_fail"][0]["params"]
        self.assertEqual(on_fail["dice"], "7d8")
        self.assertEqual(on_fail["modifier"], 30)

    def test_failed_save(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={7: 1})
        foe = H.enemy(con=-10, hp=120)
        st = H.state([wiz, foe])
        chosen = {"kind": "save_attack", "action": H.action_template("f_finger_of_death"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 120 - foe.hp_current
        self.assertGreaterEqual(dealt, 7 + 30)        # 7d8+30 on a fail
        self.assertLessEqual(dealt, 56 + 30)


if __name__ == "__main__":
    unittest.main()
