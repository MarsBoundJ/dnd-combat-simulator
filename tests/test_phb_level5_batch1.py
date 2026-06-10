"""PHB-2024-only level-5 batch (part 1) — Banishing Smite, Circle of
Power, Conjure Volley, Destructive Wave, Jallarzi's Storm of Radiance,
Steel Wind Strike. (Summon Celestial + Synaptic Static were built in
earlier passes and verified against the pasted 2024 stats.)

Engine pieces exercised:
  - banishing_smite custom rider (engine.core.banishing_smite): 5d10
    force always + HP<=50-conditional CHA save → co_incapacitated with
    turn-end escape re-save;
  - circle_of_power_aura: LIVE save advantage fan-out (consumed by
    query_save_modifiers) + half-to-none marker;
  - emanation enemies_in_area with dual damage types + prone
    (Destructive Wave);
  - point-anchored persistent_aura at 5th level (Jallarzi's).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.banishing_smite import (
    register_armed as arm_banishing,
    find_armed_entry,
)
from engine.core.modifiers import query_save_modifiers
from engine.primitives import PrimitiveRegistry, _damage

from tests._srd_helpers import (
    action_template, ally, caster, enemy, registry, state,
)


def _melee_hit(attacker, target, st, *, dice="1d8"):
    weapon = {"id": "a_sword", "type": "weapon_attack",
               "pipeline": [{"primitive": "attack_roll",
                               "params": {"kind": "melee", "bonus": 5}}]}
    st.current_attack = {"actor": attacker, "target": target,
                          "action": weapon, "state": "hit",
                          "had_advantage": False, "had_disadvantage": False}
    hp_before = target.hp_current
    _damage({"dice": dice, "modifier": 0, "type": "slashing"}, st,
             EventBus())
    return hp_before - target.hp_current


class TestRegistryLoads(unittest.TestCase):
    def test_features_present(self):
        reg = registry()
        for fid in ("f_banishing_smite", "f_circle_of_power",
                     "f_conjure_volley", "f_destructive_wave",
                     "f_jallarzis_storm_of_radiance",
                     "f_steel_wind_strike"):
            self.assertIsNotNone(reg.get("feature", fid), fid)


class TestBanishingSmite(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(31))

    def _setup(self, *, target_hp):
        pal = caster(cid="pal", ability="charisma", position=(0, 0))
        foe = enemy(eid="foe", position=(1, 0), hp=target_hp, cha=-20)
        st = state([pal, foe])
        arm_banishing(pal, slot_level=5, spell_save_dc=15,
                       action_id="a_banishing_smite", state=st)
        return st, pal, foe

    def test_high_hp_target_no_banish(self):
        st, pal, foe = self._setup(target_hp=200)
        damage = _melee_hit(pal, foe, st)
        self.assertGreaterEqual(damage, 1 + 5)    # weapon 1d8 + 5d10 min
        ev = next(e for e in st.event_log
                  if e["event"] == "banishing_smite_triggered")
        self.assertFalse(ev["banish_attempt"])
        cond_ids = [c["condition_id"] for c in foe.applied_conditions]
        self.assertNotIn("co_incapacitated", cond_ids)
        self.assertIsNone(find_armed_entry(pal))  # marker still consumed

    def test_low_hp_target_banished(self):
        st, pal, foe = self._setup(target_hp=55)
        _melee_hit(pal, foe, st)
        ev = next(e for e in st.event_log
                  if e["event"] == "banishing_smite_triggered")
        self.assertTrue(ev["banish_attempt"])
        # CHA -20 always fails → banished
        cond_ids = [c["condition_id"] for c in foe.applied_conditions]
        self.assertIn("co_incapacitated", cond_ids)

    def test_ranged_does_not_trigger(self):
        st, pal, foe = self._setup(target_hp=55)
        weapon = {"id": "a_bow", "type": "weapon_attack",
                   "pipeline": [{"primitive": "attack_roll",
                                   "params": {"kind": "ranged", "bonus": 5}}]}
        st.current_attack = {"actor": pal, "target": foe, "action": weapon,
                              "state": "hit",
                              "had_advantage": False,
                              "had_disadvantage": False}
        _damage({"dice": "1d8", "modifier": 0, "type": "piercing"}, st,
                 EventBus())
        self.assertIsNotNone(find_armed_entry(pal))   # still armed


class TestCircleOfPower(unittest.TestCase):
    def _cast(self):
        t = action_template("f_circle_of_power")
        pal = caster(cid="pal", ability="charisma", position=(0, 0),
                      slots={5: 1})
        near = ally(aid="near", position=(2, 0), hp=30, hp_max=30)
        far = ally(aid="far", position=(20, 0), hp=30, hp_max=30)  # 100 ft
        st = state([pal, near, far, enemy(position=(6, 0))])
        chosen = {"kind": "defensive_buff", "action": t, "target": pal,
                   "actor": pal}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        return st, pal, near, far

    def test_save_advantage_is_live(self):
        st, pal, near, far = self._cast()
        # query_save_modifiers actually consumes the entry
        self.assertTrue(
            query_save_modifiers(near, "wisdom", st).has_advantage)
        self.assertTrue(
            query_save_modifiers(pal, "dexterity", st).has_advantage)
        self.assertFalse(
            query_save_modifiers(far, "wisdom", st).has_advantage)

    def test_half_to_none_marker_present(self):
        _, pal, near, far = self._cast()
        def markers(a):
            return [m for m in a.active_modifiers
                    if m.get("primitive") == "magic_save_half_to_none"]
        self.assertEqual(len(markers(pal)), 1)
        self.assertEqual(len(markers(near)), 1)
        self.assertEqual(markers(far), [])

    def test_concentration_drop_scrubs_all(self):
        st, pal, near, far = self._cast()
        end_concentration(pal, st, reason="test")
        self.assertFalse(
            query_save_modifiers(near, "wisdom", st).has_advantage)
        self.assertEqual(
            [m for m in pal.active_modifiers
             if m.get("primitive") == "magic_save_half_to_none"], [])


class TestConjureVolley(unittest.TestCase):
    def test_area_spares_allies(self):
        from engine.primitives import _resolve_save_targets
        t = action_template("f_conjure_volley")
        self.assertEqual(t["area"]["shape"], "sphere")
        self.assertEqual(t["area"]["radius_ft"], 40)
        rgr = caster(cid="rgr", ability="wisdom", position=(0, 0))
        foe = enemy(eid="foe", position=(10, 0), hp=60, dex=-20)
        buddy = ally(position=(11, 0), hp=30, hp_max=30)   # inside radius
        st = state([rgr, foe, buddy])
        st.current_attack = {"actor": rgr, "target": foe, "action": t,
                              "area_origin": (10, 0)}
        ids = [a.id for a in _resolve_save_targets(
            t["pipeline"][0]["params"], st)]
        self.assertEqual(ids, ["foe"])


class TestDestructiveWave(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(17))

    def test_emanation_dual_damage_and_prone(self):
        t = action_template("f_destructive_wave")
        self.assertEqual(t["area"]["shape"], "emanation")
        self.assertEqual(t["area"]["size_ft"], 30)
        pal = caster(cid="pal", ability="charisma", position=(0, 0),
                      slots={5: 1})
        foe = enemy(eid="foe", position=(2, 0), hp=100, con=-20)
        buddy = ally(position=(1, 0), hp=30, hp_max=30)    # in — spared
        far = enemy(eid="far", position=(20, 0), hp=40)    # 100 ft — out
        st = state([pal, foe, buddy, far])
        chosen = {"kind": "aoe_attack", "action": t, "target": foe,
                   "origin_point": (0, 0), "actor": pal}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        # CON -20 always fails: 5d6 + 5d6 (min 10) + prone
        self.assertLessEqual(foe.hp_current, 100 - 10)
        cond_ids = [c["condition_id"] for c in foe.applied_conditions]
        self.assertIn("co_prone", cond_ids)
        # "You choose" — ally and caster spared, far enemy out of range
        self.assertEqual(buddy.hp_current, 30)
        self.assertEqual(pal.hp_current, pal.hp_max)
        self.assertEqual(far.hp_current, 40)


class TestJallarzisStorm(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(19))

    def test_zone_registers_and_scrubs(self):
        t = action_template("f_jallarzis_storm_of_radiance")
        wiz = caster(cid="wiz", ability="intelligence", position=(0, 0),
                      slots={5: 1})
        foe = enemy(eid="foe", position=(10, 0), hp=80, con=-20)
        st = state([wiz, foe])
        chosen = {"kind": "aoe_attack", "action": t, "target": foe,
                   "origin_point": (10, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        self.assertEqual(len(st.persistent_auras), 1)
        a = st.persistent_auras[0]
        self.assertEqual(a["anchor"], "point")
        self.assertEqual(a["caster_id"], "wiz")
        end_concentration(wiz, st, reason="test")
        self.assertEqual(st.persistent_auras, [])


class TestSteelWindStrike(unittest.TestCase):
    def test_shape(self):
        from engine.pc_schema import _dispatch_pc_builder
        ab = {k: {"score": 10, "save": 0}
              for k in ("str", "dex", "con", "int", "wis", "cha")}
        ab["int"] = {"score": 18, "save": 4}
        f = registry().get("feature", "f_steel_wind_strike")
        a = _dispatch_pc_builder(f, 9, ab, 4, "c_wizard")
        self.assertIsNotNone(a)
        self.assertNotIn("concentration", a)
        dmg_step = next(s for s in a["pipeline"]
                         if s["primitive"] == "damage")
        self.assertEqual(dmg_step["params"]["dice"], "6d10")
        self.assertEqual(dmg_step["params"]["type"], "force")
        atk_step = next(s for s in a["pipeline"]
                         if s["primitive"] == "attack_roll")
        self.assertEqual(atk_step["params"]["range_ft"], 30)


if __name__ == "__main__":
    unittest.main()
