"""PHB-2024-only level-1 batch — Thunderous Smite, Hail of Thorns,
Witch Bolt, Arms of Hadar; plus the 2024 corrections to Wrathful Smite
(non-concentration + end-of-turn re-save) and Armor of Agathys (Bonus
Action cast).

Engine pieces exercised:
  - SmiteRiderSpec extensions: bonus_damage_dice_base (Thunderous 2d6),
    on_fail_push_ft (push + Prone), repeat_save_to_end (Wrathful 2024);
  - the first RANGED smite rider with a custom save-for-half burst
    trigger (Hail of Thorns);
  - pc_builder spell_attack `concentration` + `extra_pipeline`
    (Witch Bolt's hit-or-miss channel).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.thunderous_smite import (
    THUNDEROUS_SMITE_SPEC, register_armed as arm_thunderous,
)
from engine.core.hail_of_thorns import (
    register_armed as arm_hail, try_apply_hail_of_thorns_followup,
)
from engine.core.wrathful_smite import WRATHFUL_SMITE_SPEC
from engine.core import smite_rider
from engine.pc_schema import _dispatch_pc_builder
from engine.primitives import PrimitiveRegistry, _damage

from tests._srd_helpers import (
    action_template, ally, caster, enemy, registry, state,
)


def _abil(**kw):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in kw.items():
        ab[k] = {"score": v, "save": 0}
    return ab


def _weapon_hit(attacker, target, st, *, kind, dice="1d8",
                 dmg_type="slashing"):
    """Run a weapon damage instance through _damage so the smite
    follow-up hooks fire (mirrors the wrathful-smite test approach:
    current_attack['state'] == 'hit' + params['kind'])."""
    hp_before = target.hp_current
    weapon = {
        "id": "a_weapon", "name": "Strike", "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": kind, "ability": "str", "bonus": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": 0,
                          "type": dmg_type}},
        ],
    }
    st.current_attack = {
        "actor": attacker, "target": target, "action": weapon,
        "state": "hit",
        "had_advantage": False, "had_disadvantage": False,
    }
    _damage({"dice": dice, "modifier": 0, "type": dmg_type}, st,
             EventBus())
    return hp_before - target.hp_current


def _melee_hit(attacker, target, st, *, dice="1d8"):
    return _weapon_hit(attacker, target, st, kind="melee", dice=dice)


def _ranged_hit(attacker, target, st, *, dice="1d8"):
    return _weapon_hit(attacker, target, st, kind="ranged", dice=dice,
                        dmg_type="piercing")


def _conditions(actor):
    return [c["condition_id"] for c in actor.applied_conditions]


class TestRegistryLoads(unittest.TestCase):
    def test_features_present(self):
        reg = registry()
        for fid in ("f_thunderous_smite", "f_hail_of_thorns",
                     "f_witch_bolt", "f_arms_of_hadar"):
            self.assertIsNotNone(reg.get("feature", fid), fid)

    def test_2024_corrections(self):
        # Armor of Agathys: Bonus Action in 2024 (was Action).
        aoa = action_template("f_armor_of_agathys")
        self.assertEqual(aoa["slot"], "bonus_action")
        # Wrathful Smite: NOT concentration in 2024.
        ws = action_template("f_wrathful_smite")
        self.assertNotIn("concentration", ws)
        self.assertTrue(WRATHFUL_SMITE_SPEC.repeat_save_to_end)


class TestThunderousSmite(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def _armed_pair(self, str_save=-20):
        pal = caster(cid="pal", ability="charisma", position=(0, 0))
        foe = enemy(position=(1, 0), hp=60, **{"str": str_save})
        st = state([pal, foe])
        arm_thunderous(pal, slot_level=1, spell_save_dc=15,
                         action_id="a_thunderous_smite", state=st)
        return pal, foe, st

    def test_bonus_damage_is_two_dice_base(self):
        pal, foe, st = self._armed_pair()
        total = _melee_hit(pal, foe, st)
        # weapon 1d8 (max 8) + smite 2d6 (min 2): total strictly
        # exceeds any 1d8-only roll's floor when the rider fired —
        # assert via the event log instead of dice luck.
        events = [e for e in st.event_log
                  if e["event"] == "thunderous_smite_triggered"]
        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0]["bonus_damage"], 2)   # 2d6 min
        self.assertGreater(total, 0)

    def test_failed_save_pushes_and_knocks_prone(self):
        pal, foe, st = self._armed_pair(str_save=-20)
        before_x = foe.position[0]
        _melee_hit(pal, foe, st)
        self.assertIn("co_prone", _conditions(foe))
        self.assertGreater(foe.position[0], before_x)   # shoved away

    def test_save_negates_push_and_prone(self):
        pal, foe, st = self._armed_pair(str_save=+20)
        before = tuple(foe.position)
        _melee_hit(pal, foe, st)
        self.assertNotIn("co_prone", _conditions(foe))
        self.assertEqual(tuple(foe.position), before)

    def test_one_shot_marker_clears(self):
        pal, foe, st = self._armed_pair()
        _melee_hit(pal, foe, st)
        from engine.core.thunderous_smite import find_armed_entry
        self.assertIsNone(find_armed_entry(pal))


class TestWrathfulSmite2024(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(11))

    def test_failed_save_registers_end_of_turn_resave(self):
        pal = caster(cid="pal", ability="charisma", position=(0, 0))
        foe = enemy(position=(1, 0), hp=60, wis=-20)
        st = state([pal, foe])
        from engine.core.wrathful_smite import register_armed
        register_armed(pal, slot_level=1, spell_save_dc=15,
                         action_id="a_wrathful_smite", state=st)
        _melee_hit(pal, foe, st)
        self.assertIn("co_frightened", _conditions(foe))
        saves = [s for s in st.recurring_saves
                 if s["target_id"] == foe.id
                 and s["condition_id"] == "co_frightened"]
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["trigger_event"], "target_turn_end")
        self.assertEqual(saves[0]["on_success"], "end_spell_on_target")


class TestHailOfThorns(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def _setup(self, *, with_ally=False, slot_level=1):
        rgr = caster(cid="rgr", ability="wisdom", position=(0, 0))
        foe = enemy(eid="foe", position=(6, 0), hp=50, dex=-20)
        near = enemy(eid="near", position=(7, 0), hp=50, dex=-20)
        far = enemy(eid="far", position=(12, 0), hp=50, dex=-20)
        actors = [rgr, foe, near, far]
        if with_ally:
            actors.append(ally(position=(6, 1), hp=30, hp_max=30))
        st = state(actors)
        arm_hail(rgr, slot_level=slot_level, spell_save_dc=15,
                   action_id="a_hail_of_thorns", state=st)
        return rgr, foe, near, far, st

    def test_burst_hits_target_and_adjacent_only(self):
        rgr, foe, near, far, st = self._setup()
        _ranged_hit(rgr, foe, st)
        self.assertLess(foe.hp_current, 50)
        self.assertLess(near.hp_current, 50)    # within 5 ft of target
        self.assertEqual(far.hp_current, 50)    # 30 ft away — untouched

    def test_friendly_fire_is_raw(self):
        rgr, foe, near, far, st = self._setup(with_ally=True)
        buddy = next(a for a in st.encounter.actors if a.id == "ally")
        _ranged_hit(rgr, foe, st)
        self.assertLess(buddy.hp_current, 30)   # adjacent ally pays

    def test_melee_hit_does_not_trigger(self):
        rgr, foe, near, far, st = self._setup()
        _melee_hit(rgr, foe, st)
        events = [e for e in st.event_log
                  if e["event"] == "hail_of_thorns_triggered"]
        self.assertEqual(events, [])
        from engine.core.hail_of_thorns import find_armed_entry
        self.assertIsNotNone(find_armed_entry(rgr))   # still armed

    def test_upcast_scales_dice(self):
        rgr, foe, near, far, st = self._setup(slot_level=3)
        _ranged_hit(rgr, foe, st)
        events = [e for e in st.event_log
                  if e["event"] == "hail_of_thorns_triggered"]
        self.assertEqual(events[0]["dice"], "3d10")


class TestWitchBolt(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def _action(self):
        f = registry().get("feature", "f_witch_bolt")
        return _dispatch_pc_builder(f, 1, _abil(cha=16), 2, "c_warlock")

    def test_action_shape(self):
        a = self._action()
        self.assertEqual(a["id"], "a_witch_bolt")
        self.assertTrue(a["concentration"])
        self.assertEqual(a["spell_slot_level"], 1)
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"],
                          "1d12")
        # attack_roll, damage-on-hit, then the unconditional channel
        prims = [s["primitive"] for s in a["pipeline"]]
        self.assertEqual(prims,
                          ["attack_roll", "damage", "recurring_damage"])
        self.assertNotIn("when", a["pipeline"][2])

    def test_channel_registers_even_on_miss(self):
        a = self._action()
        lock = caster(cid="lock", ability="charisma", position=(0, 0),
                       slots={1: 2})
        foe = enemy(position=(2, 0), hp=50, ac=35)   # unhittable
        st = state([lock, foe])
        chosen = {"kind": "weapon_attack", "action": a, "target": foe,
                   "actor": lock}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        ticks = [t for t in st.recurring_damage
                 if t["target_id"] == foe.id
                 and t["source_action_id"] == "a_witch_bolt"]
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0]["dice"], "1d12")
        self.assertEqual(ticks[0]["damage_type"], "lightning")

    def test_concentration_drop_scrubs_channel(self):
        a = self._action()
        lock = caster(cid="lock", ability="charisma", position=(0, 0),
                       slots={1: 2})
        foe = enemy(position=(2, 0), hp=50, ac=0)
        st = state([lock, foe])
        chosen = {"kind": "weapon_attack", "action": a, "target": foe,
                   "actor": lock}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        self.assertTrue(any(t["source_action_id"] == "a_witch_bolt"
                             for t in st.recurring_damage))
        from engine.core.concentration import end_concentration
        end_concentration(lock, st)
        self.assertFalse(any(t["source_action_id"] == "a_witch_bolt"
                              for t in st.recurring_damage))


class TestArmsOfHadar(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(9))

    def test_emanation_burst(self):
        t = action_template("f_arms_of_hadar")
        self.assertEqual(t["area"]["shape"], "emanation")
        self.assertEqual(t["area"]["size_ft"], 10)
        lock = caster(cid="lock", ability="charisma", position=(0, 0),
                       slots={1: 2})
        near = enemy(eid="near", position=(1, 0), hp=40,
                      **{"str": -20})
        far = enemy(eid="far", position=(5, 0), hp=40)   # 25 ft — out
        buddy = ally(position=(0, 1), hp=30, hp_max=30)  # in — RAW
        st = state([lock, near, far, buddy])
        chosen = {"kind": "aoe_attack", "action": t, "target": near,
                   "origin_point": (0, 0), "actor": lock}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        self.assertLess(near.hp_current, 40)
        self.assertEqual(far.hp_current, 40)
        self.assertLess(buddy.hp_current, 30)    # friendly fire is RAW
        self.assertEqual(lock.hp_current, lock.hp_max)   # caster spared


if __name__ == "__main__":
    unittest.main()
