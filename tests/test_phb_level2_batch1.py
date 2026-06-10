"""PHB-2024-only level-2 batch — Arcane Vigor, Cordon of Arrows,
Crown of Madness, Summon Beast (+ the Beast Sense non-combat stub and
Cloud of Daggers' 2024 upcast block).

Engine piece exercised: charge-limited persistent_auras (`charges` /
remaining_triggers — Cordon of Arrows' four arrows, each destroyed
after one shot regardless of the save outcome).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.pc_schema import _dispatch_pc_builder
from engine.primitives import PrimitiveRegistry

from tests._srd_helpers import (
    action_template, ally, caster, enemy, registry, state,
)


def _abil(**kw):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in kw.items():
        ab[k] = {"score": v, "save": 0}
    return ab


class TestRegistryLoads(unittest.TestCase):
    def test_features_present(self):
        reg = registry()
        for fid in ("f_arcane_vigor", "f_beast_sense",
                     "f_cordon_of_arrows", "f_crown_of_madness",
                     "f_summon_beast"):
            self.assertIsNotNone(reg.get("feature", fid), fid)
        self.assertIsNotNone(reg.get("monster", "m_bestial_spirit_land"))

    def test_beast_sense_is_inert_stub(self):
        f = registry().get("feature", "f_beast_sense")
        self.assertNotIn("action_template", f)
        self.assertNotIn("pc_builder", f)

    def test_cloud_of_daggers_2024_upcast(self):
        t = action_template("f_cloud_of_daggers")
        self.assertEqual(t["upcast_scaling"]["extra_dice_per_level"],
                          "2d4")


class TestArcaneVigor(unittest.TestCase):
    def test_heal_action_shape(self):
        f = registry().get("feature", "f_arcane_vigor")
        a = _dispatch_pc_builder(f, 3, _abil(cha=16), 2, "c_sorcerer")
        self.assertEqual(a["id"], "a_arcane_vigor")
        self.assertEqual(a["type"], "heal")
        self.assertEqual(a["slot"], "bonus_action")
        self.assertEqual(a["spell_slot_level"], 2)
        self.assertEqual(a["range_ft"], 0)   # self-only
        heal = a["pipeline"][0]["params"]
        self.assertEqual(heal["dice"], "2d6")
        self.assertEqual(heal["modifier"], 3)   # CHA +3


class TestCordonOfArrows(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(13))

    def _cast(self, *, slot_level=None):
        t = action_template("f_cordon_of_arrows")
        rgr = caster(cid="rgr", ability="wisdom", position=(0, 0),
                      slots={2: 1, 4: 1})
        foe = enemy(eid="foe", position=(3, 0), hp=200, dex=-20)
        buddy = ally(position=(1, 0), hp=30, hp_max=30)
        st = state([rgr, foe, buddy])
        chosen = {"kind": "aoe_attack", "action": t, "target": foe,
                   "origin_point": (0, 0), "actor": rgr}
        if slot_level:
            chosen["chosen_slot_level"] = slot_level
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        runner = EncounterRunner.new(st.encounter, seed=2)
        return st, runner, rgr, foe, buddy

    def test_aura_planted_with_four_charges(self):
        st, runner, rgr, foe, buddy = self._cast()
        self.assertEqual(len(st.persistent_auras), 1)
        a = st.persistent_auras[0]
        self.assertEqual(a["anchor"], "point")
        self.assertEqual(a["origin"], (0, 0))
        self.assertEqual(a["remaining_triggers"], 4)

    def test_arrow_fires_and_consumes_charge(self):
        st, runner, rgr, foe, buddy = self._cast()
        hp0 = foe.hp_current
        runner._resolve_persistent_aura_triggers(foe, st)
        self.assertLess(foe.hp_current, hp0)    # DEX -20: always fails
        self.assertEqual(st.persistent_auras[0]["remaining_triggers"], 3)

    def test_allies_exempt(self):
        st, runner, rgr, foe, buddy = self._cast()
        runner._resolve_persistent_aura_triggers(buddy, st)
        self.assertEqual(buddy.hp_current, 30)
        self.assertEqual(st.persistent_auras[0]["remaining_triggers"], 4)

    def test_depletes_after_four_shots(self):
        st, runner, rgr, foe, buddy = self._cast()
        for _ in range(4):
            runner._resolve_persistent_aura_triggers(foe, st)
        self.assertEqual(st.persistent_auras, [])
        self.assertTrue(any(e.get("event") == "persistent_aura_depleted"
                             for e in st.event_log))

    def test_upcast_adds_two_arrows_per_level(self):
        # Charge scaling is primitive-level: the slot-picker treats
        # Cordon as non-upcastable (no upcast_scaling damage block),
        # so stamp chosen_slot_level directly.
        t = action_template("f_cordon_of_arrows")
        rgr = caster(cid="rgr", ability="wisdom", position=(0, 0))
        foe = enemy(eid="foe", position=(3, 0))
        st = state([rgr, foe])
        st.current_attack = {"actor": rgr, "target": foe, "action": t,
                              "area_origin": (0, 0),
                              "chosen_slot_level": 4}
        PrimitiveRegistry.with_defaults().invoke(
            "persistent_aura", t["pipeline"][0]["params"], st, EventBus())
        self.assertEqual(st.persistent_auras[0]["remaining_triggers"], 8)


class TestCrownOfMadness(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(17))

    def test_template_shape(self):
        t = action_template("f_crown_of_madness")
        self.assertEqual(t["type"], "hard_control")
        self.assertTrue(t["concentration"])
        self.assertEqual(t["target_creature_types"], ["humanoid"])

    def test_failed_save_denies_and_registers_resave(self):
        t = action_template("f_crown_of_madness")
        sor = caster(cid="sor", ability="charisma", position=(0, 0),
                      slots={2: 1})
        foe = enemy(eid="foe", position=(4, 0), hp=60, wis=-20)
        foe.template["creature_type"] = "humanoid"
        st = state([sor, foe])
        chosen = {"kind": "hard_control", "action": t, "target": foe,
                   "actor": sor}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        self.assertIn("co_incapacitated",
                       [c["condition_id"] for c in foe.applied_conditions])
        saves = [s for s in st.recurring_saves
                 if s["target_id"] == foe.id]
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["trigger_event"], "target_turn_end")


class TestSummonBeast(unittest.TestCase):
    def test_land_spirit_stat_block(self):
        spirit = registry().get("monster", "m_bestial_spirit_land")
        self.assertEqual(spirit["combat"]["armor_class"], 13)   # 11 + 2
        self.assertEqual(spirit["combat"]["hit_points"]["average"], 30)
        rend = next(a for a in spirit["actions"] if a["id"] == "a_rend")
        dmg = rend["pipeline"][1]["params"]
        self.assertEqual(dmg["dice"], "1d8")
        self.assertEqual(dmg["modifier"], 6)    # 4 (STR) + spell level 2

    def test_summon_and_dismiss_on_concentration_end(self):
        from engine.core.concentration import (
            apply_concentration, end_concentration,
        )
        t = action_template("f_summon_beast")
        dru = caster(cid="dru", ability="wisdom", position=(0, 0),
                      slots={2: 1})
        foe = enemy(position=(4, 0), hp=60)
        st = state([dru, foe])
        st.current_attack = {"actor": dru, "target": dru, "action": t}
        apply_concentration(dru, t, st)
        PrimitiveRegistry.with_defaults().invoke(
            "summon", t["pipeline"][0]["params"], st, None)
        spirits = [a for a in st.encounter.actors
                   if a.template.get("id") == "m_bestial_spirit_land"]
        self.assertEqual(len(spirits), 1)
        self.assertEqual(spirits[0].side, dru.side)
        end_concentration(dru, st, reason="test")
        self.assertFalse(any(a.template.get("id") == "m_bestial_spirit_land"
                              for a in st.encounter.actors))


if __name__ == "__main__":
    unittest.main()
