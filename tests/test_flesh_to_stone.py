"""Flesh to Stone tests — SRD spell batch 4 (CON save or Restrained)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_hard_control
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class FleshToStoneTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_flesh_to_stone")
        self.assertEqual(a["type"], "hard_control")
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "constitution")

    def test_scores_and_restrains(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={6: 1})
        foe = H.enemy(con=-10, hp=80, attack=True)
        st = H.state([wiz, foe])
        self.assertGreater(defensive_ehp_hard_control(
            wiz, foe, H.action_template("f_flesh_to_stone"), st), 0.0)
        chosen = {"kind": "hard_control", "action": H.action_template("f_flesh_to_stone"),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_restrained", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})


if __name__ == "__main__":
    unittest.main()
