"""Burning Hands tests — SRD spell batch 3 (15-ft cone, DEX save 3d6 fire)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class BurningHandsTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_burning_hands")
        self.assertEqual(a["area"]["shape"], "cone")
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d6")

    def test_cone_burst(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={1: 1})
        inline = H.enemy(eid="inline", position=(2, 0), dex=-10, hp=40)
        off = H.enemy(eid="off", position=(0, 6), dex=-10, hp=40)
        st = H.state([wiz, inline, off])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_burning_hands"),
                    "target": inline, "origin_point": (0, 0), "direction": (1, 0),
                    "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in st.event_log if e.get("event") == "forced_save"}
        self.assertIn("inline", save_targets)
        self.assertNotIn("off", save_targets)
        self.assertLess(inline.hp_current, 40)
        self.assertEqual(wiz.spell_slots.get(1), 0)


if __name__ == "__main__":
    unittest.main()
