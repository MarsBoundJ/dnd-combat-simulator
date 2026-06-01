"""Sleet Storm tests — SRD spell batch 2 (point-anchored DEX-save → Prone zone)."""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import _persistent_aura
from tests import _srd_helpers as H


class SleetStormTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_sleet_storm")
        self.assertEqual(a["type"], "persistent_aura")
        self.assertEqual(a["area"]["radius_ft"], 20)
        self.assertTrue(a["concentration"])

    def test_registers_str_dex_zone(self):
        druid = H.caster(cid="druid", ability="wisdom", slots={3: 1})
        st = H.state([druid])
        action = H.action_template("f_sleet_storm")
        st.current_attack = {"actor": druid, "target": druid,
                              "action": action, "area_origin": (6, 6)}
        _persistent_aura(action["pipeline"][0]["params"], st, EventBus())
        aura = st.persistent_auras[0]
        self.assertEqual(aura["ability"], "dexterity")
        self.assertEqual(aura["radius_ft"], 20)

    def test_failed_save_knocks_prone(self):
        druid = H.caster(cid="druid", ability="wisdom", position=(0, 0))
        foe = H.enemy(eid="foe", position=(2, 0), dex=-20)   # near-certain fail
        st = H.state([druid, foe])
        st.persistent_auras.append({
            "caster_id": "druid", "action_id": "a_sleet_storm",
            "named_effect": "sleet_storm", "shape": "sphere",
            "radius_ft": 20, "size_ft": 0, "anchor": "point", "origin": (2, 0),
            "trigger_event": "target_turn_start_in_area", "ability": "dexterity",
            "dc": 18,
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
