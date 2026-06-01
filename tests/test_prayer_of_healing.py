"""Prayer of Healing tests — SRD spell batch 5 (static multi-target 2d8 heal)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class PrayerOfHealingTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        a = H.action_template("f_prayer_of_healing")
        self.assertEqual(a["type"], "heal")
        self.assertEqual(a["max_targets"], 5)
        # Flat 2d8, no caster modifier baked in (RAW Prayer of Healing has none)
        self.assertEqual(a["pipeline"][0]["params"]["dice"], "2d8")
        self.assertNotIn("modifier", a["pipeline"][0]["params"])

    def test_heals_a_group(self):
        cle = H.caster(cid="cle", ability="wisdom", slots={2: 1})
        a1 = H.ally(aid="a1", hp=5, hp_max=40)
        a2 = H.ally(aid="a2", hp=10, hp_max=40)
        st = H.state([cle, a1, a2])
        action = H.action_template("f_prayer_of_healing")
        chosen = {"kind": "heal", "action": action, "target": a1,
                    "targets": [a1, a2], "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertGreater(a1.hp_current, 5)
        self.assertGreater(a2.hp_current, 10)
        self.assertEqual(cle.spell_slots.get(2), 0)


if __name__ == "__main__":
    unittest.main()
