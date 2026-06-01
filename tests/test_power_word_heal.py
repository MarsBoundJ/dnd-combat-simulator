"""Power Word Heal tests — SRD spell batch 2 (single-target full heal)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class PowerWordHealTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        f = H.registry().get("feature", "f_power_word_heal")
        self.assertEqual(f["spell"]["level"], 9)
        self.assertEqual(H.action_template("f_power_word_heal")["pipeline"][0]["params"]["fixed"], 9999)

    def test_restores_to_full(self):
        cle = H.caster(cid="cle", ability="wisdom", slots={9: 1})
        tank = H.ally(aid="tank", hp=7, hp_max=300)
        st = H.state([cle, tank])
        chosen = {"kind": "heal", "action": H.action_template("f_power_word_heal"),
                    "target": tank, "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(tank.hp_current, 300)         # full, clamped
        self.assertEqual(cle.spell_slots.get(9), 0)


if __name__ == "__main__":
    unittest.main()
