"""PHB-2024-only level-3 batch — Aura of Vitality, Conjure Barrage,
Crusader's Mantle, Elemental Weapon, Lightning Arrow, Summon Fey,
Summon Undead (+ the Feign Death stub and the 2024 corrections to
Blinding Smite / Hunger of Hadar).

Engine pieces exercised:
  - recurring_heal: source-keyed caster-turn-start heal ticks (the
    ally-aura heal-over-time sub-shape) + concentration scrub;
  - crusaders_mantle_aura: weapon_damage_bonus fan-out to allies in
    radius (the offensive ally-aura sub-shape);
  - repeat_save_to_end on a no-initial-save smite (Blinding 2024);
  - the Lightning Arrow ranged rider (direct Nd8 + 10-ft burst).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.core.blinding_smite import BLINDING_SMITE_SPEC
from engine.core.lightning_arrow import (
    register_armed as arm_lightning,
)
from engine.primitives import PrimitiveRegistry, _damage

from tests._srd_helpers import (
    action_template, ally, caster, enemy, registry, state,
)


def _ranged_hit(attacker, target, st, *, dice="1d8"):
    hp_before = target.hp_current
    weapon = {
        "id": "a_bow", "name": "Shoot", "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "ranged", "ability": "dex", "bonus": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": 0,
                          "type": "piercing"}},
        ],
    }
    st.current_attack = {
        "actor": attacker, "target": target, "action": weapon,
        "state": "hit",
        "had_advantage": False, "had_disadvantage": False,
    }
    _damage({"dice": dice, "modifier": 0, "type": "piercing"}, st,
             EventBus())
    return hp_before - target.hp_current


class TestRegistryLoads(unittest.TestCase):
    def test_features_present(self):
        reg = registry()
        for fid in ("f_aura_of_vitality", "f_conjure_barrage",
                     "f_crusaders_mantle", "f_elemental_weapon",
                     "f_feign_death", "f_lightning_arrow",
                     "f_summon_fey", "f_summon_undead"):
            self.assertIsNotNone(reg.get("feature", fid), fid)
        for mid in ("m_fey_spirit", "m_undead_spirit_skeletal"):
            self.assertIsNotNone(reg.get("monster", mid), mid)

    def test_feign_death_is_inert_stub(self):
        f = registry().get("feature", "f_feign_death")
        self.assertNotIn("action_template", f)
        self.assertNotIn("pc_builder", f)

    def test_2024_corrections(self):
        # Blinding Smite: NOT concentration in 2024, re-save instead.
        bs = action_template("f_blinding_smite")
        self.assertNotIn("concentration", bs)
        self.assertTrue(BLINDING_SMITE_SPEC.repeat_save_to_end)
        # Hunger of Hadar: the end-of-turn acid save is DEX in 2024.
        hoh = action_template("f_hunger_of_hadar")
        self.assertEqual(hoh["pipeline"][0]["params"]["ability"],
                          "dexterity")


class TestAuraOfVitality(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(23))

    def _cast(self):
        t = action_template("f_aura_of_vitality")
        pal = caster(cid="pal", ability="charisma", position=(0, 0),
                      slots={3: 1}, hp=30)
        hurt = ally(aid="hurt", position=(1, 0), hp=5, hp_max=40)
        topped = ally(aid="topped", position=(0, 1), hp=40, hp_max=40)
        far = ally(aid="far", position=(20, 0), hp=1, hp_max=40)  # 100 ft
        st = state([pal, hurt, topped, far, enemy(position=(6, 0))])
        chosen = {"kind": "heal", "action": t, "target": hurt,
                   "actor": pal}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        return st, pal, hurt, topped, far

    def test_cast_heals_and_registers_tick(self):
        st, pal, hurt, topped, far = self._cast()
        self.assertGreater(hurt.hp_current, 5)     # 2d6 at cast
        ticks = [t for t in st.recurring_heals
                 if t["source_id"] == pal.id]
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0]["dice"], "2d6")

    def test_turn_start_heals_most_wounded_in_range(self):
        st, pal, hurt, topped, far = self._cast()
        hp_after_cast = hurt.hp_current
        runner = EncounterRunner.new(st.encounter, seed=3)
        runner._resolve_recurring_heals(pal, st)
        # `far` is the most wounded but 100 ft away; `hurt` gets it.
        self.assertGreater(hurt.hp_current, hp_after_cast)
        self.assertEqual(far.hp_current, 1)
        self.assertEqual(topped.hp_current, 40)

    def test_concentration_drop_scrubs_tick(self):
        st, pal, hurt, topped, far = self._cast()
        t = action_template("f_aura_of_vitality")
        apply_concentration(pal, t, st)
        end_concentration(pal, st, reason="test")
        self.assertEqual(
            [e for e in st.recurring_heals if e["source_id"] == pal.id],
            [])


class TestCrusadersMantle(unittest.TestCase):
    def test_fans_out_to_allies_in_30ft(self):
        t = action_template("f_crusaders_mantle")
        pal = caster(cid="pal", ability="charisma", position=(0, 0),
                      slots={3: 1})
        near = ally(aid="near", position=(2, 0), hp=30, hp_max=30)
        far = ally(aid="far", position=(20, 0), hp=30, hp_max=30)
        st = state([pal, near, far, enemy(position=(6, 0))])
        chosen = {"kind": "defensive_buff", "action": t, "target": pal,
                   "actor": pal}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())

        def bonus_mods(a):
            return [m for m in a.active_modifiers
                    if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(bonus_mods(pal)), 1)    # caster included
        self.assertEqual(len(bonus_mods(near)), 1)
        self.assertEqual(bonus_mods(near)[0]["params"]["value"], 2)
        self.assertEqual(bonus_mods(far), [])        # 100 ft — outside

    def test_concentration_drop_scrubs_all_copies(self):
        t = action_template("f_crusaders_mantle")
        pal = caster(cid="pal", ability="charisma", position=(0, 0),
                      slots={3: 1})
        near = ally(aid="near", position=(2, 0), hp=30, hp_max=30)
        st = state([pal, near, enemy(position=(6, 0))])
        chosen = {"kind": "defensive_buff", "action": t, "target": pal,
                   "actor": pal}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        end_concentration(pal, st, reason="test")
        for a in (pal, near):
            self.assertEqual(
                [m for m in a.active_modifiers
                 if m.get("primitive") == "weapon_damage_bonus"], [])


class TestElementalWeapon(unittest.TestCase):
    def test_self_buff_shape(self):
        t = action_template("f_elemental_weapon")
        self.assertTrue(t["concentration"])
        prims = [s["primitive"] for s in t["pipeline"]]
        self.assertEqual(prims, ["attack_modifier",
                                   "weapon_damage_bonus"])
        self.assertEqual(t["pipeline"][0]["params"]["value"], 1)
        self.assertEqual(t["pipeline"][1]["params"]["value"], 2)


class TestConjureBarrage(unittest.TestCase):
    def test_cone_spares_allies(self):
        from engine.primitives import _resolve_save_targets
        t = action_template("f_conjure_barrage")
        self.assertEqual(t["area"]["shape"], "cone")
        rgr = caster(cid="rgr", ability="wisdom", position=(0, 0))
        foe = enemy(eid="foe", position=(4, 0), hp=60, dex=-20)
        buddy = ally(position=(2, 0), hp=30, hp_max=30)   # in the cone
        st = state([rgr, foe, buddy])
        st.current_attack = {"actor": rgr, "target": foe, "action": t,
                              "area_origin": (0, 0),
                              "area_direction": (1, 0)}
        ids = [a.id for a in _resolve_save_targets(
            t["pipeline"][0]["params"], st)]
        self.assertEqual(ids, ["foe"])


class TestLightningArrow(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(29))

    def _setup(self, slot_level=3):
        rgr = caster(cid="rgr", ability="wisdom", position=(0, 0))
        foe = enemy(eid="foe", position=(8, 0), hp=200, dex=-20)
        near = enemy(eid="near", position=(9, 0), hp=50, dex=-20)
        far = enemy(eid="far", position=(14, 0), hp=50)   # 30 ft from foe
        st = state([rgr, foe, near, far])
        arm_lightning(rgr, slot_level=slot_level, spell_save_dc=15,
                        action_id="a_lightning_arrow", state=st)
        return st, rgr, foe, near, far

    def test_direct_damage_and_burst(self):
        st, rgr, foe, near, far = self._setup()
        dealt = _ranged_hit(rgr, foe, st)
        self.assertGreaterEqual(dealt, 1 + 4)     # weapon 1d8 + 4d8 min
        self.assertLess(near.hp_current, 50)      # 5 ft from target
        self.assertEqual(far.hp_current, 50)      # 30 ft — outside burst
        events = [e for e in st.event_log
                  if e["event"] == "lightning_arrow_triggered"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["burst_dice"], "2d8")
        self.assertNotIn("foe", events[0]["burst"])   # target excluded

    def test_upcast_scales_both_effects(self):
        st, rgr, foe, near, far = self._setup(slot_level=5)
        _ranged_hit(rgr, foe, st)
        ev = next(e for e in st.event_log
                  if e["event"] == "lightning_arrow_triggered")
        self.assertEqual(ev["burst_dice"], "4d8")
        self.assertGreaterEqual(ev["direct_damage"], 6)   # 6d8 min

    def test_melee_hit_does_not_trigger(self):
        st, rgr, foe, near, far = self._setup()
        weapon = {"id": "a_sword", "type": "weapon_attack",
                   "pipeline": [
                       {"primitive": "attack_roll",
                         "params": {"kind": "melee", "bonus": 5}}]}
        st.current_attack = {"actor": rgr, "target": foe,
                              "action": weapon, "state": "hit",
                              "had_advantage": False,
                              "had_disadvantage": False}
        _damage({"dice": "1d8", "modifier": 0, "type": "slashing"},
                 st, EventBus())
        from engine.core.lightning_arrow import find_armed_entry
        self.assertIsNotNone(find_armed_entry(rgr))   # still armed


class TestSummons(unittest.TestCase):
    def _summon_and_dismiss(self, feature_id, monster_id):
        t = action_template(feature_id)
        cas = caster(cid="cas", ability="intelligence", position=(0, 0),
                      slots={3: 1})
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

    def test_summon_fey(self):
        self._summon_and_dismiss("f_summon_fey", "m_fey_spirit")

    def test_summon_undead(self):
        self._summon_and_dismiss("f_summon_undead",
                                   "m_undead_spirit_skeletal")


if __name__ == "__main__":
    unittest.main()
