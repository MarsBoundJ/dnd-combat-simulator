"""Power of the Wilds tests (Path of the Wild Heart, Barbarian L14).

The L14 rage choice — Falcon / Lion / Ram — an independent build-time pick
(template.wild_heart_power_choice, default Ram) activated on rage entry,
alongside the L3 Rage of the Wilds aspect:

  - Falcon: Fly Speed = Speed while wearing NO armor.
  - Lion:   enemies within 5 ft have Disadvantage attacking anyone but you
            (or another active-Lion barbarian).
  - Ram:    on a melee hit, knock a Large-or-smaller target Prone (no save).

Layers:
  1. Build-time choice stamping (pc_schema) + default Ram + wears_armor.
  2. Activation / deactivation (Falcon fly grant + revert).
  3. Lion disadvantage aura (enemy yes, vs-Lion no, out-of-range no).
  4. Ram on-hit prone (size gate, idempotence, melee gate); _damage path.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import rage as R
from engine.core import wild_heart as WH
from engine.core import modifiers as M
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _ab():
    return {k: {"score": 14, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _pow(aid="pw", *, side="pc", pos=(0, 0), power="ram", size="medium",
           wears_armor=False, feature=True, level=14):
    ab = _ab()
    tmpl = {"id": f"t_{aid}", "name": aid, "abilities": ab,
            "cr": {"proficiency_bonus": 3}, "actions": [],
            "features_known": ["f_power_of_the_wilds"] if feature else [],
            "levels": {"barbarian": level}, "wears_armor": wears_armor}
    if power is not None:
        tmpl["wild_heart_power_choice"] = power
    a = Actor(id=aid, name=aid, template=tmpl, side=side,
              hp_current=100, hp_max=100, ac=14, position=pos,
              speed={"walk": 40}, abilities=ab)
    a.size = size
    return a


def _plain(aid="p", side="pc", pos=(0, 0), size="medium"):
    ab = _ab()
    a = Actor(id=aid, name=aid,
              template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                        "cr": {"proficiency_bonus": 3}, "actions": []},
              side=side, hp_current=100, hp_max=100, ac=14,
              position=pos, speed={"walk": 30}, abilities=ab)
    a.size = size
    return a


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class BuildChoiceTest(unittest.TestCase):

    def _template(self, choice=None, armor=None):
        spec = {"id": "z", "class": "c_barbarian", "level": 14,
                "subclass": "sc_path_of_the_wild_heart",
                "ability_scores": {"str": 20, "dex": 14, "con": 18,
                                   "int": 8, "wis": 12, "cha": 8},
                "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                             "damage_type": "slashing",
                             "attack_ability": "str", "reach_ft": 5}]}
        if choice is not None:
            spec["wild_heart_power_choice"] = choice
        if armor is not None:
            spec["armor"] = armor
        return build_pc_template(spec, _registry())

    def test_choice_stamped(self):
        self.assertEqual(self._template("falcon").get("wild_heart_power_choice"),
                         "falcon")

    def test_default_is_ram(self):
        self.assertEqual(self._template().get("wild_heart_power_choice"), "ram")

    def test_invalid_falls_back_to_ram(self):
        self.assertEqual(self._template("tiger").get("wild_heart_power_choice"),
                         "ram")

    def test_wears_armor_false_when_unarmored(self):
        self.assertFalse(self._template().get("wears_armor"))

    def test_wears_armor_true_with_armor(self):
        t = self._template(armor={"base_ac": 14, "max_dex_bonus": 2})
        self.assertTrue(t.get("wears_armor"))

    def test_feature_present_at_l14(self):
        self.assertIn("f_power_of_the_wilds",
                      self._template().get("features_known", []))


class ActivationTest(unittest.TestCase):

    def test_activates_on_rage_entry(self):
        a = _pow(power="lion")
        st = _state([a])
        R.enter_rage(a, st)
        self.assertEqual(a.wild_heart_power_active, "lion")

    def test_deactivates_on_rage_end(self):
        a = _pow(power="ram")
        st = _state([a])
        R.enter_rage(a, st)
        R.end_rage(a, st, reason="manual")
        self.assertIsNone(a.wild_heart_power_active)

    def test_no_activation_without_feature(self):
        a = _pow(power="ram", feature=False)
        st = _state([a])
        R.enter_rage(a, st)
        self.assertIsNone(a.wild_heart_power_active)

    def test_default_to_ram_when_unset(self):
        a = _pow(power=None)
        st = _state([a])
        R.enter_rage(a, st)
        self.assertEqual(a.wild_heart_power_active, "ram")

    def test_event_logged(self):
        a = _pow(power="falcon")
        st = _state([a])
        R.enter_rage(a, st)
        events = [e.get("event") for e in st.event_log]
        self.assertIn("power_of_the_wilds_activated", events)

    def test_independent_of_l3_aspect(self):
        # A L14 barbarian can hold BOTH an L3 aspect and an L14 option.
        a = _pow(power="ram")
        a.template["features_known"] = ["f_rage_of_the_wilds",
                                          "f_power_of_the_wilds"]
        a.template["wild_heart_rage_choice"] = "bear"
        st = _state([a])
        R.enter_rage(a, st)
        self.assertEqual(a.wild_heart_active_choice, "bear")
        self.assertEqual(a.wild_heart_power_active, "ram")


class FalconTest(unittest.TestCase):

    def test_fly_granted_when_unarmored(self):
        a = _pow(power="falcon", wears_armor=False)
        st = _state([a])
        R.enter_rage(a, st)
        self.assertEqual(a.speed.get("fly"), 40)

    def test_no_fly_when_armored(self):
        a = _pow(power="falcon", wears_armor=True)
        st = _state([a])
        R.enter_rage(a, st)
        self.assertIsNone(a.speed.get("fly"))

    def test_fly_reverts_on_rage_end(self):
        a = _pow(power="falcon", wears_armor=False)
        st = _state([a])
        R.enter_rage(a, st)
        R.end_rage(a, st, reason="manual")
        self.assertIsNone(a.speed.get("fly"))

    def test_prior_fly_restored_on_rage_end(self):
        a = _pow(power="falcon", wears_armor=False)
        a.speed["fly"] = 60   # pre-existing fly (e.g., from a spell)
        st = _state([a])
        R.enter_rage(a, st)
        R.end_rage(a, st, reason="manual")
        self.assertEqual(a.speed.get("fly"), 60)


class LionAuraTest(unittest.TestCase):

    def _setup(self, foe_pos=(1, 0)):
        lion = _pow("lion", power="lion", pos=(0, 0))
        ally = _plain("ally", side="pc", pos=(2, 0))
        foe = _plain("foe", side="enemy", pos=foe_pos)
        st = _state([lion, ally, foe])
        R.enter_rage(lion, st)
        return lion, ally, foe, st

    def test_enemy_disadvantage_vs_non_lion(self):
        lion, ally, foe, st = self._setup()
        self.assertTrue(
            M.query_attack_modifiers(foe, ally, st).has_disadvantage)

    def test_no_disadvantage_attacking_lion(self):
        lion, ally, foe, st = self._setup()
        self.assertFalse(
            M.query_attack_modifiers(foe, lion, st).has_disadvantage)

    def test_no_disadvantage_when_enemy_far_from_lion(self):
        # Foe 50 ft from lion → not within 5 ft → no aura.
        lion, ally, foe, st = self._setup(foe_pos=(10, 0))
        self.assertFalse(
            M.query_attack_modifiers(foe, ally, st).has_disadvantage)

    def test_no_aura_when_lion_not_raging(self):
        lion, ally, foe, st = self._setup()
        R.end_rage(lion, st, reason="manual")
        self.assertFalse(
            M.query_attack_modifiers(foe, ally, st).has_disadvantage)


class RamTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_predicate_knocks_large_prone(self):
        ram = _pow("ram", power="ram")
        foe = _plain("foe", side="enemy", pos=(1, 0), size="large")
        st = _state([ram, foe])
        R.enter_rage(ram, st)
        st.current_attack = {"actor": ram, "target": foe, "state": "hit"}
        WH.try_apply_ram(ram, foe, st, {"kind": "melee"})
        self.assertTrue(any(c.get("condition_id") == "co_prone"
                             for c in foe.applied_conditions))

    def test_huge_target_not_proned(self):
        ram = _pow("ram", power="ram")
        foe = _plain("foe", side="enemy", pos=(1, 0), size="huge")
        st = _state([ram, foe])
        R.enter_rage(ram, st)
        st.current_attack = {"actor": ram, "target": foe, "state": "hit"}
        WH.try_apply_ram(ram, foe, st, {"kind": "melee"})
        self.assertFalse(any(c.get("condition_id") == "co_prone"
                              for c in foe.applied_conditions))

    def test_ranged_hit_does_not_prone(self):
        ram = _pow("ram", power="ram")
        foe = _plain("foe", side="enemy", pos=(1, 0), size="medium")
        st = _state([ram, foe])
        R.enter_rage(ram, st)
        st.current_attack = {"actor": ram, "target": foe, "state": "hit"}
        WH.try_apply_ram(ram, foe, st, {"kind": "ranged"})
        self.assertFalse(any(c.get("condition_id") == "co_prone"
                              for c in foe.applied_conditions))

    def test_idempotent_on_already_prone(self):
        ram = _pow("ram", power="ram")
        foe = _plain("foe", side="enemy", pos=(1, 0), size="medium")
        foe.applied_conditions.append({"condition_id": "co_prone"})
        st = _state([ram, foe])
        R.enter_rage(ram, st)
        st.current_attack = {"actor": ram, "target": foe, "state": "hit"}
        WH.try_apply_ram(ram, foe, st, {"kind": "melee"})
        prone = [c for c in foe.applied_conditions
                 if c.get("condition_id") == "co_prone"]
        self.assertEqual(len(prone), 1)   # not doubled

    def test_no_prone_when_not_ram(self):
        a = _pow("lion", power="lion")
        foe = _plain("foe", side="enemy", pos=(1, 0), size="medium")
        st = _state([a, foe])
        R.enter_rage(a, st)
        st.current_attack = {"actor": a, "target": foe, "state": "hit"}
        WH.try_apply_ram(a, foe, st, {"kind": "melee"})
        self.assertFalse(any(c.get("condition_id") == "co_prone"
                              for c in foe.applied_conditions))

    def test_fires_through_damage_pipeline(self):
        ram = _pow("ram", power="ram")
        foe = _plain("foe", side="enemy", pos=(1, 0), size="large")
        st = _state([ram, foe])
        R.enter_rage(ram, st)
        # Real combat populates attack_roll_params; mirror that here so the
        # _damage on-hit melee block (is_weapon_attack) fires.
        st.current_attack = {"actor": ram, "target": foe, "state": "hit",
                              "attack_roll_params": {"kind": "melee"}}
        primitives_module._damage(
            {"dice": "", "modifier": 5, "type": "slashing"}, st, EventBus())
        self.assertTrue(any(c.get("condition_id") == "co_prone"
                             for c in foe.applied_conditions))


if __name__ == "__main__":
    unittest.main()
