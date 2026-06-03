"""Polymorph (control) — forced WIS save → transform the TARGET into a
Beast under the form system's `polymorph` policy.

Proves the mechanic + its cross-system interactions (Legendary Resistance,
carry-overflow death revert, concentration-end revert) by driving the
spell's forced_save pipeline directly. (Class-list wiring is separate
content — the Wizard PC currently has no spell list.)
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import forms
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _forced_save, _damage

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                   schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _abil(wis_save=0):
    a = {k: {"score": 16, "save": 3} for k in
         ("str", "dex", "con", "int", "wis", "cha")}
    a["wis"] = {"score": 10 + 2 * wis_save, "save": wis_save}
    return a


def _caster():
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="wiz", name="wiz",
                  template={"id": "pc_wiz", "abilities": ab, "actions": [],
                             "cr": {"proficiency_bonus": 5},
                             "spellcasting_ability": "intelligence"},
                  side="pc", hp_current=60, hp_max=60, ac=14,
                  speed={"walk": 30}, position=(1, 0), abilities=ab)


def _target(hp=200, ctype="dragon", lr=0):
    ab = _abil()
    res = {"legendary_resistance_remaining": lr} if lr else {}
    return Actor(id="boss", name="boss",
                  template={"id": "m_boss", "abilities": ab, "actions": [],
                             "cr": {"proficiency_bonus": 5}},
                  side="enemy", hp_current=hp, hp_max=hp, ac=18,
                  speed={"walk": 40}, position=(0, 0), abilities=ab,
                  creature_type=ctype, resources=dict(res))


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


_ON_FAIL = [{"primitive": "polymorph_target", "params": {"form": "m_giant_toad"}}]


def _cast_polymorph(caster, target, state, *, dc):
    state.current_attack = {"actor": caster, "target": target,
                             "action": {"id": "a_polymorph",
                                         "concentration": True},
                             "state": None, "had_advantage": False,
                             "had_disadvantage": False}
    _forced_save({"ability": "wisdom", "dc": dc, "affected": "current_target",
                   "on_fail": _ON_FAIL, "on_success": []}, state, EventBus())


class PolymorphTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))
        self.toad_hp = int(_registry().get("monster", "m_giant_toad")
                            ["combat"]["hit_points"]["average"])

    def test_failed_save_polymorphs_into_beast(self):
        c, t = _caster(), _target(hp=200)
        st = _state([c, t])
        _cast_polymorph(c, t, st, dc=99)        # unbeatable → fail
        self.assertTrue(forms.is_transformed(t))
        self.assertEqual(forms.active_form_id(t), "m_giant_toad")
        self.assertEqual(t.hp_current, self.toad_hp)   # beast HP pool
        self.assertEqual(t.creature_type, "beast")

    def test_successful_save_no_effect(self):
        c, t = _caster(), _target(hp=200)
        st = _state([c, t])
        _cast_polymorph(c, t, st, dc=1)         # auto-succeed
        self.assertFalse(forms.is_transformed(t))
        self.assertEqual(t.hp_current, 200)

    def test_legendary_resistance_avoids_polymorph(self):
        c, t = _caster(), _target(hp=200, lr=3)
        st = _state([c, t])
        _cast_polymorph(c, t, st, dc=99)        # would fail, but LR...
        self.assertFalse(forms.is_transformed(t))    # ...auto-succeeds
        self.assertEqual(t.resources["legendary_resistance_remaining"], 2)

    def test_damage_past_form_hp_reverts_with_overflow(self):
        c, t = _caster(), _target(hp=200)
        st = _state([c, t])
        _cast_polymorph(c, t, st, dc=99)
        self.assertEqual(t.hp_current, self.toad_hp)
        # Deal toad_hp + 10 → form drops to 0, 10 overflow carries to true HP.
        atk = _caster(); atk.id = "striker"; atk.side = "enemy"
        st.current_attack = {"actor": atk, "target": t, "state": "hit",
                              "action": {"id": "a"}, "had_advantage": False,
                              "had_disadvantage": False}
        _damage({"dice": "", "modifier": self.toad_hp + 10,
                  "type": "slashing"}, st, EventBus())
        self.assertFalse(forms.is_transformed(t))
        self.assertEqual(t.creature_type, "dragon")    # true form back
        self.assertEqual(t.hp_current, 190)            # 200 - 10 overflow

    def test_concentration_end_reverts(self):
        c, t = _caster(), _target(hp=200)
        st = _state([c, t])
        apply_concentration(c, {"id": "a_polymorph", "concentration": True}, st)
        _cast_polymorph(c, t, st, dc=99)
        self.assertTrue(forms.is_transformed(t))
        end_concentration(c, st, reason="test")
        self.assertFalse(forms.is_transformed(t))
        self.assertEqual(t.hp_current, 200)            # true HP restored


if __name__ == "__main__":
    unittest.main()
