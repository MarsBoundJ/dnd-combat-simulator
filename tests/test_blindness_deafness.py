"""Blindness/Deafness tests — SRD spell batch 2 (CON save or Blinded)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class BlindnessDeafnessTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        f = H.registry().get("feature", "f_blindness_deafness")
        self.assertEqual(f["spell"]["level"], 2)
        self.assertFalse(H.action_template("f_blindness_deafness").get("concentration"))

    def test_failed_save_blinds_and_resaves(self):
        cle = H.caster(cid="cle", ability="wisdom", slots={2: 1})
        foe = H.enemy(con=-10)
        st = H.state([cle, foe])
        chosen = {"kind": "hard_control", "action": H.action_template("f_blindness_deafness"),
                    "target": foe, "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_blinded", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})


if __name__ == "__main__":
    unittest.main()
