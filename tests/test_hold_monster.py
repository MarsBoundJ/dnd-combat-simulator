"""Hold Monster tests — SRD spell batch 2 (WIS save or Paralyzed, any creature)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_hard_control
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class HoldMonsterTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_hold_monster")
        self.assertEqual(a["range_ft"], 90)
        self.assertTrue(a["concentration"])

    def test_scores_and_paralyzes(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={5: 1})
        foe = H.enemy(wis=-10, hp=60, attack=True)
        st = H.state([wiz, foe])
        self.assertGreater(defensive_ehp_hard_control(
            wiz, foe, H.action_template("f_hold_monster"), st), 0.0)
        chosen = {"kind": "hard_control", "action": H.action_template("f_hold_monster"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_paralyzed", H.condition_ids(foe))
        self.assertIn("co_incapacitated", H.condition_ids(foe))   # inherited
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})


if __name__ == "__main__":
    unittest.main()
