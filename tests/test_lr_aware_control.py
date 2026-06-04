"""LR-aware control scoring — a save-or-lose control vs a Legendary
Resistance target is discounted 1/(lr+1), because LR (engine v1 greedy
policy) negates the lockdown until its charges drain. Stops the AI wasting
premium control at full value into LR (the boss-sim Bard finding).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_hard_control, lr_control_factor
from engine.core.legendary_resistance import RESOURCE_KEY
from tests import _srd_helpers as H


class LrControlFactorTest(unittest.TestCase):
    def test_no_lr_is_full_value(self):
        foe = H.enemy(hp=60, attack=True)
        self.assertEqual(lr_control_factor(foe), 1.0)

    def test_factor_scales_inverse_with_charges(self):
        foe = H.enemy(hp=60, attack=True)
        foe.resources[RESOURCE_KEY] = 1
        self.assertAlmostEqual(lr_control_factor(foe), 0.5)
        foe.resources[RESOURCE_KEY] = 3
        self.assertAlmostEqual(lr_control_factor(foe), 0.25)


class HardControlDiscountTest(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_control_vs_lr_target_is_discounted(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={5: 1})
        hold = H.action_template("f_hold_monster")

        no_lr = H.enemy(cid="no_lr", wis=-10, hp=60, attack=True)
        st0 = H.state([wiz, no_lr])
        base = defensive_ehp_hard_control(wiz, no_lr, hold, st0)
        self.assertGreater(base, 0.0)

        lr3 = H.enemy(cid="lr3", wis=-10, hp=60, attack=True)
        lr3.resources[RESOURCE_KEY] = 3
        st3 = H.state([wiz, lr3])
        discounted = defensive_ehp_hard_control(wiz, lr3, hold, st3)

        # Same stats, only LR differs -> exactly 1/4 the value (lr=3).
        self.assertAlmostEqual(discounted, base / 4.0, places=4)

    def test_value_rises_as_charges_drain(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={5: 1})
        hold = H.action_template("f_hold_monster")
        foe = H.enemy(cid="foe", wis=-10, hp=60, attack=True)
        st = H.state([wiz, foe])

        foe.resources[RESOURCE_KEY] = 3
        v3 = defensive_ehp_hard_control(wiz, foe, hold, st)
        foe.resources[RESOURCE_KEY] = 1
        v1 = defensive_ehp_hard_control(wiz, foe, hold, st)
        foe.resources[RESOURCE_KEY] = 0
        v0 = defensive_ehp_hard_control(wiz, foe, hold, st)

        self.assertLess(v3, v1)
        self.assertLess(v1, v0)   # full value once LRs are drained


if __name__ == "__main__":
    unittest.main()
