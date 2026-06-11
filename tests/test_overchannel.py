"""Overchannel — Evoker (Wizard L14) damage maximizer.

Covers the maximize-dice primitive branch, the apply_overchannel
transform (stamp + escalating reuse self-damage), eligibility gating,
and the PC-build wiring (resource counter + feature presence). Mirrors
the metamagic test style: the mechanic is correct + directly testable;
proactive AI selection is deferred.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine.core import overchannel
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources
from engine.primitives import _damage, _roll_dice_maximized

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _abilities():
    return {k: {"score": 10, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _evoker(level=14, hp=80):
    a = Actor(id="evk", name="evk",
               template={"id": "t", "name": "evk", "abilities": _abilities(),
                          "cr": {"proficiency_bonus": 5},
                          "features_known": ["f_overchannel"]},
               side="pc", hp_current=hp, hp_max=hp, ac=12,
               speed={"walk": 30}, position=(0, 0), abilities=_abilities())
    a.resources = {}
    return a


def _foe(hp=400):
    return Actor(id="foe", name="foe", template={"abilities": {}},
                  side="enemy", hp_current=hp, hp_max=hp, ac=10,
                  speed={"walk": 30}, position=(1, 0), abilities=_abilities())


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [x.id for x in actors]
    st.round = 1
    return st


def _fireball(level=3):
    return {"id": "a_fireball", "spell_slot_level": level,
            "pipeline": [{"primitive": "forced_save",
                           "params": {"on_fail": [{"primitive": "damage",
                                                    "params": {"dice": "8d6",
                                                                "type": "fire"}}],
                                       "on_success": []}}]}


class RollMaximizedTest(unittest.TestCase):
    def test_maximized_is_count_times_sides(self):
        self.assertEqual(_roll_dice_maximized("8d6"), 48)
        self.assertEqual(_roll_dice_maximized("1d12"), 12)
        self.assertEqual(_roll_dice_maximized("10d10"), 100)


class MaximizeDamageStepTest(unittest.TestCase):
    def test_damage_with_maximize_flag_deals_max(self):
        evk, foe = _evoker(), _foe()
        st = _state([evk, foe])
        st.current_attack = {"actor": evk, "target": foe,
                              "action": {"id": "x"}, "state": "hit"}
        hp = foe.hp_current
        _damage({"dice": "8d6", "type": "fire", "maximize_dice": True},
                st, EventBus())
        self.assertEqual(hp - foe.hp_current, 48)


class EligibilityTest(unittest.TestCase):
    def test_eligible_damage_spell_levels_1_to_5(self):
        self.assertTrue(overchannel.is_eligible(_fireball(3)))
        self.assertTrue(overchannel.is_eligible(_fireball(1)))
        self.assertTrue(overchannel.is_eligible(_fireball(5)))

    def test_ineligible_level_6_or_cantrip_or_no_damage(self):
        self.assertFalse(overchannel.is_eligible(_fireball(6)))
        self.assertFalse(overchannel.is_eligible(_fireball(0)))
        no_dmg = {"id": "a_shield", "spell_slot_level": 1, "pipeline": []}
        self.assertFalse(overchannel.is_eligible(no_dmg))


class ApplyOverchannelTest(unittest.TestCase):
    def test_first_use_stamps_flag_no_self_damage(self):
        evk, foe = _evoker(), _foe()
        st = _state([evk, foe])
        action = _fireball(3)
        hp = evk.hp_current
        modified = overchannel.apply_overchannel(action, evk, st,
                                                  random.Random(1))
        # The damage step in the modified copy is maximized.
        from engine.core.metamagic import _iter_damage_params
        params = list(_iter_damage_params(modified))
        self.assertTrue(all(p.get("maximize_dice") for p in params))
        # Original untouched.
        orig = list(_iter_damage_params(action))
        self.assertFalse(any(p.get("maximize_dice") for p in orig))
        # First use is free; counter advances to 1.
        self.assertEqual(evk.hp_current, hp)
        self.assertEqual(evk.resources["overchannel_uses_this_rest"], 1)

    def test_reuse_applies_escalating_self_damage(self):
        evk, foe = _evoker(), _foe()
        st = _state([evk, foe])
        evk.resources["overchannel_uses_this_rest"] = 1   # one free use spent
        hp = evk.hp_current
        overchannel.apply_overchannel(_fireball(3), evk, st, random.Random(7))
        # 2nd use of a level-3 spell: (2 * 3) = 6 d12 necrotic to self.
        ev = [e for e in st.event_log if e.get("event") == "overchannel_used"][-1]
        dmg = ev["self_damage"]
        self.assertEqual(ev["use_number"], 2)
        self.assertTrue(6 <= dmg <= 72)
        self.assertEqual(evk.hp_current, hp - dmg)
        self.assertEqual(evk.resources["overchannel_uses_this_rest"], 2)


class PCBuildWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                     schema_root=SCHEMA_ROOT)

    def test_evoker_l14_has_overchannel_and_counter(self):
        pc = {"id": "w", "class": "c_wizard", "level": 14,
              "subclass": "sc_evoker",
              "ability_scores": {"str": 8, "dex": 14, "con": 14,
                                  "int": 18, "wis": 10, "cha": 10},
              "weapons": []}
        tmpl = build_pc_template(pc, self.registry)
        self.assertIn("f_overchannel", tmpl.get("features_known", []))
        res = derive_pc_resources(pc, self.registry)
        self.assertEqual(res.get("overchannel_uses_this_rest"), 0)


if __name__ == "__main__":
    unittest.main()
