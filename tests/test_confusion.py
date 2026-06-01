"""Confusion tests — SRD spell batch 3 (AoE WIS save or Incapacitated)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class ConfusionTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_confusion")
        self.assertEqual(a["area"]["shape"], "sphere")
        self.assertEqual(a["area"]["radius_ft"], 10)
        self.assertTrue(a["concentration"])

    def test_in_sphere_incapacitated(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=3, slots={4: 1})
        near = H.enemy(eid="near", position=(2, 0), wis=-10)
        far = H.enemy(eid="far", position=(8, 0), wis=-10)   # 40 ft from origin
        st = H.state([wiz, near, far])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_confusion"),
                    "target": near, "origin_point": (2, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_incapacitated", H.condition_ids(near))
        self.assertNotIn("co_incapacitated", H.condition_ids(far))
        self.assertIn("near", {e["target_id"] for e in st.recurring_saves})


if __name__ == "__main__":
    unittest.main()
