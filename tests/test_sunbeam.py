"""Sunbeam tests — SRD spell batch 2 (60-ft line, CON save 6d8 radiant + Blinded)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class SunbeamTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_sunbeam")
        self.assertEqual(a["area"]["shape"], "line")
        self.assertEqual(a["area"]["length_ft"], 60)
        self.assertTrue(a["concentration"])

    def test_line_damages_and_blinds(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=4, slots={6: 1})
        inline = H.enemy(eid="inline", position=(4, 0), con=-10, hp=80)
        off = H.enemy(eid="off", position=(0, 6), con=-10, hp=80)
        st = H.state([cle, inline, off])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_sunbeam"),
                    "target": inline, "origin_point": (0, 0), "direction": (1, 0),
                    "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in st.event_log if e.get("event") == "forced_save"}
        self.assertIn("inline", save_targets)
        self.assertNotIn("off", save_targets)
        self.assertLess(inline.hp_current, 80)
        self.assertIn("co_blinded", H.condition_ids(inline))


if __name__ == "__main__":
    unittest.main()
