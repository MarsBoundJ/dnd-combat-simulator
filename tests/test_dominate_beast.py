"""Dominate Beast tests — SRD spell batch 4 (WIS save or Charmed)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class DominateBeastTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        f = H.registry().get("feature", "f_dominate_beast")
        self.assertEqual(f["spell"]["level"], 4)
        self.assertTrue(H.action_template("f_dominate_beast")["concentration"])

    def test_failed_save_charms(self):
        dru = H.caster(cid="dru", ability="wisdom", pb=3, slots={4: 1})
        foe = H.enemy(wis=-10)
        st = H.state([dru, foe])
        chosen = {"kind": "hard_control", "action": H.action_template("f_dominate_beast"),
                    "target": foe, "actor": dru}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_charmed", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})
        self.assertEqual(dru.concentration_on["action_id"], "a_dominate_beast")


if __name__ == "__main__":
    unittest.main()
