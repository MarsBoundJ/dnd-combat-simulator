"""Dominate Person / Monster tests — SRD spell batch 2 (WIS save or Charmed)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class DominateTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_both_load(self):
        self.assertEqual(H.registry().get("feature", "f_dominate_person")["spell"]["level"], 5)
        self.assertEqual(H.registry().get("feature", "f_dominate_monster")["spell"]["level"], 8)

    def _cast(self, feature_id, slot):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={slot: 1})
        foe = H.enemy(wis=-10)
        st = H.state([wiz, foe])
        chosen = {"kind": "hard_control", "action": H.action_template(feature_id),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        return wiz, foe, st

    def test_dominate_person_charms(self):
        _, foe, st = self._cast("f_dominate_person", 5)
        self.assertIn("co_charmed", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})

    def test_dominate_monster_charms(self):
        _, foe, st = self._cast("f_dominate_monster", 8)
        self.assertIn("co_charmed", H.condition_ids(foe))


if __name__ == "__main__":
    unittest.main()
