"""Eyebite tests — SRD spell batch 3 (WIS save or Frightened)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class EyebiteTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_eyebite")
        self.assertEqual(a["type"], "hard_control")
        self.assertTrue(a["concentration"])

    def test_failed_save_frightens(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={6: 1})
        foe = H.enemy(wis=-10)
        st = H.state([wiz, foe])
        chosen = {"kind": "hard_control", "action": H.action_template("f_eyebite"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_frightened", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})


if __name__ == "__main__":
    unittest.main()
