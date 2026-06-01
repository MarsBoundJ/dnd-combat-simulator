"""Monster Shape-Shift (2024 "Change Shape") — stat-preserving form change.

RAW (SRD 5.2.1): "Its game statistics, OTHER THAN ITS SIZE, are the same
in each form." So Shape-Shift changes only `size` (+ creature_type if the
form declares one) and keeps HP / AC / abilities / attacks. It rides the
form core's `change_shape` policy (hp: keep).

Layers:
  1. _shape_shift changes only size; HP/AC/abilities/template preserved
  2. creature_type changes only when the form declares one
  3. voluntary revert restores the true size, leaving HP untouched
  4. CRITICAL: a creature dropped to 0 HP while shifted DIES (reverting to
     true size) — it is NOT resurrected by a stale HP snapshot
  5. Wild Shape (hp: replace) is unaffected by the keep-policy changes
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import forms
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import (_shape_shift, _shape_shift_revert, _damage,
                                  _wild_shape_transform)


def _abil(s=16, d=14, c=14, i=10, w=11, ch=18):
    return {"str": {"score": s, "save": 3}, "dex": {"score": d, "save": 2},
            "con": {"score": c, "save": 2}, "int": {"score": i, "save": 0},
            "wis": {"score": w, "save": 0}, "cha": {"score": ch, "save": 4}}


def _shifter(hp=40, ac=14):
    ab = _abil()
    return Actor(id="doppel", name="doppel",
                  template={"id": "m_doppelganger", "name": "Doppelganger",
                             "abilities": ab,
                             "actions": [{"id": "a_slam", "type": "weapon_attack",
                                           "pipeline": []}],
                             "cr": {"proficiency_bonus": 2}},
                  side="enemy", hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": 30}, position=(0, 0), abilities=ab,
                  size="medium", creature_type="monstrosity")


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class StatPreservingTest(unittest.TestCase):

    def test_shape_shift_changes_only_size(self):
        d = _shifter(hp=40, ac=14)
        st = _state([d])
        st.current_attack = {"actor": d}
        _shape_shift({"form_id": "noble", "size": "small"}, st, EventBus())
        self.assertTrue(forms.is_transformed(d))
        self.assertEqual(d.size, "small")           # size changed
        # Everything else preserved
        self.assertEqual(d.hp_current, 40)
        self.assertEqual(d.hp_max, 40)
        self.assertEqual(d.ac, 14)
        self.assertEqual(d.abilities["cha"]["score"], 18)
        self.assertEqual(d.template["id"], "m_doppelganger")  # NOT swapped
        self.assertEqual(d.creature_type, "monstrosity")      # unchanged

    def test_creature_type_changes_only_if_declared(self):
        d = _shifter()
        st = _state([d])
        st.current_attack = {"actor": d}
        _shape_shift({"form_id": "wolf", "size": "large",
                       "creature_type": "beast"}, st, EventBus())
        self.assertEqual(d.size, "large")
        self.assertEqual(d.creature_type, "beast")

    def test_voluntary_revert_restores_size_keeps_hp(self):
        d = _shifter(hp=40)
        st = _state([d])
        st.current_attack = {"actor": d}
        _shape_shift({"form_id": "small_form", "size": "small"}, st, EventBus())
        d.hp_current = 25                       # took damage while shifted
        _shape_shift_revert({}, st, EventBus())
        self.assertFalse(forms.is_transformed(d))
        self.assertEqual(d.size, "medium")      # true size back
        self.assertEqual(d.hp_current, 25)      # HP NOT restored to 40


class DeathWhileShiftedTest(unittest.TestCase):
    """The resurrection guard: a stat-preserving form has no HP pool to
    fall back on, so 0 HP means death."""

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def _hit(self, target, amount, state):
        attacker = _shifter(); attacker.id = "atk"; attacker.side = "pc"
        state.current_attack = {"actor": attacker, "target": target,
                                 "state": "hit", "action": {"id": "a_x"},
                                 "had_advantage": False,
                                 "had_disadvantage": False}
        _damage({"dice": "", "modifier": amount, "type": "bludgeoning"},
                state, EventBus())

    def test_zero_hp_while_shifted_dies_not_resurrects(self):
        d = _shifter(hp=30)
        st = _state([d])
        st.current_attack = {"actor": d}
        _shape_shift({"form_id": "small", "size": "small"}, st, EventBus())
        self._hit(d, 30, st)                    # exactly lethal
        self.assertEqual(d.hp_current, 0)
        self.assertTrue(d.is_dead)              # DIED — not rescued
        self.assertFalse(forms.is_transformed(d))   # reverted as it fell
        self.assertEqual(d.size, "medium")      # to true size

    def test_overkill_while_shifted_dies(self):
        d = _shifter(hp=30)
        st = _state([d])
        st.current_attack = {"actor": d}
        _shape_shift({"form_id": "small", "size": "small"}, st, EventBus())
        self._hit(d, 999, st)
        self.assertTrue(d.is_dead)
        self.assertEqual(d.hp_current, 0)


class WildShapeUnaffectedTest(unittest.TestCase):
    """The hp:keep changes must not regress the hp:replace (Wild Shape)
    path: assuming a beast form still adopts the form's HP pool."""

    def test_wild_shape_still_replaces_hp(self):
        # A druid-ish actor wild-shaping into a synthetic registry beast.
        ab = _abil()
        druid = Actor(id="druid", name="druid",
                       template={"id": "pc_druid", "abilities": ab,
                                  "actions": [], "cr": {"proficiency_bonus": 2}},
                       side="pc", hp_current=22, hp_max=22, ac=14,
                       speed={"walk": 30}, position=(0, 0), abilities=ab,
                       size="medium", creature_type="humanoid")
        bear = {"id": "m_form_bear", "size": "large", "creature_type": "beast",
                "abilities": _abil(19, 10, 16, 2, 13, 7),
                "combat": {"armor_class": 11,
                            "hit_points": {"average": 34}},
                "actions": []}

        class _Reg:
            def get(self, etype, eid):
                return bear
        st = _state([druid])
        st.content_registry = _Reg()
        st.current_attack = {"actor": druid}
        _wild_shape_transform({"form": "m_form_bear"}, st, EventBus())
        self.assertEqual(druid.hp_current, 34)   # adopted the bear's HP
        self.assertEqual(druid.abilities["str"]["score"], 19)


if __name__ == "__main__":
    unittest.main()
