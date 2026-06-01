"""Irresistible Dance tests — SRD spell batch 2 (WIS save or co_dancing)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class IrresistibleDanceTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_irresistible_dance")
        self.assertEqual(a["type"], "hard_control")
        self.assertTrue(a["concentration"])
        co = H.registry().get("condition", "co_dancing")
        self.assertEqual(co["scope"], "absolute")

    def test_failed_save_applies_dancing_debuff(self):
        bard = H.caster(cid="bard", ability="charisma", pb=4, slots={6: 1})
        foe = H.enemy(eid="foe", wis=-10)
        other = H.enemy(eid="other", position=(2, 0))
        st = H.state([bard, foe, other])
        chosen = {"kind": "hard_control", "action": H.action_template("f_irresistible_dance"),
                    "target": foe, "actor": bard}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_dancing", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})
        # The dancing target's own attacks have Disadvantage...
        own = modifiers.query_attack_modifiers(foe, other, st)
        self.assertTrue(own.has_disadvantage)
        # ...and attacks against it have Advantage.
        vs = modifiers.query_attack_modifiers(other, foe, st)
        self.assertTrue(vs.has_advantage)


if __name__ == "__main__":
    unittest.main()
