"""Gust of Wind tests — SRD spell batch 4 (60-ft line, STR save or pushed 15 ft)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class GustOfWindTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_gust_of_wind")
        self.assertEqual(a["area"]["shape"], "line")
        self.assertTrue(a["concentration"])
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["primitive"], "forced_movement")

    def test_failed_save_pushes_away(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={2: 1})
        foe = H.enemy(eid="foe", position=(2, 0), str=-10)   # in the +x line
        st = H.state([wiz, foe])
        before = foe.position
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_gust_of_wind"),
                    "target": foe, "origin_point": (0, 0), "direction": (1, 0),
                    "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertGreater(foe.position[0], before[0])       # pushed away from caster


if __name__ == "__main__":
    unittest.main()
