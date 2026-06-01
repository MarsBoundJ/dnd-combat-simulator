"""Command tests — SRD spell batch 2 (WIS save or lose next turn / Halt)."""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class CommandTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        self.assertEqual(H.registry().get("feature", "f_command")["spell"]["level"], 1)

    def test_failed_save_incapacitates_one_turn(self):
        cle = H.caster(cid="cle", ability="wisdom", slots={1: 1})
        foe = H.enemy(wis=-10)
        st = H.state([cle, foe])
        chosen = {"kind": "hard_control", "action": H.action_template("f_command"),
                    "target": foe, "actor": cle}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_incapacitated", H.condition_ids(foe))
        # Instantaneous: no recurring save (one-turn effect)
        self.assertEqual(st.recurring_saves, [])
        dur = [c for c in foe.applied_conditions if c["condition_id"] == "co_incapacitated"][0]
        self.assertEqual(dur["duration"], "until_actor_next_turn_start")


if __name__ == "__main__":
    unittest.main()
