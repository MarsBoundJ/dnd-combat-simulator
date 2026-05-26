"""Extra Attack auto-generation tests (PR #39).

Layers:
  1. _extra_attack_count: maps features_known → attack count (1/2/3/4)
  2. _build_extra_attack_action: shape (multiattack, count, sub_actions
     referencing first weapon repeated)
  3. _build_feature_actions: emits Extra Attack only at L5+, only for
     Fighter, only when weapons exist
  4. build_pc_template integration: L4 fighter has no multiattack, L5+
     does; count scales L5→L11→L20
  5. Behavioral end-to-end: L5 fighter via pc: schema does TWO
     attack_roll events per turn vs one for L4

Run via:
    python -m unittest tests.test_extra_attack
"""
from __future__ import annotations

import unittest

from engine.pc_schema import (
    build_pc_template, _build_feature_actions, _extra_attack_count,
    _build_extra_attack_action,
)


# ============================================================================
# Mock registry — full fighter level table for L1 → L20 testing
# ============================================================================

class _MockRegistry:
    def __init__(self, classes):
        self._classes = classes
    def get(self, etype, eid):
        if etype != "class":
            raise KeyError(etype)
        if eid not in self._classes:
            raise KeyError(eid)
        return self._classes[eid]


def _fighter_class_def() -> dict:
    """Minimal fighter class def with the Extra Attack progression."""
    return {
        "id": "c_fighter", "name": "Fighter",
        "core_traits": {"hit_die": "d10",
                         "save_proficiencies": ["strength", "constitution"]},
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": ["f_fighting_style", "f_second_wind"],
              "class_resources": {"second_wind_uses": 2}},
            {"level": 5, "proficiency_bonus": 3,
              "features": ["f_extra_attack"],
              "class_resources": {"second_wind_uses": 3}},
            {"level": 11, "proficiency_bonus": 4,
              "features": ["f_two_extra_attacks"],
              "class_resources": {"second_wind_uses": 4}},
            {"level": 20, "proficiency_bonus": 6,
              "features": ["f_three_extra_attacks"],
              "class_resources": {"second_wind_uses": 4}},
        ],
    }


def _registry():
    return _MockRegistry({"c_fighter": _fighter_class_def()})


def _fighter_spec(level: int) -> dict:
    return {
        "class": "c_fighter", "level": level,
        "ability_scores": {"str": 16, "dex": 12, "con": 14,
                            "int": 10, "wis": 10, "cha": 10},
        "weapons": [{
            "id": "a_longsword", "name": "Longsword",
            "attack_ability": "str", "damage_dice": "1d8",
            "damage_type": "slashing", "reach_ft": 5,
        }],
    }


# ============================================================================
# Count derivation
# ============================================================================

class ExtraAttackCountTest(unittest.TestCase):

    def test_none_at_L1(self) -> None:
        self.assertEqual(
            _extra_attack_count({"f_fighting_style"}), 1)

    def test_two_with_extra_attack(self) -> None:
        self.assertEqual(
            _extra_attack_count({"f_extra_attack"}), 2)

    def test_three_with_two_extra_attacks(self) -> None:
        self.assertEqual(
            _extra_attack_count({"f_extra_attack",
                                   "f_two_extra_attacks"}), 3)

    def test_four_with_three_extra_attacks(self) -> None:
        self.assertEqual(
            _extra_attack_count({"f_extra_attack",
                                   "f_two_extra_attacks",
                                   "f_three_extra_attacks"}), 4)

    def test_higher_feature_supersedes_lower(self) -> None:
        """L20 fighter has all three features in features_known
        (accumulated across levels). Total count = 4, not 2+3+4."""
        features = {"f_extra_attack",
                     "f_two_extra_attacks",
                     "f_three_extra_attacks"}
        self.assertEqual(_extra_attack_count(features), 4)


# ============================================================================
# Action shape
# ============================================================================

class BuildExtraAttackActionTest(unittest.TestCase):

    def test_shape_count_2(self) -> None:
        weapons = [{"id": "a_longsword", "name": "Longsword",
                     "type": "weapon_attack", "pipeline": []}]
        action = _build_extra_attack_action(2, weapons)
        self.assertEqual(action["type"], "multiattack")
        self.assertEqual(action["count"], 2)
        self.assertEqual(action["sub_actions"],
                          ["a_longsword", "a_longsword"])
        self.assertEqual(action["id"], "a_extra_attack")

    def test_shape_count_4(self) -> None:
        weapons = [{"id": "a_greatsword", "name": "Greatsword",
                     "type": "weapon_attack", "pipeline": []}]
        action = _build_extra_attack_action(4, weapons)
        self.assertEqual(action["count"], 4)
        self.assertEqual(action["sub_actions"], ["a_greatsword"] * 4)

    def test_uses_first_weapon_when_multiple(self) -> None:
        weapons = [
            {"id": "a_first", "name": "First", "type": "weapon_attack",
              "pipeline": []},
            {"id": "a_second", "name": "Second", "type": "weapon_attack",
              "pipeline": []},
        ]
        action = _build_extra_attack_action(2, weapons)
        self.assertEqual(action["sub_actions"], ["a_first", "a_first"])


# ============================================================================
# _build_feature_actions: gating
# ============================================================================

