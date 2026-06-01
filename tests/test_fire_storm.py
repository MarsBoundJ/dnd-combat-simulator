"""Fire Storm tests — SRD spell batch 3 (sphere, DEX save 7d10 fire)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class FireStormTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_fire_storm")
        self.assertEqual(a["type"], "aoe_attack")
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["params"]["dice"], "7d10")

    def test_burst_damages(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=4, slots={7: 1})
        foe = H.enemy(eid="foe", position=(3, 0), dex=-10, hp=120)
        st = H.state([cle, foe])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_fire_storm"),
                    "target": foe, "origin_point": (3, 0), "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLessEqual(foe.hp_current, 120 - 7)


if __name__ == "__main__":
    unittest.main()
