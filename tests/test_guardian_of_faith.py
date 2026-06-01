"""Guardian of Faith tests — SRD spell batch 4 (point-anchored DEX-save 20 radiant zone)."""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import _persistent_aura
from tests import _srd_helpers as H


class GuardianOfFaithTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_guardian_of_faith")
        self.assertEqual(a["type"], "persistent_aura")
        self.assertFalse(a.get("concentration"))         # 8 hours, not Concentration
        on_fail = a["pipeline"][0]["params"]["on_fail"][0]["params"]
        self.assertEqual(on_fail["modifier"], 20)        # flat 20 radiant (no dice)
        self.assertEqual(on_fail["type"], "radiant")

    def test_registers_enemies_only_zone(self):
        cle = H.caster(cid="cle", ability="wisdom", pb=3, slots={4: 1})
        st = H.state([cle])
        action = H.action_template("f_guardian_of_faith")
        st.current_attack = {"actor": cle, "target": cle, "action": action,
                              "area_origin": (4, 4)}
        _persistent_aura(action["pipeline"][0]["params"], st, EventBus())
        aura = st.persistent_auras[0]
        self.assertEqual(aura["affected"], "enemies")
        self.assertEqual(aura["radius_ft"], 10)

    def test_flat_20_radiant_on_failed_save(self):
        cle = H.caster(cid="cle", ability="wisdom", position=(0, 0))
        foe = H.enemy(eid="foe", position=(1, 0), dex=-20, hp=60)   # guaranteed fail
        st = H.state([cle, foe])
        st.persistent_auras.append({
            "caster_id": "cle", "action_id": "a_guardian_of_faith",
            "named_effect": "guardian_of_faith", "shape": "sphere",
            "radius_ft": 10, "size_ft": 0, "anchor": "point", "origin": (1, 0),
            "trigger_event": "target_turn_start_in_area", "ability": "dexterity",
            "dc": 16,
            "on_fail": [{"primitive": "damage", "params": {"modifier": 20, "type": "radiant"}}],
            "on_success": [{"primitive": "damage",
                             "params": {"modifier": 20, "type": "radiant", "multiplier": 0.5}}],
            "affected": "enemies", "applied_at_round": 1,
        })
        runner = EncounterRunner.new(st.encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        runner._resolve_persistent_aura_triggers(foe, st)
        self.assertEqual(foe.hp_current, 40)             # exactly 20 flat radiant


if __name__ == "__main__":
    unittest.main()
