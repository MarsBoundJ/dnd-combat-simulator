"""Incendiary Cloud tests — SRD spell batch 3 (point-anchored DEX-save fire zone)."""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import _persistent_aura
from tests import _srd_helpers as H


class IncendiaryCloudTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_incendiary_cloud")
        self.assertEqual(a["type"], "persistent_aura")
        self.assertTrue(a["concentration"])

    def test_registers_dex_aura(self):
        wiz = H.caster(cid="wiz", ability="intelligence", pb=4, slots={8: 1})
        st = H.state([wiz])
        action = H.action_template("f_incendiary_cloud")
        st.current_attack = {"actor": wiz, "target": wiz, "action": action,
                              "area_origin": (5, 5)}
        _persistent_aura(action["pipeline"][0]["params"], st, EventBus())
        aura = st.persistent_auras[0]
        self.assertEqual(aura["ability"], "dexterity")
        self.assertEqual(aura["radius_ft"], 20)

    def test_aura_damages_enemy(self):
        wiz = H.caster(cid="wiz", ability="intelligence", position=(0, 0))
        foe = H.enemy(eid="foe", position=(1, 0), dex=-5, hp=80)
        st = H.state([wiz, foe])
        st.persistent_auras.append({
            "caster_id": "wiz", "action_id": "a_incendiary_cloud",
            "named_effect": "incendiary_cloud", "shape": "sphere",
            "radius_ft": 20, "size_ft": 0, "anchor": "point", "origin": (1, 0),
            "trigger_event": "target_turn_start_in_area", "ability": "dexterity",
            "dc": 17,
            "on_fail": [{"primitive": "damage", "params": {"dice": "10d8", "type": "fire"}}],
            "on_success": [{"primitive": "damage",
                             "params": {"dice": "10d8", "type": "fire", "multiplier": 0.5}}],
            "affected": "all_creatures", "applied_at_round": 1,
        })
        runner = EncounterRunner.new(st.encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        runner._resolve_persistent_aura_triggers(foe, st)
        self.assertLess(foe.hp_current, 80)


if __name__ == "__main__":
    unittest.main()
