"""Call Lightning tests — SRD spell batch 2 (5-ft burst, DEX save 3d10)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class CallLightningTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_call_lightning")
        self.assertEqual(a["area"]["shape"], "sphere")
        self.assertEqual(a["area"]["radius_ft"], 5)
        self.assertTrue(a["concentration"])
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d10")

    def test_burst_damages_in_radius(self):
        druid = H.caster(cid="druid", ability="wisdom", slots={3: 1})
        near = H.enemy(eid="near", position=(8, 0), dex=-10)
        far = H.enemy(eid="far", position=(12, 0), dex=-10)
        st = H.state([druid, near, far])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_call_lightning"),
                    "target": near, "origin_point": (8, 0), "actor": druid}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in st.event_log if e.get("event") == "forced_save"}
        self.assertEqual(save_targets, {"near"})
        self.assertLess(near.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
