"""Blade Barrier tests — SRD spell batch 3 (save-zone, DEX save 6d10 force)."""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import _persistent_aura
from tests import _srd_helpers as H


class BladeBarrierTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_blade_barrier")
        self.assertEqual(a["type"], "persistent_aura")
        self.assertTrue(a["concentration"])
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["params"]["type"], "force")

    def test_aura_damages_enemy(self):
        cle = H.caster(cid="cle", ability="wisdom", position=(0, 0))
        foe = H.enemy(eid="foe", position=(2, 0), dex=-5, hp=70)
        st = H.state([cle, foe])
        st.persistent_auras.append({
            "caster_id": "cle", "action_id": "a_blade_barrier",
            "named_effect": "blade_barrier", "shape": "cube", "size_ft": 10,
            "radius_ft": 0, "anchor": "point", "origin": (2, 0),
            "trigger_event": "target_turn_start_in_area", "ability": "dexterity",
            "dc": 16,
            "on_fail": [{"primitive": "damage", "params": {"dice": "6d10", "type": "force"}}],
            "on_success": [{"primitive": "damage",
                             "params": {"dice": "6d10", "type": "force", "multiplier": 0.5}}],
            "affected": "all_creatures", "applied_at_round": 1,
        })
        runner = EncounterRunner.new(st.encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        runner._resolve_persistent_aura_triggers(foe, st)
        self.assertLess(foe.hp_current, 70)


if __name__ == "__main__":
    unittest.main()
