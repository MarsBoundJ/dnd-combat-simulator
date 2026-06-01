"""Phantasmal Killer tests — SRD spell batch 4 (WIS save 4d10 psychic + Cursed)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class PhantasmalKillerTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_phantasmal_killer")
        self.assertEqual(a["type"], "save_attack")
        self.assertTrue(a["half_on_success"])
        self.assertTrue(a["concentration"])

    def test_failed_save_damages_and_curses(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={4: 1})
        foe = H.enemy(eid="foe", wis=-10, hp=80)
        other = H.enemy(eid="other", position=(2, 0))
        st = H.state([wiz, foe, other])
        chosen = {"kind": "save_attack", "action": H.action_template("f_phantasmal_killer"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 80 - foe.hp_current
        self.assertGreaterEqual(dealt, 4)            # 4d10 on a fail
        self.assertIn("co_cursed", H.condition_ids(foe))
        # Cursed → the target's attacks have Disadvantage
        self.assertTrue(modifiers.query_attack_modifiers(foe, other, st).has_disadvantage)
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})


if __name__ == "__main__":
    unittest.main()
