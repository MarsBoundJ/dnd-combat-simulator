"""Insect Plague tests — SRD spell batch 3 (point-anchored CON-save piercing zone)."""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import _persistent_aura
from tests import _srd_helpers as H


class InsectPlagueTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_insect_plague")
        self.assertEqual(a["type"], "persistent_aura")
        self.assertTrue(a["concentration"])
        self.assertEqual(a["upcast_scaling"]["damage_type"], "piercing")

    def test_registers_con_aura(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=4, slots={5: 1})
        st = H.state([cle])
        action = H.action_template("f_insect_plague")
        st.current_attack = {"actor": cle, "target": cle, "action": action,
                              "area_origin": (6, 6)}
        _persistent_aura(action["pipeline"][0]["params"], st, EventBus())
        aura = st.persistent_auras[0]
        self.assertEqual(aura["ability"], "constitution")
        self.assertEqual(aura["radius_ft"], 20)
        self.assertEqual(aura["dc"], 8 + 4 + 4)        # pb4 + WIS+4

    def test_aura_damages_enemy(self):
        cle = H.caster(cid="cle", ability="wisdom", position=(0, 0))
        foe = H.enemy(eid="foe", position=(1, 0), con=-5, hp=60)
        st = H.state([cle, foe])
        st.persistent_auras.append({
            "caster_id": "cle", "action_id": "a_insect_plague",
            "named_effect": "insect_plague", "shape": "sphere",
            "radius_ft": 20, "size_ft": 0, "anchor": "point", "origin": (1, 0),
            "trigger_event": "target_turn_start_in_area", "ability": "constitution",
            "dc": 16,
            "on_fail": [{"primitive": "damage", "params": {"dice": "4d10", "type": "piercing"}}],
            "on_success": [{"primitive": "damage",
                             "params": {"dice": "4d10", "type": "piercing", "multiplier": 0.5}}],
            "affected": "all_creatures", "applied_at_round": 1,
        })
        runner = EncounterRunner.new(st.encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        runner._resolve_persistent_aura_triggers(foe, st)
        self.assertLess(foe.hp_current, 60)


if __name__ == "__main__":
    unittest.main()
