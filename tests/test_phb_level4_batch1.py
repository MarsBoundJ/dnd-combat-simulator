"""PHB-2024-only level-4 batch — Aura of Purity, Fount of Moonlight,
Grasping Vine, Staggering Smite, Summon Aberration, Summon Construct,
Summon Elemental.

Engine pieces exercised:
  - aura_of_purity_aura: defensive ally aura fan-out (damage_resistance
    + condition_save_advantage to caster + allies ≤30 ft);
  - fount_of_moonlight_buff: self-buff weapon_damage_bonus (melee) +
    damage_resistance:radiant;
  - active_modifiers damage_resistance gate in _damage (new engine
    feature — halves the matching damage type when present);
  - staggering_smite_arm + try_apply_staggering_smite_followup: melee
    SmiteRiderSpec, 4d6 psychic + WIS save → co_stunned, upcast scaling.
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.core.staggering_smite import (
    register_armed as arm_staggering,
    find_armed_entry,
    STAGGERING_SMITE_SPEC,
)
from engine.primitives import PrimitiveRegistry, _damage
from engine.core import pipeline

from tests._srd_helpers import (
    action_template, ally, caster, enemy, registry, state,
)


class TestRegistryLoads(unittest.TestCase):
    def test_features_present(self):
        reg = registry()
        for fid in ("f_aura_of_purity", "f_fount_of_moonlight",
                     "f_grasping_vine", "f_staggering_smite",
                     "f_summon_aberration", "f_summon_construct",
                     "f_summon_elemental"):
            self.assertIsNotNone(reg.get("feature", fid), fid)

    def test_monsters_present(self):
        reg = registry()
        for mid in ("m_aberrant_spirit_beholderkin",
                     "m_construct_spirit_clay",
                     "m_elemental_spirit_air"):
            self.assertIsNotNone(reg.get("monster", mid), mid)


class TestAuraOfPurity(unittest.TestCase):
    def _cast(self):
        t = action_template("f_aura_of_purity")
        pal = caster(cid="pal", ability="charisma", position=(0, 0),
                      slots={4: 1})
        near = ally(aid="near", position=(2, 0), hp=30, hp_max=30)
        far = ally(aid="far", position=(20, 0), hp=30, hp_max=30)  # 100 ft
        foe = enemy(position=(6, 0))
        st = state([pal, near, far, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": pal,
                   "actor": pal}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        return st, pal, near, far

    def _resistance_mods(self, actor, dmg_type="poison"):
        return [m for m in actor.active_modifiers
                if m.get("primitive") == "damage_resistance"
                and (m.get("params") or {}).get("type") == dmg_type]

    def _save_adv_mods(self, actor):
        return [m for m in actor.active_modifiers
                if m.get("primitive") == "condition_save_advantage"]

    def test_fans_out_to_allies_in_30ft(self):
        _, pal, near, far = self._cast()
        # Caster and near ally (10 ft) both get modifiers
        self.assertEqual(len(self._resistance_mods(pal)), 1)
        self.assertEqual(len(self._resistance_mods(near)), 1)
        self.assertEqual(len(self._save_adv_mods(pal)), 1)
        self.assertEqual(len(self._save_adv_mods(near)), 1)
        # Far ally (100 ft) gets nothing
        self.assertEqual(self._resistance_mods(far), [])
        self.assertEqual(self._save_adv_mods(far), [])

    def test_concentration_drop_scrubs_all_copies(self):
        st, pal, near, far = self._cast()
        end_concentration(pal, st, reason="test")
        for actor in (pal, near):
            self.assertEqual(self._resistance_mods(actor), [])
            self.assertEqual(self._save_adv_mods(actor), [])

    def test_damage_resistance_halves_poison(self):
        """New engine gate: active_modifiers damage_resistance halves damage."""
        primitives_module.set_rng(random.Random(7))
        st, pal, near, _far = self._cast()
        # Deal poison damage to near (has the resistance modifier)
        foe = next(a for a in st.encounter.actors if a.side != pal.side)
        st.current_attack = {"actor": foe, "target": near, "action": {},
                              "state": "hit",
                              "had_advantage": False, "had_disadvantage": False}
        hp_before = near.hp_current
        _damage({"dice": "4d6", "modifier": 0, "type": "poison"}, st,
                 EventBus())
        damage_dealt = hp_before - near.hp_current
        # Without resistance the 4d6 average is 14; halved ≈ 7
        # Just verify it's strictly less than the max non-resisted roll (24)
        # halved, and that damage is positive.
        self.assertGreater(damage_dealt, 0)
        self.assertLessEqual(damage_dealt, 12)   # max 4d6=24 halved to 12


class TestFountOfMoonlight(unittest.TestCase):
    def _cast(self):
        t = action_template("f_fount_of_moonlight")
        dru = caster(cid="dru", ability="wisdom", position=(0, 0),
                      slots={4: 1})
        foe = enemy(position=(3, 0))
        st = state([dru, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": dru,
                   "actor": dru}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        return st, dru, t

    def test_self_buff_shape(self):
        _, dru, _ = self._cast()
        wdb = [m for m in dru.active_modifiers
               if m.get("primitive") == "weapon_damage_bonus"]
        dr = [m for m in dru.active_modifiers
              if m.get("primitive") == "damage_resistance"]
        self.assertEqual(len(wdb), 1)
        self.assertEqual(wdb[0]["params"]["value"], 7)
        self.assertEqual(wdb[0]["params"]["when"], "melee_attack")
        self.assertEqual(len(dr), 1)
        self.assertEqual(dr[0]["params"]["type"], "radiant")

    def test_concentration_drop_scrubs_buff(self):
        st, dru, _ = self._cast()
        end_concentration(dru, st, reason="test")
        wdb = [m for m in dru.active_modifiers
               if m.get("primitive") == "weapon_damage_bonus"]
        dr = [m for m in dru.active_modifiers
              if m.get("primitive") == "damage_resistance"]
        self.assertEqual(wdb, [])
        self.assertEqual(dr, [])


class TestGraspingVine(unittest.TestCase):
    def test_shape(self):
        from engine.pc_schema import _dispatch_pc_builder
        ab = {k: {"score": 10, "save": 0}
              for k in ("str", "dex", "con", "int", "wis", "cha")}
        ab["wis"] = {"score": 18, "save": 4}
        f = registry().get("feature", "f_grasping_vine")
        a = _dispatch_pc_builder(f, 9, ab, 4, "c_druid")
        self.assertIsNotNone(a)
        self.assertTrue(a.get("concentration"))
        pipeline_prims = [s["primitive"] for s in a["pipeline"]]
        self.assertIn("attack_roll", pipeline_prims)
        self.assertIn("damage", pipeline_prims)
        dmg_step = next(s for s in a["pipeline"] if s["primitive"] == "damage")
        self.assertEqual(dmg_step["params"]["type"], "bludgeoning")
        self.assertIn("4d8", dmg_step["params"]["dice"])


class TestStaggeringSmite(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(42))

    def _setup(self, slot_level=4):
        pal = caster(cid="pal", ability="charisma", position=(0, 0))
        foe = enemy(eid="foe", position=(1, 0), hp=200, wis=-20)
        st = state([pal, foe])
        arm_staggering(pal, slot_level=slot_level, spell_save_dc=15,
                        action_id="a_staggering_smite", state=st)
        return st, pal, foe

    def _melee_hit(self, attacker, target, st):
        weapon = {"id": "a_sword", "type": "weapon_attack",
                   "pipeline": [{"primitive": "attack_roll",
                                   "params": {"kind": "melee", "bonus": 5}}]}
        st.current_attack = {"actor": attacker, "target": target,
                              "action": weapon, "state": "hit",
                              "had_advantage": False, "had_disadvantage": False}
        hp_before = target.hp_current
        _damage({"dice": "1d8", "modifier": 0, "type": "slashing"}, st,
                 EventBus())
        return hp_before - target.hp_current

    def test_armed_and_fires_on_melee_hit(self):
        st, pal, foe = self._setup()
        self.assertIsNotNone(find_armed_entry(pal))
        damage = self._melee_hit(pal, foe, st)
        # 1d8 weapon + 4d6 smite; minimum is 1+4=5
        self.assertGreaterEqual(damage, 5)
        # co_stunned applied (WIS -20 always fails)
        cond_ids = [c["condition_id"] for c in foe.applied_conditions]
        self.assertIn("co_stunned", cond_ids)
        # Marker consumed (one-shot)
        self.assertIsNone(find_armed_entry(pal))
        events = [e for e in st.event_log
                  if e["event"] == "staggering_smite_triggered"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["slot_level"], 4)

    def test_ranged_does_not_trigger(self):
        st, pal, foe = self._setup()
        weapon = {"id": "a_bow", "type": "weapon_attack",
                   "pipeline": [{"primitive": "attack_roll",
                                   "params": {"kind": "ranged", "bonus": 5}}]}
        st.current_attack = {"actor": pal, "target": foe, "action": weapon,
                              "state": "hit",
                              "had_advantage": False, "had_disadvantage": False}
        _damage({"dice": "1d8", "modifier": 0, "type": "piercing"}, st,
                 EventBus())
        self.assertIsNotNone(find_armed_entry(pal))   # still armed
        self.assertEqual(
            [e for e in st.event_log
             if e["event"] == "staggering_smite_triggered"], [])

    def test_upcast_scales(self):
        primitives_module.set_rng(random.Random(99))
        st, pal, foe = self._setup(slot_level=5)
        self._melee_hit(pal, foe, st)
        ev = next(e for e in st.event_log
                  if e["event"] == "staggering_smite_triggered")
        self.assertEqual(ev["slot_level"], 5)
        # 5d6 base; min damage from smite alone = 5
        self.assertGreaterEqual(ev["bonus_damage"], 5)


class TestSummons(unittest.TestCase):
    def _summon_and_dismiss(self, feature_id, monster_id):
        from engine.core.concentration import apply_concentration, end_concentration
        t = action_template(feature_id)
        cas = caster(cid="cas", ability="intelligence", position=(0, 0),
                      slots={4: 1})
        st = state([cas, enemy(position=(6, 0), hp=60)])
        st.current_attack = {"actor": cas, "target": cas, "action": t}
        apply_concentration(cas, t, st)
        PrimitiveRegistry.with_defaults().invoke(
            "summon", t["pipeline"][0]["params"], st, None)
        spirits = [a for a in st.encounter.actors
                   if a.template.get("id") == monster_id]
        self.assertEqual(len(spirits), 1, monster_id)
        self.assertEqual(spirits[0].side, cas.side)
        end_concentration(cas, st, reason="test")
        self.assertFalse(any(a.template.get("id") == monster_id
                              for a in st.encounter.actors))

    def test_summon_aberration(self):
        self._summon_and_dismiss("f_summon_aberration",
                                   "m_aberrant_spirit_beholderkin")

    def test_summon_construct(self):
        self._summon_and_dismiss("f_summon_construct",
                                   "m_construct_spirit_clay")

    def test_summon_elemental(self):
        self._summon_and_dismiss("f_summon_elemental",
                                   "m_elemental_spirit_air")


if __name__ == "__main__":
    unittest.main()
