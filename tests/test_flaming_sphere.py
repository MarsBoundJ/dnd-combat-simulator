"""Flaming Sphere tests — SRD spell batch 2 (point-anchored DEX-save fire aura)."""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import _persistent_aura
from tests import _srd_helpers as H


class FlamingSphereTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_flaming_sphere")
        self.assertEqual(a["type"], "persistent_aura")
        self.assertTrue(a["concentration"])
        self.assertEqual(a["upcast_scaling"]["damage_type"], "fire")

    def test_registers_point_anchored_dex_aura(self):
        druid = H.caster(cid="druid", ability="wisdom", slots={2: 1})
        st = H.state([druid])
        action = H.action_template("f_flaming_sphere")
        st.current_attack = {"actor": druid, "target": druid,
                              "action": action, "area_origin": (4, 4)}
        _persistent_aura(action["pipeline"][0]["params"], st, EventBus())
        aura = st.persistent_auras[0]
        self.assertEqual(aura["ability"], "dexterity")
        self.assertEqual(aura["anchor"], "point")
        self.assertEqual(aura["origin"], (4, 4))
        self.assertEqual(aura["dc"], 8 + 3 + 4)        # pb3 + WIS+4

    def test_aura_damages_enemy_in_radius(self):
        druid = H.caster(cid="druid", ability="wisdom", position=(0, 0))
        foe = H.enemy(eid="foe", position=(1, 0), dex=-5, hp=40)
        st = H.state([druid, foe])
        st.persistent_auras.append({
            "caster_id": "druid", "action_id": "a_flaming_sphere",
            "named_effect": "flaming_sphere", "shape": "sphere",
            "radius_ft": 5, "size_ft": 0, "anchor": "point", "origin": (1, 0),
            "trigger_event": "target_turn_start_in_area", "ability": "dexterity",
            "dc": 15,
            "on_fail": [{"primitive": "damage", "params": {"dice": "2d6", "type": "fire"}}],
            "on_success": [{"primitive": "damage",
                             "params": {"dice": "2d6", "type": "fire", "multiplier": 0.5}}],
            "affected": "all_creatures", "applied_at_round": 1,
        })
        runner = EncounterRunner.new(st.encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        runner._resolve_persistent_aura_triggers(foe, st)
        self.assertLess(foe.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
