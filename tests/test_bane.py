"""Bane tests — SRD spell batch 3 (CHA save or -1d4 to attacks & saves)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class BaneTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_bane")
        self.assertTrue(a["concentration"])
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "charisma")

    def test_failed_save_applies_penalty(self):
        cle = H.caster(cid="cle", ability="wisdom", slots={1: 1})
        foe = H.enemy(eid="foe", cha=-10)
        other = H.enemy(eid="other", position=(2, 0))
        st = H.state([cle, foe, other])
        chosen = {"kind": "hard_control", "action": H.action_template("f_bane"),
                    "target": foe, "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        # The baned enemy's own attack rolls take -2
        am = modifiers.query_attack_modifiers(foe, other, st)
        self.assertEqual(am.attack_bonus_modifier, -2)
        # ...and its saves take -2
        sm = modifiers.query_save_modifiers(foe, "dexterity", st)
        self.assertEqual(sm.save_bonus_modifier, -2)
        self.assertEqual(cle.concentration_on["action_id"], "a_bane")


if __name__ == "__main__":
    unittest.main()
