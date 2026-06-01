"""Harm tests — SRD spell batch 3 (single-target CON save-for-half 14d6)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class HarmTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_harm")
        self.assertEqual(a["type"], "save_attack")
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["params"]["dice"], "14d6")

    def test_failed_save_big_necrotic(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=4, slots={6: 1})
        foe = H.enemy(con=-10, hp=120)
        st = H.state([cle, foe])
        chosen = {"kind": "save_attack", "action": H.action_template("f_harm"),
                    "target": foe, "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 120 - foe.hp_current
        self.assertGreaterEqual(dealt, 14)
        self.assertLessEqual(dealt, 84)


if __name__ == "__main__":
    unittest.main()
