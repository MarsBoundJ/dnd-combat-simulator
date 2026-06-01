"""Mass Healing Word tests — SRD spell batch 2 (BA multi-target 2d4+mod heal)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.pc_schema import _build_mass_healing_word_action
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


def _abil(wis=16):
    return {"wis": {"score": wis}}


class MassHealingWordTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        f = H.registry().get("feature", "f_mass_healing_word")
        self.assertEqual(f["spell"]["level"], 3)
        self.assertEqual(f["source"], "srd_5.2.1")

    def test_builder(self):
        a = _build_mass_healing_word_action(5, _abil(16), "c_cleric")
        self.assertEqual(a["type"], "heal")
        self.assertEqual(a["slot"], "bonus_action")
        self.assertEqual(a["max_targets"], 6)
        self.assertEqual(a["pipeline"][0]["params"]["dice"], "2d4")
        self.assertEqual(a["pipeline"][0]["params"]["modifier"], 3)   # WIS+3

    def test_heals_a_group(self):
        cleric = H.caster(cid="cleric", ability="wisdom", score=16, slots={3: 1})
        a1 = H.ally(aid="a1", hp=5, hp_max=40)
        a2 = H.ally(aid="a2", hp=8, hp_max=40)
        st = H.state([cleric, a1, a2])
        action = _build_mass_healing_word_action(5, _abil(16), "c_cleric")
        chosen = {"kind": "heal", "action": action, "target": a1,
                    "targets": [a1, a2], "actor": cleric}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertGreater(a1.hp_current, 5)
        self.assertGreater(a2.hp_current, 8)
        self.assertEqual(cleric.spell_slots.get(3), 0)


if __name__ == "__main__":
    unittest.main()
