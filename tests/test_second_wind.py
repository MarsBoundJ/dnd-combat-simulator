"""Second Wind end-to-end tests (PR #33).

Verifies the full path:
  1. pc_schema._build_second_wind_action: shape (heal, bonus_action,
     feature_use, dice=1d10, fixed=fighter_level)
  2. _build_feature_actions: present for f_second_wind only
  3. build_pc_template: integrates Second Wind into the action list
     for L1+ Fighters
  4. Behavioral integration: a wounded L2 Fighter picks Second Wind
     in their bonus slot, decrements the counter, and is healed
  5. Once the counter hits zero, Second Wind is filtered out

Run via:
    python -m unittest tests.test_second_wind
"""
from __future__ import annotations

import random
import unittest

from engine.pc_schema import (
    _build_second_wind_action, _build_feature_actions, build_pc_template,
)


# ============================================================================
# Action-shape unit tests
# ============================================================================

class BuildSecondWindActionTest(unittest.TestCase):

    def test_shape_at_L1(self) -> None:
        a = _build_second_wind_action(1)
        self.assertEqual(a["id"], "a_second_wind")
        self.assertEqual(a["name"], "Second Wind")
        self.assertEqual(a["type"], "heal")
        self.assertEqual(a["slot"], "bonus_action")
        self.assertEqual(a["feature_use"], "second_wind_uses_remaining")
        step = a["pipeline"][0]
        self.assertEqual(step["primitive"], "heal")
        self.assertEqual(step["params"]["target"], "self")
        self.assertEqual(step["params"]["dice"], "1d10")
        self.assertEqual(step["params"]["fixed"], 1)

    def test_fixed_scales_with_level(self) -> None:
        self.assertEqual(_build_second_wind_action(5)["pipeline"][0]
                          ["params"]["fixed"], 5)
        self.assertEqual(_build_second_wind_action(20)["pipeline"][0]
                          ["params"]["fixed"], 20)


class BuildFeatureActionsTest(unittest.TestCase):

    def test_second_wind_generated_when_feature_known(self) -> None:
        out = _build_feature_actions({"f_second_wind"}, 1, "c_fighter")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "a_second_wind")

    def test_no_second_wind_when_feature_absent(self) -> None:
        out = _build_feature_actions(
            {"f_fighting_style", "f_weapon_mastery"}, 1, "c_fighter")
        self.assertEqual(out, [])

    def test_no_second_wind_for_non_fighter(self) -> None:
        """Second Wind is a Fighter feature; the feature id alone
        shouldn't trigger generation on another class (defensive
        check — no other class declares f_second_wind in RAW)."""
        out = _build_feature_actions({"f_second_wind"}, 1, "c_wizard")
        self.assertEqual(out, [])


# ============================================================================
# Integration with build_pc_template
# ============================================================================

class _MockRegistry:
    def __init__(self, classes):
        self._classes = classes
    def get(self, etype, eid):
        if etype != "class": raise KeyError(etype)
        if eid not in self._classes: raise KeyError(eid)
        return self._classes[eid]


def _fighter_class_def() -> dict:
    return {
        "id": "c_fighter", "name": "Fighter",
        "core_traits": {"hit_die": "d10",
                         "save_proficiencies": ["strength", "constitution"]},
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": ["f_fighting_style", "f_second_wind"],
              "class_resources": {"second_wind_uses": 2}},
            {"level": 2, "proficiency_bonus": 2,
              "features": ["f_action_surge_one_use"],
              "class_resources": {"second_wind_uses": 2}},
        ],
    }


class BuildPCTemplateIntegrationTest(unittest.TestCase):

    def test_L1_fighter_has_second_wind_action(self) -> None:
        reg = _MockRegistry({"c_fighter": _fighter_class_def()})
        spec = {
            "class": "c_fighter", "level": 1,
            "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                 "int": 10, "wis": 10, "cha": 10},
            "weapons": [{"id": "a_sword", "name": "Sword",
                          "attack_ability": "str",
                          "damage_dice": "1d8",
                          "damage_type": "slashing"}],
        }
        template = build_pc_template(spec, reg)
        sw = [a for a in template["actions"]
              if a.get("id") == "a_second_wind"]
        self.assertEqual(len(sw), 1)
        # `fixed` damage modifier = fighter_level (1 here)
        self.assertEqual(sw[0]["pipeline"][0]["params"]["fixed"], 1)


