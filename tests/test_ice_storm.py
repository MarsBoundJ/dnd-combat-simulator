"""Ice Storm tests — SRD spell batch 3 (sphere, DEX save 2d10 + 4d6)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class IceStormTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_ice_storm")
        on_fail = a["pipeline"][0]["params"]["on_fail"]
        types = {s["params"]["type"] for s in on_fail}
        self.assertEqual(types, {"bludgeoning", "cold"})

    def test_two_damage_types_land(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=3, slots={4: 1})
        near = H.enemy(eid="near", position=(2, 0), dex=-10, hp=80)
        far = H.enemy(eid="far", position=(10, 0), dex=-10, hp=80)
        st = H.state([wiz, near, far])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_ice_storm"),
                    "target": near, "origin_point": (2, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in st.event_log if e.get("event") == "forced_save"}
        self.assertIn("near", save_targets)
        self.assertNotIn("far", save_targets)        # 40 ft from origin, outside 20-ft radius
        # 2d10 + 4d6 on a fail → at least 6 damage landed
        self.assertLessEqual(near.hp_current, 80 - 6)


if __name__ == "__main__":
    unittest.main()
