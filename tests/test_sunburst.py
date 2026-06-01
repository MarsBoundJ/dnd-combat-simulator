"""Sunburst tests — SRD spell batch 3 (60-ft sphere, CON save 12d6 + Blinded)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class SunburstTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = H.action_template("f_sunburst")
        self.assertEqual(a["area"]["radius_ft"], 60)
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "constitution")

    def test_damages_and_blinds(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=4, slots={8: 1})
        foe = H.enemy(eid="foe", position=(4, 0), con=-10, hp=120)
        st = H.state([cle, foe])
        chosen = {"kind": "aoe_attack", "action": H.action_template("f_sunburst"),
                    "target": foe, "origin_point": (4, 0), "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 120)
        self.assertIn("co_blinded", H.condition_ids(foe))
        # Sunburst's 60-ft sphere catches everyone in it (friendly fire);
        # the failed-save enemy gets a turn-end CON re-save registered.
        self.assertIn("foe", {e["target_id"] for e in st.recurring_saves})


if __name__ == "__main__":
    unittest.main()