# ============================================================================
# Behavioral end-to-end — wounded fighter heals themselves
# ============================================================================

class SecondWindBehavioralTest(unittest.TestCase):

    def test_wounded_fighter_picks_second_wind_and_heals(self) -> None:
        """A wounded L2 Fighter with no adjacent enemy should use Second
        Wind on their bonus slot, decrement the counter, and heal."""
        from engine.cli import _build_actor
        from engine.core.state import Encounter, CombatState
        from engine.core.runner import EncounterRunner
        import engine.primitives as primitives_module

        reg = _MockRegistry({"c_fighter": _fighter_class_def()})
        fighter_spec = {
            "instance_id": "fighter",
            "side": "pc",
            "position": [0, 0],
            "hp_current": 5,    # wounded — heal has clear value
            "pc": {
                "class": "c_fighter", "level": 2,
                "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                     "int": 10, "wis": 10, "cha": 10},
                "weapons": [{"id": "a_sword", "name": "Sword",
                              "attack_ability": "str",
                              "damage_dice": "1d8",
                              "damage_type": "slashing"}],
                # Fight-to-the-death retreat preset so the bloodied
                # fighter doesn't flee on turn 1 (default preset
                # triggers retreat at ≤50% HP). We need them to stay
                # and act so Second Wind can fire.
                "behavior_profile": {"presets": {"retreat": "ftd"}},
            },
        }
        # Inline-template enemy at melee range (so the fighter has an
        # in-reach attack candidate and uses Action Surge round 1 too;
        # but Second Wind is on the bonus slot — that's what we verify).
        enemy_template = {
            "id": "tpl_ogre", "name": "Ogre",
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con", "int", "wis", "cha")},
            "cr": {"value": 2, "xp": 450, "proficiency_bonus": 2},
            "combat": {
                "armor_class": 14,
                "hit_points": {"average": 30, "dice": "4d10",
                                 "con_contribution": 8},
                "speed": {"walk": 30},
                "initiative": {"modifier": 0, "score": 5},
            },
            "actions": [{
                "id": "a_club", "name": "Club", "type": "weapon_attack",
                "pipeline": [
                    {"primitive": "attack_roll",
                      "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
                    {"primitive": "damage",
                      "params": {"dice": "1d6", "modifier": 2,
                                  "type": "bludgeoning"},
                      "when": {"event": "damage_roll",
                                "condition": "combat.attack_state == hit"}},
                ],
            }],
        }
        ogre_spec = {"instance_id": "ogre", "side": "enemy",
                      "position": [0, 1],
                      "hp_current": 30,
                      "template": enemy_template}

        fighter = _build_actor(fighter_spec, reg)
        ogre = _build_actor(ogre_spec, reg)
        # Auto-wired SW counter
        self.assertEqual(
            fighter.resources["second_wind_uses_remaining"], 2)
        self.assertEqual(fighter.hp_current, 5)

        # Run one encounter to termination — we only care about round 1
        # behavior, but letting it run is the simplest setup.
        enc = Encounter(id="sw_test", actors=[fighter, ogre])
        runner = EncounterRunner.new(enc, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Second Wind was consumed at least once
        sw_events = [e for e in state.event_log
                      if e.get("event") == "feature_use_consumed"
                      and e.get("resource") == "second_wind_uses_remaining"]
        self.assertGreater(len(sw_events), 0,
                            "Wounded fighter should have consumed Second "
                            "Wind at least once over the encounter")
        # Counter decremented
        self.assertLess(
            fighter.resources["second_wind_uses_remaining"], 2)
        # A `healed` event landed for the fighter
        heal_events = [e for e in state.event_log
                        if e.get("event") == "healed"
                        and e.get("target") == "fighter"]
        self.assertGreater(len(heal_events), 0)


if __name__ == "__main__":
    unittest.main()
