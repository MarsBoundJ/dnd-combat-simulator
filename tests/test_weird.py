"""Weird tests — SRD spell batch 5 (30-ft sphere, WIS save 10d10 + Frightened)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class WeirdTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_weird")
        self.assertEqual(a["area"]["radius_ft"], 30)
        self.assertTrue(a["concentration"])
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["params"]["dice"], "10d10")

    def test_failed_save_damages_and_frightens(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=6, slots={9: 1})
        near = H.enemy(eid="near", position=(3, 0), wis=-10, hp=150)
        far = H.enemy(eid="far", position=(10, 0), wis=-10, hp=150)   # 50 ft from origin
        st = H.state([wiz, near, far])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_weird"),
                    "target": near, "origin_point": (3, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(near.hp_current, 150)
        self.assertIn("co_frightened", H.condition_ids(near))
        self.assertNotIn("co_frightened", H.condition_ids(far))
        self.assertIn("near", {e["target_id"] for e in st.recurring_saves})


if __name__ == "__main__":
    unittest.main()
