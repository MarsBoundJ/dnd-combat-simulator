"""Entangle tests — SRD spell batch 2 (persistent 20-ft zone, STR save or Restrained)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry, _persistent_aura
from tests import _srd_helpers as H


class EntangleTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = H.action_template("f_entangle")
        self.assertEqual(a["type"], "persistent_aura")
        self.assertEqual(a["area"]["shape"], "cube")
        self.assertTrue(a["concentration"])

    def test_registers_point_anchored_str_aura(self):
        ranger = H.caster(cid="ranger", ability="wisdom", slots={1: 1})
        st = H.state([ranger])
        action = H.action_template("f_entangle")
        st.current_attack = {"actor": ranger, "target": ranger,
                              "action": action, "area_origin": (5, 5)}
        _persistent_aura(action["pipeline"][0]["params"], st, EventBus())
        self.assertEqual(len(st.persistent_auras), 1)
        aura = st.persistent_auras[0]
        self.assertEqual(aura["shape"], "cube")
        self.assertEqual(aura["ability"], "strength")
        self.assertEqual(aura["anchor"], "point")
        self.assertEqual(aura["origin"], (5, 5))
        # DC resolved from the caster's spell save DC (8 + pb3 + WIS mod4 = 15)
        self.assertEqual(aura["dc"], 8 + 3 + 4)


if __name__ == "__main__":
    unittest.main()
