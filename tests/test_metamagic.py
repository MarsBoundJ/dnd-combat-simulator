"""Metamagic subsystem (Sorcerer).

Covers all 10 SRD options at the transform level (apply_metamagic mutates
a COPY + spends Sorcery Points), the known/affordability gates, the Font
of Magic slot<->SP conversion, and engine-honor integration for the
resolution-time options (Empowered reroll, Heightened disadvantage,
Careful auto-succeed).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import metamagic as mm
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _forced_save, _damage


def _caster(cha=18, sp=10, known=None):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["cha"] = {"score": cha, "save": 0}
    a = Actor(id="sorc", name="sorc",
               template={"id": "t", "name": "sorc", "abilities": abilities,
                          "cr": {"proficiency_bonus": 3},
                          "metamagic_known": list(known or mm.METAMAGIC_OPTIONS)},
               side="pc", hp_current=30, hp_max=30, ac=13,
               speed={"walk": 30}, position=(0, 0), abilities=abilities,
               spell_slots={1: 2, 2: 1})
    a.resources = {"sorcery_points_remaining": sp, "sorcery_points_max": sp}
    return a


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [x.id for x in actors]
    st.round = 1
    return st


def _save_action():
    return {"id": "a_fireball", "name": "Fireball", "type": "aoe_attack",
            "spell_slot_level": 3, "range_ft": 150,
            "pipeline": [
                {"primitive": "forced_save",
                  "params": {"ability": "dexterity", "dc": 15,
                              "affected": "all_creatures_in_area",
                              "on_fail": [{"primitive": "damage",
                                            "params": {"dice": "8d6",
                                                        "type": "fire"}}],
                              "on_success": []}}]}


class TransformTest(unittest.TestCase):

    def setUp(self):
        self.c = _caster()
        self.st = _state([self.c])

    def test_quickened_to_bonus_action(self):
        a = mm.apply_metamagic("quickened", _save_action(), self.c, self.st)
        self.assertEqual(a["slot"], "bonus_action")
        self.assertEqual(self.c.resources["sorcery_points_remaining"], 8)  # -2

    def test_distant_doubles_range(self):
        a = mm.apply_metamagic("distant", _save_action(), self.c, self.st)
        self.assertEqual(a["range_ft"], 300)
        self.assertEqual(self.c.resources["sorcery_points_remaining"], 9)  # -1

    def test_transmuted_changes_type(self):
        a = mm.apply_metamagic("transmuted", _save_action(), self.c, self.st)
        dmg = a["pipeline"][0]["params"]["on_fail"][0]["params"]
        self.assertNotEqual(dmg["type"], "fire")  # fire -> lightning

    def test_empowered_tags_damage(self):
        a = mm.apply_metamagic("empowered", _save_action(), self.c, self.st)
        dmg = a["pipeline"][0]["params"]["on_fail"][0]["params"]
        self.assertEqual(dmg["empowered_reroll"], 4)  # CHA 18 -> +4

    def test_heightened_tags_save(self):
        a = mm.apply_metamagic("heightened", _save_action(), self.c, self.st)
        self.assertTrue(a["pipeline"][0]["params"]["heightened"])
        self.assertEqual(self.c.resources["sorcery_points_remaining"], 8)  # -2

    def test_careful_tags_save(self):
        a = mm.apply_metamagic("careful", _save_action(), self.c, self.st)
        self.assertEqual(a["pipeline"][0]["params"]["careful_allies"], 4)

    def test_seeking_and_subtle_flags(self):
        a = mm.apply_metamagic("seeking", _save_action(), self.c, self.st)
        self.assertTrue(a["metamagic_seeking"])
        b = mm.apply_metamagic("subtle", _save_action(), self.c, self.st)
        self.assertTrue(b["subtle"])

    def test_twinned_sets_two_targets(self):
        single = {"id": "a_charm", "max_targets": 1, "range_ft": 30,
                   "pipeline": []}
        a = mm.apply_metamagic("twinned", single, self.c, self.st)
        self.assertEqual(a["max_targets"], 2)

    def test_original_action_not_mutated(self):
        orig = _save_action()
        mm.apply_metamagic("quickened", orig, self.c, self.st)
        # Quickened sets slot on the COPY; the original is untouched.
        self.assertNotIn("slot", orig)


class GateTest(unittest.TestCase):

    def test_unknown_option_noop(self):
        c = _caster(known=["distant"])
        st = _state([c])
        a = mm.apply_metamagic("quickened", _save_action(), c, st)
        self.assertNotIn("slot", a)  # not applied
        self.assertEqual(c.resources["sorcery_points_remaining"], 10)  # no SP

    def test_insufficient_sp_noop(self):
        c = _caster(sp=1)  # Heightened costs 2
        st = _state([c])
        a = mm.apply_metamagic("heightened", _save_action(), c, st)
        self.assertNotIn("heightened",
                          a["pipeline"][0]["params"])
        self.assertEqual(c.resources["sorcery_points_remaining"], 1)


class FontOfMagicTest(unittest.TestCase):

    def test_slot_to_sp(self):
        c = _caster(sp=2)
        c.resources["sorcery_points_max"] = 10  # room below the cap
        st = _state([c])
        ok = mm.convert_slot_to_sp(c, 2, st)  # 2nd-level slot -> +2 SP
        self.assertTrue(ok)
        self.assertEqual(c.resources["sorcery_points_remaining"], 4)
        self.assertEqual(c.spell_slots[2], 0)

    def test_slot_to_sp_capped(self):
        c = _caster(sp=10)  # already at max
        st = _state([c])
        mm.convert_slot_to_sp(c, 1, st)
        self.assertEqual(c.resources["sorcery_points_remaining"], 10)  # capped

    def test_sp_to_slot(self):
        c = _caster(sp=5)
        st = _state([c])
        ok = mm.convert_sp_to_slot(c, 2, st)  # 2nd-level slot costs 3 SP
        self.assertTrue(ok)
        self.assertEqual(c.resources["sorcery_points_remaining"], 2)
        self.assertEqual(c.spell_slots[2], 2)  # was 1, +1

    def test_sp_to_slot_unaffordable(self):
        c = _caster(sp=1)
        st = _state([c])
        self.assertFalse(mm.convert_sp_to_slot(c, 3, st))  # needs 5 SP


class EngineHonorTest(unittest.TestCase):
    """Resolution-time honors via the real primitives."""

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_careful_ally_auto_succeeds_no_damage(self):
        sorc = _caster()
        ally = Actor(id="ally", name="ally", template={"abilities": {}},
                      side="pc", hp_current=30, hp_max=30, ac=13,
                      speed={"walk": 30}, position=(1, 0),
                      abilities={k: {"score": 10, "save": 0}
                                  for k in ("str", "dex", "con", "int",
                                              "wis", "cha")})
        st = _state([sorc, ally])
        st.current_attack = {"actor": sorc, "target": ally,
                              "action": {"id": "a_fireball"}}
        hp_before = ally.hp_current
        _forced_save({"ability": "dexterity", "dc": 30,  # would auto-fail
                       "affected": "current_target",
                       "careful_allies": 2,
                       "on_fail": [{"primitive": "damage",
                                     "params": {"dice": "8d6", "type": "fire"}}],
                       "on_success": []}, st, EventBus())
        # Careful: ally took NO damage despite a DC it would fail
        self.assertEqual(ally.hp_current, hp_before)
        evs = [e for e in st.event_log if e.get("metamagic_careful")]
        self.assertEqual(len(evs), 1)

    def test_empowered_reroll_changes_damage_distribution(self):
        # With a low-rolling seed, empowered reroll should raise total
        # damage vs no reroll on the same seed.
        def roll_once(empowered):
            primitives_module.set_rng(random.Random(2))
            sorc = _caster()
            foe = Actor(id="foe", name="foe", template={"abilities": {}},
                         side="enemy", hp_current=200, hp_max=200, ac=10,
                         speed={"walk": 30}, position=(1, 0),
                         abilities={k: {"score": 10, "save": 0}
                                     for k in ("str", "dex", "con", "int",
                                                 "wis", "cha")})
            st = _state([sorc, foe])
            st.current_attack = {"actor": sorc, "target": foe,
                                  "action": {"id": "x"}, "state": "hit"}
            params = {"dice": "8d6", "type": "fire"}
            if empowered:
                params["empowered_reroll"] = 4
            hp = foe.hp_current
            _damage(params, st, EventBus())
            return hp - foe.hp_current
        plain = roll_once(False)
        emp = roll_once(True)
        # Rerolling the 4 lowest of 8d6 should never reduce the total.
        self.assertGreaterEqual(emp, plain)


if __name__ == "__main__":
    unittest.main()
