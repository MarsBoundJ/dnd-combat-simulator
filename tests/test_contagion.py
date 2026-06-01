"""Contagion tests — SRD spell batch 4 (CON save or 11d8 + Poisoned)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class ContagionTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_contagion")
        self.assertEqual(a["type"], "save_attack")
        self.assertFalse(a.get("concentration"))     # 7 days, not Concentration
        self.assertEqual(a["range_ft"], 5)           # touch

    def test_failed_save_damages_and_poisons(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=4, slots={5: 1})
        foe = H.enemy(con=-10, hp=120)
        st = H.state([cle, foe])
        chosen = {"kind": "save_attack", "action": H.action_template("f_contagion"),
                    "target": foe, "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 120 - foe.hp_current
        self.assertGreaterEqual(dealt, 11)           # 11d8 on a fail
        self.assertIn("co_poisoned", H.condition_ids(foe))
        self.assertEqual({e["target_id"] for e in st.recurring_saves}, {"foe"})


if __name__ == "__main__":
    unittest.main()
