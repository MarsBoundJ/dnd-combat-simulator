"""Acid Arrow tests — SRD spell batch 4 (pc_builder spell_attack, 4d4 acid)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.pc_schema import _dispatch_pc_builder
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


def _action():
    feat = H.registry().get("feature", "f_acid_arrow")
    return _dispatch_pc_builder(feat, level=5, ability_scores={"int": {"score": 18}},
                                  proficiency_bonus=3, class_id="c_wizard")


class AcidArrowTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads_and_builds(self):
        feat = H.registry().get("feature", "f_acid_arrow")
        self.assertEqual(feat["spell"]["level"], 2)
        self.assertEqual(feat["pc_builder"]["kind"], "spell_attack")
        a = _action()
        self.assertEqual(a["pipeline"][0]["params"]["bonus"], 4 + 3)   # INT+4, PB 3
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "4d4")
        self.assertEqual(a["pipeline"][1]["params"]["type"], "acid")
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d4")

    def test_hits_and_damages(self):
        wiz = H.caster(cid="wiz", ability="intelligence", score=18, pb=3, slots={2: 1})
        foe = H.enemy(ac=5, hp=40)
        st = H.state([wiz, foe])
        chosen = {"kind": "weapon_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