class BuildFeatureActionsExtraAttackTest(unittest.TestCase):

    def test_no_extra_attack_below_L5(self) -> None:
        weapons = [{"id": "a_w", "name": "W", "type": "weapon_attack",
                     "pipeline": []}]
        actions = _build_feature_actions(
            {"f_fighting_style"}, 1, "c_fighter", weapon_actions=weapons)
        ma = [a for a in actions if a.get("type") == "multiattack"]
        self.assertEqual(ma, [])

    def test_emits_at_L5_for_fighter(self) -> None:
        weapons = [{"id": "a_w", "name": "W", "type": "weapon_attack",
                     "pipeline": []}]
        actions = _build_feature_actions(
            {"f_extra_attack"}, 5, "c_fighter", weapon_actions=weapons)
        ma = [a for a in actions if a.get("type") == "multiattack"]
        self.assertEqual(len(ma), 1)
        self.assertEqual(ma[0]["count"], 2)

    def test_no_emit_for_non_fighter(self) -> None:
        """Defensive: Extra Attack is currently Fighter-only in this
        impl. Other classes that have similar mechanics (Barbarian,
        Paladin, etc.) get added when those classes land."""
        weapons = [{"id": "a_w", "name": "W", "type": "weapon_attack",
                     "pipeline": []}]
        actions = _build_feature_actions(
            {"f_extra_attack"}, 5, "c_wizard", weapon_actions=weapons)
        ma = [a for a in actions if a.get("type") == "multiattack"]
        self.assertEqual(ma, [])

    def test_no_emit_when_no_weapons(self) -> None:
        """Fighter with no weapons (unusual but legal): skip
        multiattack generation. No weapons → nothing to reference."""
        actions = _build_feature_actions(
            {"f_extra_attack"}, 5, "c_fighter", weapon_actions=[])
        ma = [a for a in actions if a.get("type") == "multiattack"]
        self.assertEqual(ma, [])


# ============================================================================
# build_pc_template integration
# ============================================================================

class BuildPCTemplateIntegrationTest(unittest.TestCase):

    def test_L4_fighter_has_no_multiattack(self) -> None:
        template = build_pc_template(_fighter_spec(4), _registry())
        ma = [a for a in template["actions"]
              if a.get("type") == "multiattack"]
        self.assertEqual(ma, [])

    def test_L5_fighter_has_multiattack_count_2(self) -> None:
        template = build_pc_template(_fighter_spec(5), _registry())
        ma = [a for a in template["actions"]
              if a.get("type") == "multiattack"]
        self.assertEqual(len(ma), 1)
        self.assertEqual(ma[0]["count"], 2)
        self.assertEqual(ma[0]["sub_actions"],
                          ["a_longsword", "a_longsword"])

    def test_L11_fighter_has_multiattack_count_3(self) -> None:
        template = build_pc_template(_fighter_spec(11), _registry())
        ma = [a for a in template["actions"]
              if a.get("type") == "multiattack"]
        self.assertEqual(ma[0]["count"], 3)

    def test_L20_fighter_has_multiattack_count_4(self) -> None:
        template = build_pc_template(_fighter_spec(20), _registry())
        ma = [a for a in template["actions"]
              if a.get("type") == "multiattack"]
        self.assertEqual(ma[0]["count"], 4)

    def test_L5_fighter_keeps_single_attack_action(self) -> None:
        """Multiattack is ADDED; the single-attack weapon action is
        still in the list (the candidate generator may still pick it
        if multiattack scores lower for some reason)."""
        template = build_pc_template(_fighter_spec(5), _registry())
        weapon_attacks = [a for a in template["actions"]
                           if a.get("type") == "weapon_attack"]
        self.assertEqual(len(weapon_attacks), 1)
        self.assertEqual(weapon_attacks[0]["id"], "a_longsword")


# ============================================================================
# Behavioral end-to-end: L5 fighter does 2 attacks per turn
# ============================================================================

class ExtraAttackBehavioralTest(unittest.TestCase):

    def test_L5_fighter_two_attack_rolls_per_turn(self) -> None:
        """L5 Fighter via the pc: schema should pick multiattack each
        turn and produce 2 attack_roll events per main slot."""
        from engine.cli import _build_actor
        from engine.core.state import Encounter
        from engine.core.runner import EncounterRunner
        import engine.primitives as primitives_module

        fighter_spec = {
            "instance_id": "fighter",
            "side": "pc",
            "position": [0, 0],
            "pc": {
                "class": "c_fighter", "level": 5,
                "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                     "int": 10, "wis": 10, "cha": 10},
                "weapons": [{"id": "a_longsword", "name": "Longsword",
                              "attack_ability": "str",
                              "damage_dice": "1d8",
                              "damage_type": "slashing", "reach_ft": 5}],
                "behavior_profile": {"presets": {"retreat": "ftd"}},
            },
        }
        ogre_template = {
            "id": "tpl_ogre", "name": "Ogre",
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con", "int", "wis", "cha")},
            "cr": {"value": 2, "xp": 450, "proficiency_bonus": 2},
            "combat": {
                "armor_class": 14,
                "hit_points": {"average": 80, "dice": "8d10",
                                 "con_contribution": 24},
                "speed": {"walk": 30},
                "initiative": {"modifier": -5, "score": 0},
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
                      "hp_current": 80, "template": ogre_template}

        fighter = _build_actor(fighter_spec, _registry())
        ogre = _build_actor(ogre_spec, _registry())
        enc = Encounter(id="t", actors=[fighter, ogre])
        runner = EncounterRunner.new(enc, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Find round 1 fighter attack rolls — there should be 2
        round1_events = []
        for e in state.event_log:
            if (e.get("event") == "turn_start"
                    and e.get("round") == 2):
                break
            round1_events.append(e)
        fighter_attacks_r1 = [
            e for e in round1_events
            if e.get("event") == "attack_roll"
            and e.get("actor") == "fighter"
        ]
        self.assertEqual(len(fighter_attacks_r1), 2,
                          f"Expected 2 attack_rolls (Extra Attack at L5), "
                          f"got {len(fighter_attacks_r1)}")


if __name__ == "__main__":
    unittest.main()
