"""Grease tests — SRD spell batch 3 (point-anchored DEX-save → Prone cube zone)."""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import _persistent_aura
from tests import _srd_helpers as H


class GreaseTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_grease")
        self.assertEqual(a["area"]["shape"], "cube")
        self.assertFalse(a.get("concentration"))       # 1 minute, not Concentration

    def test_registers_cube_dex_zone(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={1: 1})
        st = H.state([wiz])
        action = H.action_template("f_grease")
        st.current_attack = {"actor": wiz, "target": wiz, "action": action,
                              "area_origin": (3, 3)}
        _persistent_aura(action["pipeline"][0]["params"], st, EventBus())
        aura = st.persistent_auras[0]
        self.assertEqual(aura["shape"], "cube")
        self.assertEqual(aura["ability"], "dexterity")

    def test_failed_save_knocks_prone(self):
        wiz = H.caster(cid="wiz", ability="intelligence", position=(0, 0))
        foe = H.enemy(eid="foe", position=(2, 0), dex=-20, hp=30)
        st = H.state([wiz, foe])
        st.persistent_auras.append({
            "caster_id": "wiz", "action_id": "a_grease",
            "named_effect": "grease", "shape": "cube", "size_ft": 10,
            "radius_ft": 0, "anchor": "point", "origin": (2, 0),
            "trigger_event": "target_turn_start_in_area", "ability": "dexterity",
            "dc": 16,
            "on_fail": [{"primitive": "apply_condition",
                          "params": {"condition_id": "co_prone",
                                       "duration": "until_actor_next_turn_start"}}],
            "on_success": [], "affected": "all_creatures", "applied_at_round": 1,
        })
        runner = EncounterRunner.new(st.encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        runner._resolve_persistent_aura_triggers(foe, st)
        self.assertIn("co_prone", H.condition_ids(foe))


if __name__ == "__main__":
    unittest.main()
