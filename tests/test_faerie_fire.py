"""Faerie Fire tests — SRD spell batch 2 (AoE DEX save, attackers get advantage)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class FaerieFireTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        f = H.registry().get("feature", "f_faerie_fire")
        self.assertEqual(f["spell"]["level"], 1)
        self.assertTrue(H.action_template("f_faerie_fire")["concentration"])
        co = H.registry().get("condition", "co_faerie_fire")
        self.assertEqual(co["scope"], "absolute")

    def test_outlines_and_grants_attacker_advantage(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={1: 1})
        foe = H.enemy(eid="foe", position=(2, 0), dex=-10)
        ally = H.enemy(eid="striker", position=(1, 0))   # any attacker who can see foe
        st = H.state([wiz, foe, ally])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_faerie_fire"),
                    "target": foe, "origin_point": (2, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_faerie_fire", H.condition_ids(foe))
        # An attacker now has advantage against the outlined target
        am = modifiers.query_attack_modifiers(ally, foe, st)
        self.assertTrue(am.net_advantage() == "advantage" or am.has_advantage)


if __name__ == "__main__":
    unittest.main()
