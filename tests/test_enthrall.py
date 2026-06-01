"""Enthrall tests — SRD spell batch 5 (WIS save or Enthralled, -10 Perception)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class EnthrallTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        f = H.registry().get("feature", "f_enthrall")
        self.assertEqual(f["spell"]["level"], 2)
        self.assertTrue(H.action_template("f_enthrall")["concentration"])
        co = H.registry().get("condition", "co_enthralled")
        self.assertEqual(co["scope"], "absolute")

    def test_failed_save_enthralls(self):
        bard = H.caster(cid="bard", ability="charisma", slots={2: 1})
        foe = H.enemy(wis=-10)
        st = H.state([bard, foe])
        chosen = {"kind": "hard_control", "action": H.action_template("f_enthrall"),
                    "target": foe, "actor": bard}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_enthralled", H.condition_ids(foe))
        self.assertEqual(bard.concentration_on["action_id"], "a_enthrall")


if __name__ == "__main__":
    unittest.main()
