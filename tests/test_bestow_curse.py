"""Bestow Curse tests — SRD spell batch 3 (WIS save or co_cursed)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class BestowCurseTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_bestow_curse")
        self.assertTrue(a["concentration"])
        co = H.registry().get("condition", "co_cursed")
        self.assertEqual(co["scope"], "absolute")

    def test_failed_save_curses_with_attack_disadvantage(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=3, slots={3: 1})
        foe = H.enemy(eid="foe", wis=-10)
        other = H.enemy(eid="other", position=(2, 0))
        st = H.state([cle, foe, other])
        chosen = {"kind": "hard_control", "action": H.action_template("f_bestow_curse"),
                    "target": foe, "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_cursed", H.condition_ids(foe))
        # The cursed creature's own attacks have Disadvantage
        am = modifiers.query_attack_modifiers(foe, other, st)
        self.assertTrue(am.has_disadvantage)
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})


if __name__ == "__main__":
    unittest.main()
