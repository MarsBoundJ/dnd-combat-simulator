"""Hideous Laughter tests — SRD spell batch 2 (WIS save or Incapacitated)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class HideousLaughterTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_hideous_laughter")
        self.assertEqual(a["type"], "hard_control")
        self.assertTrue(a["concentration"])

    def test_incapacitates_and_resaves(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={1: 1})
        foe = H.enemy(wis=-10)
        st = H.state([wiz, foe])
        chosen = {"kind": "hard_control", "action": H.action_template("f_hideous_laughter"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_incapacitated", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})
        self.assertEqual(wiz.concentration_on["action_id"], "a_hideous_laughter")


if __name__ == "__main__":
    unittest.main()
