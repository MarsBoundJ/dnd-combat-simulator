"""Warrior of the Gods tests (Path of the Zealot, Barbarian L3).

A Bonus-Action self-heal from a d12 dice pool (4/5/6/7 at L3/6/12/17).
The primitive spends the fewest dice that cover missing HP, rolls them,
and heals the actor; the pool refreshes on a Long Rest; the AI scores it
as a self-heal.

Layers:
  1. Resource seeding by level (4/5/6/7).
  2. Primitive: heals self, drains pool, never overheals, no-ops at full
     HP / empty pool.
  3. Long-rest refresh restores the pool.
  4. Heal scoring: positive when wounded, 0 at full HP / empty / non-self.
  5. is_self_targeted_heal recognizes it.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.basic_actions import is_self_targeted_heal
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import derive_pc_resources
from engine.primitives import _warrior_of_the_gods

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                          schema_root=_REPO / "schema")


_ACTION = {
    "id": "a_warrior_of_the_gods", "name": "Warrior of the Gods",
    "type": "heal", "slot": "bonus_action",
    "pipeline": [{"primitive": "warrior_of_the_gods",
                    "params": {"target": "self"}}],
}


def _zealot(*, hp=20, hp_max=100, dice=4):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    a = Actor(id="z", name="z",
                template={"id": "t_z", "name": "z", "abilities": ab,
                            "cr": {"proficiency_bonus": 2}, "actions": []},
                side="pc", hp_current=hp, hp_max=hp_max, ac=12,
                position=(0, 0), speed={"walk": 30}, abilities=ab)
    a.resources = {"warrior_of_the_gods_dice_remaining": dice,
                     "warrior_of_the_gods_dice_max": dice}
    return a


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [x.id for x in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class ResourceSeedingTest(unittest.TestCase):

    def _dice(self, level):
        spec = {
            "id": "z", "class": "c_barbarian", "level": level,
            "subclass": "sc_path_of_the_zealot",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                 "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                          "damage_type": "slashing", "attack_ability": "str",
                          "reach_ft": 5}],
        }
        r = derive_pc_resources(spec, _registry())
        return r.get("warrior_of_the_gods_dice_remaining")

    def test_pool_scales_by_level(self):
        self.assertEqual(self._dice(3), 4)
        self.assertEqual(self._dice(5), 4)
        self.assertEqual(self._dice(6), 5)
        self.assertEqual(self._dice(12), 6)
        self.assertEqual(self._dice(17), 7)
        self.assertEqual(self._dice(20), 7)


class PrimitiveTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(4))

    def _heal(self, actor):
        st = _state([actor])
        st.current_attack = {"actor": actor, "target": actor}
        _warrior_of_the_gods({"target": "self"}, st, EventBus())
        return st

    def test_heals_self_and_drains_pool(self):
        z = _zealot(hp=20, hp_max=100, dice=4)
        self._heal(z)
        self.assertGreater(z.hp_current, 20)
        self.assertLess(z.resources["warrior_of_the_gods_dice_remaining"], 4)

    def test_never_overheals_past_max(self):
        z = _zealot(hp=98, hp_max=100, dice=4)
        self._heal(z)
        self.assertLessEqual(z.hp_current, 100)

    def test_noop_at_full_hp(self):
        z = _zealot(hp=100, hp_max=100, dice=4)
        self._heal(z)
        self.assertEqual(z.hp_current, 100)
        self.assertEqual(z.resources["warrior_of_the_gods_dice_remaining"], 4)

    def test_noop_when_pool_empty(self):
        z = _zealot(hp=20, hp_max=100, dice=0)
        self._heal(z)
        self.assertEqual(z.hp_current, 20)

    def test_spends_more_dice_for_bigger_wound(self):
        # Missing 90 HP → needs ceil(90/6.5)=14 dice but capped at pool 4.
        z = _zealot(hp=10, hp_max=100, dice=4)
        self._heal(z)
        self.assertEqual(z.resources["warrior_of_the_gods_dice_remaining"], 0)


class LongRestRefreshTest(unittest.TestCase):

    def test_long_rest_restores_pool(self):
        from engine.core.rest import _refresh_warrior_of_the_gods_pool_to_max
        z = _zealot(dice=4)
        z.resources["warrior_of_the_gods_dice_remaining"] = 1
        result = _refresh_warrior_of_the_gods_pool_to_max(z)
        self.assertEqual(result, {"new_total": 4})
        self.assertEqual(z.resources["warrior_of_the_gods_dice_remaining"], 4)

    def test_noop_for_non_zealot(self):
        from engine.core.rest import _refresh_warrior_of_the_gods_pool_to_max
        ab = {k: {"score": 10, "save": 0}
              for k in ("str", "dex", "con", "int", "wis", "cha")}
        plain = Actor(id="p", name="p",
                        template={"id": "t", "name": "p", "abilities": ab,
                                    "cr": {"proficiency_bonus": 2},
                                    "actions": []},
                        side="pc", hp_current=10, hp_max=10, ac=10,
                        position=(0, 0), speed={"walk": 30}, abilities=ab)
        plain.resources = {}
        self.assertIsNone(_refresh_warrior_of_the_gods_pool_to_max(plain))


class ScoringTest(unittest.TestCase):

    def test_self_marker_recognized(self):
        self.assertTrue(is_self_targeted_heal(_ACTION))

    def test_positive_value_when_wounded(self):
        from engine.ai.defensive_ehp import defensive_ehp_healing
        z = _zealot(hp=20, hp_max=100, dice=4)
        st = _state([z])
        self.assertGreater(defensive_ehp_healing(z, z, _ACTION, st), 0.0)

    def test_zero_at_full_hp(self):
        from engine.ai.defensive_ehp import defensive_ehp_healing
        z = _zealot(hp=100, hp_max=100, dice=4)
        st = _state([z])
        self.assertEqual(defensive_ehp_healing(z, z, _ACTION, st), 0.0)

    def test_zero_when_pool_empty(self):
        from engine.ai.defensive_ehp import defensive_ehp_healing
        z = _zealot(hp=20, hp_max=100, dice=0)
        st = _state([z])
        self.assertEqual(defensive_ehp_healing(z, z, _ACTION, st), 0.0)


if __name__ == "__main__":
    unittest.main()
