"""Charm Person / Charm Monster tests — SRD spell batch 3 (WIS save or Charmed)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class CharmTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_both_load(self):
        self.assertEqual(H.registry().get("feature", "f_charm_person")["spell"]["level"], 1)
        self.assertEqual(H.registry().get("feature", "f_charm_monster")["spell"]["level"], 4)
        # Neither is Concentration (1-hour duration)
        self.assertFalse(H.action_template("f_charm_person").get("concentration"))
        self.assertFalse(H.action_template("f_charm_monster").get("concentration"))

    def _cast(self, fid, slot):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={slot: 1})
        foe = H.enemy(wis=-10)
        st = H.state([wiz, foe])
        chosen = {"kind": "hard_control", "action": H.action_template(fid),
                    "target": foe, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        return foe, st

    def test_charm_person(self):
        foe, st = self._cast("f_charm_person", 1)
        self.assertIn("co_charmed", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})

    def test_charm_monster(self):
        foe, st = self._cast("f_charm_monster", 4)
        self.assertIn("co_charmed", H.condition_ids(foe))


if __name__ == "__main__":
    unittest.main()
