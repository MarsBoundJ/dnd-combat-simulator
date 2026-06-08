"""Rage of the Gods tests (Path of the Zealot, Barbarian L14).

1/long-rest divine form activated on Rage entry:
  - Flight: fly speed = walk speed.
  - Resistance to Necrotic, Psychic, Radiant.
  - Revivification (reaction): ally within 30 ft would drop to 0 HP →
    spend Rage use → set ally HP to Barbarian level.

Layers:
  1. Resource seeding at L14 (PC schema).
  2. Activation: try_activate sets flag, fly speed, decrements use.
  3. Deactivation: fly speed reverted, flag cleared on rage end.
  4. Resistance: N/P/R halved while active.
  5. Revivification: restores ally from 0 HP, spends Rage use.
  6. Long-rest refresh.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import derive_pc_resources
from engine.core.rage_of_the_gods import (
    try_activate_rage_of_the_gods,
    deactivate_rage_of_the_gods,
    applies_resistance,
    execute_revivification,
)

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _ab():
    return {k: {"score": 10, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _zealot(*, level=14, uses=1, raging=True):
    ab = _ab()
    a = Actor(id="z", name="z",
              template={"id": "t_z", "name": "z", "abilities": ab,
                        "cr": {"proficiency_bonus": 2}, "actions": [],
                        "features_known": ["f_rage_of_the_gods"],
                        "levels": {"barbarian": level}},
              side="pc", hp_current=80, hp_max=150, ac=12,
              position=(0, 0), speed={"walk": 30}, abilities=ab)
    a.resources = {"rage_of_the_gods_uses_remaining": uses,
                   "rage_of_the_gods_uses_max": 1,
                   "rage_uses_remaining": 3}
    a.rage_active = raging
    a.rage_damage_bonus = 3
    return a


def _ally(aid="ally1", pos=(2, 0)):  # 2 grid squares = 10 ft (within 30 ft range)
    ab = _ab()
    a = Actor(id=aid, name=aid,
              template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                        "cr": {"proficiency_bonus": 2}, "actions": []},
              side="pc", hp_current=30, hp_max=100, ac=12,
              position=pos, speed={"walk": 30}, abilities=ab)
    return a


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [x.id for x in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class ResourceSeedingTest(unittest.TestCase):

    def test_resource_seeded_at_l14(self):
        spec = {
            "id": "z", "class": "c_barbarian", "level": 14,
            "subclass": "sc_path_of_the_zealot",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                         "damage_type": "slashing", "attack_ability": "str",
                         "reach_ft": 5}],
        }
        r = derive_pc_resources(spec, _registry())
        self.assertEqual(r.get("rage_of_the_gods_uses_remaining"), 1)
        self.assertEqual(r.get("rage_of_the_gods_uses_max"), 1)

    def test_no_resource_below_l14(self):
        spec = {
            "id": "z", "class": "c_barbarian", "level": 10,
            "subclass": "sc_path_of_the_zealot",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                         "damage_type": "slashing", "attack_ability": "str",
                         "reach_ft": 5}],
        }
        r = derive_pc_resources(spec, _registry())
        self.assertIsNone(r.get("rage_of_the_gods_uses_remaining"))


class ActivationTest(unittest.TestCase):

    def test_activation_sets_flag_and_fly(self):
        z = _zealot(uses=1)
        st = _state([z])
        activated = try_activate_rage_of_the_gods(z, st)
        self.assertTrue(activated)
        self.assertTrue(z.rage_of_the_gods_active)
        self.assertEqual(z.speed.get("fly"), 30)

    def test_activation_decrements_use(self):
        z = _zealot(uses=1)
        st = _state([z])
        try_activate_rage_of_the_gods(z, st)
        self.assertEqual(z.resources["rage_of_the_gods_uses_remaining"], 0)

    def test_no_activation_when_no_uses(self):
        z = _zealot(uses=0)
        st = _state([z])
        activated = try_activate_rage_of_the_gods(z, st)
        self.assertFalse(activated)
        self.assertFalse(z.rage_of_the_gods_active)

    def test_no_activation_without_feature(self):
        z = _zealot(uses=1)
        z.template["features_known"] = []
        st = _state([z])
        activated = try_activate_rage_of_the_gods(z, st)
        self.assertFalse(activated)

    def test_event_logged(self):
        z = _zealot(uses=1)
        st = _state([z])
        try_activate_rage_of_the_gods(z, st)
        events = [e.get("event") for e in st.event_log]
        self.assertIn("rage_of_the_gods_activated", events)


class DeactivationTest(unittest.TestCase):

    def test_deactivation_clears_flag_and_fly(self):
        z = _zealot(uses=1)
        z.speed["fly"] = 30
        z.rage_of_the_gods_active = True
        z._rage_of_the_gods_prior_fly = None
        st = _state([z])
        deactivate_rage_of_the_gods(z, st)
        self.assertFalse(z.rage_of_the_gods_active)
        self.assertNotIn("fly", z.speed)

    def test_deactivation_idempotent(self):
        z = _zealot(uses=1)
        z.rage_of_the_gods_active = False
        st = _state([z])
        deactivate_rage_of_the_gods(z, st)  # should not raise
        self.assertFalse(z.rage_of_the_gods_active)


class ResistanceTest(unittest.TestCase):

    def test_resists_necrotic_when_active(self):
        z = _zealot()
        z.rage_of_the_gods_active = True
        self.assertTrue(applies_resistance(z, "necrotic"))

    def test_resists_psychic_when_active(self):
        z = _zealot()
        z.rage_of_the_gods_active = True
        self.assertTrue(applies_resistance(z, "psychic"))

    def test_resists_radiant_when_active(self):
        z = _zealot()
        z.rage_of_the_gods_active = True
        self.assertTrue(applies_resistance(z, "radiant"))

    def test_no_resistance_to_fire(self):
        z = _zealot()
        z.rage_of_the_gods_active = True
        self.assertFalse(applies_resistance(z, "fire"))

    def test_no_resistance_when_inactive(self):
        z = _zealot()
        z.rage_of_the_gods_active = False
        self.assertFalse(applies_resistance(z, "necrotic"))


class RevivificationTest(unittest.TestCase):

    def test_restores_ally_to_barbarian_level(self):
        z = _zealot(level=14)
        a = _ally()
        a.hp_current = 0
        st = _state([z, a])
        execute_revivification(z, a, st)
        self.assertEqual(a.hp_current, 14)  # barbarian level

    def test_spends_rage_use(self):
        z = _zealot(level=14)
        z.resources["rage_uses_remaining"] = 3
        a = _ally()
        st = _state([z, a])
        execute_revivification(z, a, st)
        self.assertEqual(z.resources["rage_uses_remaining"], 2)

    def test_uses_reaction_slot(self):
        z = _zealot(level=14)
        a = _ally()
        st = _state([z, a])
        execute_revivification(z, a, st)
        self.assertTrue(z.actions_used_this_turn["reaction"])

    def test_clears_dying_state(self):
        z = _zealot(level=14)
        a = _ally()
        a.hp_current = 0
        a.is_dying = True
        a.death_save_successes = 1
        a.death_save_failures = 2
        st = _state([z, a])
        execute_revivification(z, a, st)
        self.assertFalse(a.is_dying)
        self.assertEqual(a.death_save_successes, 0)
        self.assertEqual(a.death_save_failures, 0)

    def test_event_logged(self):
        z = _zealot(level=14)
        a = _ally()
        st = _state([z, a])
        execute_revivification(z, a, st)
        events = [e.get("event") for e in st.event_log]
        self.assertIn("revivification_used", events)


class LongRestRefreshTest(unittest.TestCase):

    def test_long_rest_restores_use(self):
        from engine.core.rest import _refresh_generic_uses_to_max
        z = _zealot(uses=0)
        z.resources["rage_of_the_gods_uses_max"] = 1
        result = _refresh_generic_uses_to_max(
            z, "rage_of_the_gods_uses_remaining", "rage_of_the_gods_uses_max")
        self.assertEqual(result, {"new_total": 1})

    def test_noop_when_already_full(self):
        from engine.core.rest import _refresh_generic_uses_to_max
        z = _zealot(uses=1)
        result = _refresh_generic_uses_to_max(
            z, "rage_of_the_gods_uses_remaining", "rage_of_the_gods_uses_max")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
