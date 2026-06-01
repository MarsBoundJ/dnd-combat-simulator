"""Form system Phase 1 — mechanical form core (assume/revert + policies +
damage routing + reversion).

Validated with synthetic actors + a synthetic beast form template (no
content dependency — Wild Shape/Polymorph spells ride this in later
phases).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import forms
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _damage


def _abil(s, d, c, i, w, ch):
    return {"str": {"score": s, "save": 0}, "dex": {"score": d, "save": 0},
            "con": {"score": c, "save": 0}, "int": {"score": i, "save": 0},
            "wis": {"score": w, "save": 0}, "cha": {"score": ch, "save": 0}}


def _druid(hp=22, ac=14):
    ab = _abil(10, 12, 14, 10, 16, 10)   # WIS 16 caster
    return Actor(id="druid", name="druid",
                  template={"id": "pc_druid", "name": "Druid",
                             "abilities": ab, "actions": [],
                             "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": 30}, position=(0, 0), abilities=ab,
                  size="medium", creature_type="humanoid")


def _bear_form():
    # Synthetic beast stat block (Brown-Bear-ish): high STR/CON, more HP.
    return {"id": "m_form_bear", "name": "Bear Form", "size": "large",
            "creature_type": "beast",
            "abilities": _abil(19, 10, 16, 2, 13, 7),
            "combat": {"armor_class": 11,
                        "hit_points": {"average": 34, "dice": "4d10+12"},
                        "speed": {"walk": 40, "climb": 30}},
            "actions": [{"id": "a_bite", "type": "weapon_attack",
                          "pipeline": []}]}


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class AssumeRevertTest(unittest.TestCase):

    def test_wild_shape_swaps_physical_keeps_mental(self):
        d = _druid(hp=22, ac=14)
        st = _state([d])
        forms.assume_form(d, _bear_form(), "wild_shape",
                            {"effect": "wild_shape"}, st)
        self.assertTrue(forms.is_transformed(d))
        self.assertEqual(forms.active_form_id(d), "m_form_bear")
        # Physical replaced
        self.assertEqual(d.abilities["str"]["score"], 19)   # bear STR
        self.assertEqual(d.ac, 11)
        self.assertEqual(d.size, "large")
        self.assertEqual(d.creature_type, "beast")
        self.assertEqual(d.hp_current, 34)                  # form HP pool
        self.assertEqual(d.hp_max, 34)
        self.assertEqual(d.speed["walk"], 40)
        # Mental KEPT (Wild Shape)
        self.assertEqual(d.abilities["wis"]["score"], 16)   # druid WIS
        self.assertEqual(d.abilities["int"]["score"], 10)

    def test_polymorph_replaces_mental_too(self):
        d = _druid()
        st = _state([d])
        forms.assume_form(d, _bear_form(), "polymorph",
                            {"effect": "polymorph"}, st)
        self.assertEqual(d.abilities["wis"]["score"], 13)   # bear WIS, not 16
        self.assertEqual(d.abilities["int"]["score"], 2)

    def test_revert_restores_true_form(self):
        d = _druid(hp=22, ac=14)
        st = _state([d])
        forms.assume_form(d, _bear_form(), "wild_shape", {}, st)
        forms.revert_form(d, st, reason="voluntary")
        self.assertFalse(forms.is_transformed(d))
        self.assertEqual(d.abilities["str"]["score"], 10)   # druid STR back
        self.assertEqual(d.ac, 14)
        self.assertEqual(d.size, "medium")
        self.assertEqual(d.creature_type, "humanoid")
        self.assertEqual(d.hp_current, 22)                  # base HP restored
        self.assertIsNone(d.base_form_snapshot)


class DamageRoutingTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def _hit(self, target, amount):
        attacker = _druid(); attacker.id = "atk"; attacker.side = "enemy"
        st = target_state = _state([attacker, target])
        st.current_attack = {"actor": attacker, "target": target,
                              "state": "hit", "action": {"id": "a_x"},
                              "had_advantage": False, "had_disadvantage": False}
        _damage({"dice": "", "modifier": amount, "type": "bludgeoning"},
                st, EventBus())
        return st

    def test_damage_hits_form_pool_then_reverts_at_zero(self):
        d = _druid(hp=22)
        st = _state([d])
        forms.assume_form(d, _bear_form(), "wild_shape", {}, st)  # 34 form HP
        # 20 damage → form HP 34→14, still transformed
        self._hit(d, 20)
        self.assertTrue(forms.is_transformed(d))
        self.assertEqual(d.hp_current, 14)
        # 14 more → form HP 0 → revert to druid at FULL base HP (Wild Shape
        # carries no overflow), not dead
        self._hit(d, 14)
        self.assertFalse(forms.is_transformed(d))
        self.assertFalse(d.is_dead)
        self.assertEqual(d.hp_current, 22)

    def test_polymorph_overflow_carries_to_true_hp(self):
        d = _druid(hp=22)
        st = _state([d])
        forms.assume_form(d, _bear_form(), "polymorph", {}, st)  # 34 form HP
        # 40 damage to a 34-HP form → 6 overflow → revert, true HP 22-6=16
        self._hit(d, 40)
        self.assertFalse(forms.is_transformed(d))
        self.assertFalse(d.is_dead)
        self.assertEqual(d.hp_current, 16)

    def test_polymorph_massive_overflow_kills(self):
        d = _druid(hp=22)
        st = _state([d])
        forms.assume_form(d, _bear_form(), "polymorph", {}, st)  # 34 form HP
        # 34 form + 22 true = 56 to fully kill; 60 overflow kills
        self._hit(d, 60)
        self.assertFalse(forms.is_transformed(d))
        self.assertTrue(d.is_dead)
        self.assertEqual(d.hp_current, 0)

    def test_wild_shape_overflow_never_kills(self):
        d = _druid(hp=22)
        st = _state([d])
        forms.assume_form(d, _bear_form(), "wild_shape", {}, st)
        self._hit(d, 999)   # huge — Wild Shape just reverts, full base HP
        self.assertFalse(d.is_dead)
        self.assertEqual(d.hp_current, 22)


class ConcentrationRevertTest(unittest.TestCase):

    def test_concentration_end_reverts_polymorph(self):
        caster = _druid(); caster.id = "caster"
        victim = _druid(hp=18); victim.id = "victim"; victim.side = "enemy"
        st = _state([caster, victim])
        # Caster polymorphs the victim, sustained by concentration.
        apply_concentration(caster, {"id": "a_polymorph",
                                        "concentration": True}, st)
        forms.assume_form(victim, _bear_form(), "polymorph",
                            {"effect": "polymorph", "caster_id": "caster",
                              "action_id": "a_polymorph"}, st)
        self.assertTrue(forms.is_transformed(victim))
        end_concentration(caster, st, reason="test")
        self.assertFalse(forms.is_transformed(victim))
        self.assertEqual(victim.hp_current, 18)   # true HP restored


if __name__ == "__main__":
    unittest.main()
