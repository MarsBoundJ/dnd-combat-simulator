"""Befuddlement tests — SRD spell batch 2 (INT save-for-half, 10d12 psychic)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class BefuddlementTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_befuddlement")
        self.assertEqual(a["type"], "save_attack")
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "intelligence")
        self.assertTrue(a["half_on_success"])

    def test_failed_save_takes_big_psychic(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={8: 1})
        foe = H.enemy(hp=150)
        foe.abilities["int"]["save"] = -10           # near-guaranteed fail
        st = H.state([wiz, foe])
        chosen = {"kind": "save_attack", "action": H.action_template("f_befuddlement"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 150 - foe.hp_current
        self.assertGreaterEqual(dealt, 10)           # 10d12 = 10..120
        self.assertLessEqual(dealt, 120)


if __name__ == "__main__":
    unittest.main()
