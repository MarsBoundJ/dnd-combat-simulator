"""Fear tests — SRD spell batch 2 (30-ft cone, WIS save or Frightened)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class FearTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_fear")
        self.assertEqual(a["area"]["shape"], "cone")
        self.assertTrue(a["concentration"])

    def test_cone_frightens_targets(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={3: 1})
        near = H.enemy(eid="near", position=(2, 0), wis=-10)     # in the +x cone
        off = H.enemy(eid="off", position=(0, 6), wis=-10)        # perpendicular
        st = H.state([wiz, near, off])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_fear"),
                    "target": near, "origin_point": (0, 0), "direction": (1, 0),
                    "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in st.event_log
                         if e.get("event") == "forced_save"}
        self.assertIn("near", save_targets)
        self.assertNotIn("off", save_targets)
        self.assertIn("co_frightened", H.condition_ids(near))
        self.assertIn("near", {e["target_id"] for e in st.recurring_saves})


if __name__ == "__main__":
    unittest.main()
