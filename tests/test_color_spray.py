"""Color Spray tests — SRD spell batch 4 (15-ft cone, CON save or Blinded)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class ColorSprayTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_color_spray")
        self.assertEqual(a["area"]["shape"], "cone")
        self.assertFalse(a.get("concentration"))

    def test_cone_blinds_inline(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={1: 1})
        inline = H.enemy(eid="inline", position=(2, 0), con=-10)
        off = H.enemy(eid="off", position=(0, 6), con=-10)
        st = H.state([wiz, inline, off])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_color_spray"),
                    "target": inline, "origin_point": (0, 0), "direction": (1, 0),
                    "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_blinded", H.condition_ids(inline))
        self.assertNotIn("co_blinded", H.condition_ids(off))


if __name__ == "__main__":
    unittest.main()
