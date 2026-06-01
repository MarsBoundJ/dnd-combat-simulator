"""Mass Cure Wounds tests — SRD spell batch 2 (multi-target 5d8+mod heal)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.pc_schema import _build_mass_cure_wounds_action
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


def _abil(wis=18):
    return {"wis": {"score": wis}}


class MassCureWoundsTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        f = H.registry().get("feature", "f_mass_cure_wounds")
        self.assertEqual(f["spell"]["level"], 5)

    def test_builder(self):
        a = _build_mass_cure_wounds_action(9, _abil(18), "c_cleric")
        self.assertEqual(a["max_targets"], 6)
        self.assertEqual(a["pipeline"][0]["params"]["dice"], "5d8")
        self.assertEqual(a["pipeline"][0]["params"]["modifier"], 4)   # WIS+4

    def test_heals_a_group(self):
        cleric = H.caster(cid="cleric", ability="wisdom", score=18, slots={5: 1})
        a1 = H.ally(aid="a1", hp=10, hp_max=80)
        a2 = H.ally(aid="a2", hp=20, hp_max=80)
        st = H.state([cleric, a1, a2])
        action = _build_mass_cure_wounds_action(9, _abil(18), "c_cleric")
        chosen = {"kind": "heal", "action": action, "target": a1,
                    "targets": [a1, a2], "actor": cleric}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertGreaterEqual(a1.hp_current, 10 + 9)   # 5d8+4 ≥ 9
        self.assertGreaterEqual(a2.hp_current, 20 + 9)


if __name__ == "__main__":
    unittest.main()
