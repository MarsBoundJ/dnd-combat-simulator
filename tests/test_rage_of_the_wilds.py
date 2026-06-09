"""Rage of the Wilds tests (Path of the Wild Heart, Barbarian L3).

The L3 rage choice — Bear / Eagle / Wolf — chosen at build time
(template.wild_heart_rage_choice, default Bear) and activated on rage entry:

  - Bear:  Resistance to every damage type except Force/Necrotic/Psychic/
           Radiant (broader than base Rage B/P/S; no double-halve).
  - Eagle: rage-entry Dash + Disengage grant.
  - Wolf:  allies have Advantage attacking enemies within 5 ft of the Wolf.

Layers:
  1. Build-time choice stamping (pc_schema) + default to Bear.
  2. Activation on rage entry / deactivation on rage end.
  3. Bear resistance (predicate + real _damage halving; exceptions).
  4. Eagle rage-entry grant.
  5. Wolf advantage aura (ally yes, self no, out-of-range no, enemy-side no).
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


def _wild_heart(aid="wh", *, side="pc", pos=(0, 0), choice="bear",
                  hp=100, level=3, feature=True):
    ab = _ab()
    tmpl = {"id": f"t_{aid}", "name": aid, "abilities": ab,
            "cr": {"proficiency_bonus": 2}, "actions": [],
            "features_known": ["f_rage_of_the_wilds"] if feature else [],
            "levels": {"barbarian": level}}
    if choice is not None:
        tmpl["wild_heart_rage_choice"] = choice
    return Actor(id=aid, name=aid, template=tmpl, side=side,
                 hp_current=hp, hp_max=hp, ac=14, position=pos,
                 speed={"walk": 30}, abilities=ab)


def _plain(aid="p", side="pc", pos=(0, 0)):
    ab = _ab()
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=100, hp_max=100, ac=14,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class BuildChoiceTest(unittest.TestCase):

    def _template(self, choice=None):
        spec = {"id": "z", "class": "c_barbarian", "level": 3,
                "subclass": "sc_path_of_the_wild_heart",
                "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                   "int": 8, "wis": 10, "cha": 8},
                "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                             "damage_type": "slashing",
                             "attack_ability": "str", "reach_ft": 5}]}
        if choice is not None:
            spec["wild_heart_rage_choice"] = choice
        return build_pc_template(spec, _registry())

    def test_choice_stamped(self):
        self.assertEqual(self._template("wolf").get("wild_heart_rage_choice"),
                         "wolf")

    def test_default_is_bear(self):
        self.assertEqual(self._template().get("wild_heart_rage_choice"),
                         "bear")

    def test_invalid_choice_falls_back_to_bear(self):
        self.assertEqual(self._template("dragon").get("wild_heart_rage_choice"),
                         "bear")

    def test_feature_present_at_l3(self):
        self.assertIn("f_rage_of_the_wilds",
                      self._template().get("features_known", []))


class ActivationTest(unittest.TestCase):

    def test_activates_on_rage_entry(self):
        a = _wild_heart(choice="bear")
        st = _state([a])
        R.enter_rage(a, st)
        self.assertEqual(a.wild_heart_active_choice, "bear")

    def test_deactivates_on_rage_end(self):
        a = _wild_heart(choice="wolf")
        st = _state([a])
        R.enter_rage(a, st)
        R.end_rage(a, st, reason="manual")
        self.assertIsNone(a.wild_heart_active_choice)

    def test_no_activation_without_feature(self):
        a = _wild_heart(choice="bear", feature=False)
        st = _state([a])
        R.enter_rage(a, st)
        self.assertIsNone(a.wild_heart_active_choice)

    def test_unset_choice_defaults_to_bear(self):
        a = _wild_heart(choice=None)
        st = _state([a])
        R.enter_rage(a, st)
        self.assertEqual(a.wild_heart_active_choice, "bear")

    def test_activation_logs_event(self):
        a = _wild_heart(choice="eagle")
        st = _state([a])
        R.enter_rage(a, st)
        events = [e.get("event") for e in st.event_log]
        self.assertIn("rage_of_the_wilds_activated", events)


class BearResistanceTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_resists_fire(self):
        a = _wild_heart(choice="bear")
        a.wild_heart_active_choice = "bear"
        self.assertTrue(WH.applies_bear_resistance(a, "fire"))

    def test_resists_physical(self):
        a = _wild_heart(choice="bear")
        a.wild_heart_active_choice = "bear"
        for t in ("bludgeoning", "piercing", "slashing"):
            self.assertTrue(WH.applies_bear_resistance(a, t))

    def test_does_not_resist_exceptions(self):
        a = _wild_heart(choice="bear")
        a.wild_heart_active_choice = "bear"
        for t in ("force", "necrotic", "psychic", "radiant"):
            self.assertFalse(WH.applies_bear_resistance(a, t))

    def test_no_resistance_when_not_bear(self):
        a = _wild_heart(choice="wolf")
        a.wild_heart_active_choice = "wolf"
        self.assertFalse(WH.applies_bear_resistance(a, "fire"))

    def test_no_resistance_when_inactive(self):
        a = _wild_heart(choice="bear")
        a.wild_heart_active_choice = None
        self.assertFalse(WH.applies_bear_resistance(a, "fire"))

    def test_fire_damage_halved_through_damage(self):
        bear = _wild_heart(choice="bear")
        enemy = _plain("foe", side="enemy", pos=(1, 0))
        st = _state([bear, enemy])
        R.enter_rage(bear, st)
        st.current_attack = {"actor": enemy, "target": bear, "state": "hit"}
        hp0 = bear.hp_current
        primitives_module._damage({"dice": "", "modifier": 20, "type": "fire"},
                                   st, EventBus())
        self.assertEqual(hp0 - bear.hp_current, 10)

    def test_radiant_damage_not_halved(self):
        bear = _wild_heart(choice="bear")
        enemy = _plain("foe", side="enemy", pos=(1, 0))
        st = _state([bear, enemy])
        R.enter_rage(bear, st)
        st.current_attack = {"actor": enemy, "target": bear, "state": "hit"}
        hp0 = bear.hp_current
        primitives_module._damage({"dice": "", "modifier": 20, "type": "radiant"},
                                   st, EventBus())
        self.assertEqual(hp0 - bear.hp_current, 20)

    def test_no_double_halve_with_base_rage_bps(self):
        # Slashing is already halved by base Rage BPS; Bear must not
        # double-halve (20 → 10, not 5).
        bear = _wild_heart(choice="bear")
        enemy = _plain("foe", side="enemy", pos=(1, 0))
        st = _state([bear, enemy])
        R.enter_rage(bear, st)
        st.current_attack = {"actor": enemy, "target": bear, "state": "hit"}
        hp0 = bear.hp_current
        primitives_module._damage({"dice": "", "modifier": 20, "type": "slashing"},
                                   st, EventBus())
        self.assertEqual(hp0 - bear.hp_current, 10)


class EagleTest(unittest.TestCase):

    def test_rage_entry_grants_dash_and_disengage(self):
        a = _wild_heart(choice="eagle")
        st = _state([a])
        R.enter_rage(a, st)
        self.assertTrue(a.disengaging)
        self.assertTrue(a.dashed_this_turn)

    def test_bear_does_not_grant_dash(self):
        a = _wild_heart(choice="bear")
        st = _state([a])
        R.enter_rage(a, st)
        self.assertFalse(a.dashed_this_turn)


class WolfAuraTest(unittest.TestCase):

    def _setup(self, foe_pos=(1, 0)):
        wolf = _wild_heart("wolf", choice="wolf", pos=(0, 0))
        ally = _plain("ally", side="pc", pos=(5, 0))
        foe = _plain("foe", side="enemy", pos=foe_pos)
        st = _state([wolf, ally, foe])
        R.enter_rage(wolf, st)
        return wolf, ally, foe, st

    def test_ally_has_advantage_vs_adjacent_enemy(self):
        wolf, ally, foe, st = self._setup()
        self.assertTrue(M.query_attack_modifiers(ally, foe, st).has_advantage)

    def test_wolf_self_no_advantage_from_own_aura(self):
        wolf, ally, foe, st = self._setup()
        self.assertFalse(M.query_attack_modifiers(wolf, foe, st).has_advantage)

    def test_no_advantage_vs_distant_enemy(self):
        wolf, ally, foe, st = self._setup(foe_pos=(10, 0))  # 50 ft from wolf
        self.assertFalse(M.query_attack_modifiers(ally, foe, st).has_advantage)

    def test_no_aura_when_wolf_not_raging(self):
        wolf, ally, foe, st = self._setup()
        R.end_rage(wolf, st, reason="manual")
        self.assertFalse(M.query_attack_modifiers(ally, foe, st).has_advantage)

    def test_bear_choice_grants_no_aura(self):
        bear = _wild_heart("bear", choice="bear", pos=(0, 0))
        ally = _plain("ally", side="pc", pos=(5, 0))
        foe = _plain("foe", side="enemy", pos=(1, 0))
        st = _state([bear, ally, foe])
        R.enter_rage(bear, st)
        self.assertFalse(M.query_attack_modifiers(ally, foe, st).has_advantage)


if __name__ == "__main__":
    unittest.main()
