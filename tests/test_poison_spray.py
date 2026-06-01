"""Poison Spray tests — SRD spell batch 4 (pc_builder attack_cantrip, Nd12 poison)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.pc_schema import _dispatch_pc_builder
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


def _action(level=1):
    feat = H.registry().get("feature", "f_poison_spray")
    return _dispatch_pc_builder(feat, level=level, ability_scores={"int": {"score": 16}},
                                  proficiency_bonus=2, class_id="c_wizard")


class PoisonSprayTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads_and_scales(self):
        feat = H.registry().get("feature", "f_poison_spray")
        self.assertEqual(feat["spell"]["level"], 0)
        self.assertEqual(feat["pc_builder"]["kind"], "attack_cantrip")
        for lvl, n in [(1, 1), (5, 2), (11, 3), (17, 4)]:
            self.assertEqual(_action(lvl)["pipeline"][1]["params"]["dice"], f"{n}d12")

    def test_no_slot_and_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", score=16, slots={})
        foe = H.enemy(ac=5, hp=30)
        st = H.state([wiz, foe])
        chosen = {"kind": "weapon_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 30)
        self.assertEqual(_action()["spell_slot_level"], 0)


if __name__ == "__main__":
    unittest.main()
