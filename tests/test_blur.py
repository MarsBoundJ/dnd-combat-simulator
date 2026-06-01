"""Blur tests — SRD spell batch 3 (self buff: attackers have Disadvantage)."""
from __future__ import annotations

import unittest

from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class BlurTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_blur")
        self.assertEqual(a["type"], "defensive_buff")
        self.assertTrue(a["concentration"])

    def test_cast_imposes_disadvantage_on_attackers(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={2: 1})
        foe = H.enemy(eid="foe", position=(1, 0))
        st = H.state([wiz, foe])
        chosen = {"kind": "defensive_buff", "action": H.action_template("f_blur"),
                    "target": wiz, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        am = modifiers.query_attack_modifiers(foe, wiz, st)   # foe attacking the blurred caster
        self.assertTrue(am.has_disadvantage)
        # The caster attacking out is unaffected
        am_out = modifiers.query_attack_modifiers(wiz, foe, st)
        self.assertFalse(am_out.has_disadvantage)


if __name__ == "__main__":
    unittest.main()
