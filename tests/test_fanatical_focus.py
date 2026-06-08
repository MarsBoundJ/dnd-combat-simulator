"""Fanatical Focus tests (Path of the Zealot, Barbarian L6).

Once per active Rage, when the Zealot fails a saving throw, they may
reroll it with a bonus equal to their Rage Damage bonus.

Layers:
  1. Resource seeding at L6 (PC schema).
  2. Primitive: reroll fires on rage + feature + failed save.
  3. Once-per-Rage: second failed save in same Rage doesn't reroll.
  4. Resets on new Rage entry.
  5. No-op when not raging or lacking the feature.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import derive_pc_resources
from engine.core.fanatical_focus import (
    has_fanatical_focus,
    try_fanatical_focus_reroll,
    reset_for_new_rage,
)

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _zealot(*, hp=50, hp_max=100, level=6, raging=True, rage_dmg=2):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    a = Actor(id="z", name="z",
              template={"id": "t_z", "name": "z", "abilities": ab,
                        "cr": {"proficiency_bonus": 2}, "actions": [],
                        "features_known": ["f_fanatical_focus"],
                        "levels": {"barbarian": level}},
              side="pc", hp_current=hp, hp_max=hp_max, ac=12,
              position=(0, 0), speed={"walk": 30}, abilities=ab)
    a.rage_active = raging
    a.rage_damage_bonus = rage_dmg
    a._fanatical_focus_used_this_rage = False
    return a


def _plain_actor():
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    a = Actor(id="p", name="p",
              template={"id": "t_p", "name": "p", "abilities": ab,
                        "cr": {"proficiency_bonus": 2}, "actions": [],
                        "features_known": []},
              side="pc", hp_current=50, hp_max=100, ac=12,
              position=(0, 0), speed={"walk": 30}, abilities=ab)
    a.rage_active = False
    a.rage_damage_bonus = 0
    return a


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [x.id for x in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class ResourceSeedingTest(unittest.TestCase):

    def _resources(self, level):
        spec = {
            "id": "z", "class": "c_barbarian", "level": level,
            "subclass": "sc_path_of_the_zealot",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                         "damage_type": "slashing", "attack_ability": "str",
                         "reach_ft": 5}],
        }
        return derive_pc_resources(spec, _registry())

    def test_no_resource_below_l6(self):
        r = self._resources(3)
        # Fanatical Focus is a passive — no explicit resource counter.
        # (It uses an actor attribute flag, not a resource key.)
        # The test simply verifies the level-3 Zealot spec doesn't error.
        self.assertIsNotNone(r)

    def test_has_feature_at_l6(self):
        from engine.pc_schema import build_pc_template
        spec = {
            "id": "z", "class": "c_barbarian", "level": 6,
            "subclass": "sc_path_of_the_zealot",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                         "damage_type": "slashing", "attack_ability": "str",
                         "reach_ft": 5}],
        }
        tmpl = build_pc_template(spec, _registry())
        self.assertIn("f_fanatical_focus",
                      tmpl.get("features_known", []))


class FanaticalFocusPassiveTest(unittest.TestCase):

    def setUp(self):
        self.rng = random.Random(42)

    def _state(self, actor):
        return _state([actor])

    def test_reroll_fires_on_raging_zealot_fail(self):
        z = _zealot(raging=True, rage_dmg=2)
        st = self._state(z)
        d20, total, outcome = try_fanatical_focus_reroll(
            z, "wisdom", dc=15, rng=self.rng, state=st)
        self.assertIsNotNone(d20)
        self.assertIn(outcome, ("success", "fail"))
        self.assertTrue(z._fanatical_focus_used_this_rage)

    def test_once_per_rage(self):
        z = _zealot(raging=True, rage_dmg=2)
        z._fanatical_focus_used_this_rage = True
        st = self._state(z)
        d20, total, outcome = try_fanatical_focus_reroll(
            z, "wisdom", dc=15, rng=self.rng, state=st)
        self.assertIsNone(d20)

    def test_no_reroll_when_not_raging(self):
        z = _zealot(raging=False)
        st = self._state(z)
        d20, _, _ = try_fanatical_focus_reroll(
            z, "wisdom", dc=15, rng=self.rng, state=st)
        self.assertIsNone(d20)

    def test_no_reroll_without_feature(self):
        z = _zealot(raging=True)
        z.template["features_known"] = []
        st = self._state(z)
        d20, _, _ = try_fanatical_focus_reroll(
            z, "wisdom", dc=15, rng=self.rng, state=st)
        self.assertIsNone(d20)

    def test_reset_for_new_rage(self):
        z = _zealot(raging=True)
        z._fanatical_focus_used_this_rage = True
        reset_for_new_rage(z)
        self.assertFalse(z._fanatical_focus_used_this_rage)

    def test_reroll_adds_rage_bonus(self):
        # Force a known RNG so we can verify the bonus lands in the total.
        rng = random.Random(999)
        z = _zealot(raging=True, rage_dmg=4)
        z.abilities = {"wis": {"score": 10, "save": 0},
                       **{k: {"score": 10, "save": 0}
                          for k in ("str", "dex", "con", "int", "cha")}}
        st = self._state(z)
        d20, total, _ = try_fanatical_focus_reroll(
            z, "wisdom", dc=20, rng=rng, state=st)
        self.assertIsNotNone(d20)
        # total = d20 + save_bonus(0) + rage_bonus(4)
        self.assertEqual(total, d20 + 4)

    def test_event_logged(self):
        z = _zealot(raging=True, rage_dmg=2)
        st = self._state(z)
        try_fanatical_focus_reroll(z, "strength", dc=10, rng=self.rng,
                                    state=st)
        events = [e["event"] for e in st.event_log]
        self.assertIn("fanatical_focus_reroll", events)


if __name__ == "__main__":
    unittest.main()
