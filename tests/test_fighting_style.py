"""Fighting Style tests (PR #38).

Layers:
  1. _validate_fighting_style accepts known ids + rejects unknown
  2. Defense (+1 AC) applies with armor block, NOT without
  3. Dueling (+2 damage) applies to one-handed melee, NOT to ranged
     or two-handed
  4. Archery (+2 attack) applies to ranged, NOT to melee
  5. No style → no modifiers (regression-safe)
  6. End-to-end via cli._build_actor + a registry mock

Run via:
    python -m unittest tests.test_fighting_style
"""
from __future__ import annotations

import unittest

from engine.pc_schema import (
    build_pc_template, _validate_fighting_style, _KNOWN_FIGHTING_STYLES,
)


# ============================================================================
# Mock registry
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
    return {
        "id": "c_fighter", "name": "Fighter",
        "core_traits": {"hit_die": "d10",
                         "save_proficiencies": ["strength", "constitution"]},
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": ["f_fighting_style", "f_second_wind"],
              "class_resources": {"second_wind_uses": 2}},
        ],
    }


def _registry():
    return _MockRegistry({"c_fighter": _fighter_class_def()})


def _base_spec(fighting_style: str | None = None,
                  armor: dict | None = None,
                  weapons: list[dict] | None = None,
                  level: int = 1) -> dict:
    """A minimal L1 Fighter spec, easy to vary per-test."""
    spec = {
        "class": "c_fighter", "level": level,
        "ability_scores": {"str": 16, "dex": 14, "con": 14,
                            "int": 10, "wis": 10, "cha": 10},
        "weapons": weapons if weapons is not None else [{
            "id": "a_longsword", "name": "Longsword",
            "attack_ability": "str", "damage_dice": "1d8",
            "damage_type": "slashing", "reach_ft": 5,
        }],
    }
    if fighting_style is not None:
        spec["fighting_style"] = fighting_style
    if armor is not None:
        spec["armor"] = armor
    return spec


# ============================================================================
# Validation
# ============================================================================

class ValidateFightingStyleTest(unittest.TestCase):

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_validate_fighting_style(None))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_validate_fighting_style(""))

    def test_known_styles_pass(self) -> None:
        for s in _KNOWN_FIGHTING_STYLES:
            self.assertEqual(_validate_fighting_style(s), s)

    def test_uppercase_normalized(self) -> None:
        self.assertEqual(_validate_fighting_style("DEFENSE"), "defense")
        self.assertEqual(_validate_fighting_style("Dueling"), "dueling")

    def test_unknown_style_raises(self) -> None:
        # PR #49 + PR #53 + PR #63: great_weapon_fighting +
        # two_weapon_fighting + blind_fighting are now all known
        # styles. Use a genuinely-unknown id for the rejection check.
        with self.assertRaises(ValueError):
            _validate_fighting_style("interception")
        with self.assertRaises(ValueError):
            _validate_fighting_style("does_not_exist")


# ============================================================================
# Defense — +1 AC when armor present
# ============================================================================

class DefenseFightingStyleTest(unittest.TestCase):

    def test_adds_one_AC_with_armor(self) -> None:
        spec = _base_spec(fighting_style="defense",
                           armor={"base_ac": 16, "max_dex_bonus": 2})
        template = build_pc_template(spec, _registry())
        # Base AC = 16 + min(DEX +2, 2) = 18. Defense adds 1 → 19.
        self.assertEqual(template["combat"]["armor_class"], 19)

    def test_no_armor_means_no_bonus(self) -> None:
        spec = _base_spec(fighting_style="defense")    # no armor block
        template = build_pc_template(spec, _registry())
        # Unarmored: 10 + DEX +2 = 12. Defense does NOT apply.
        self.assertEqual(template["combat"]["armor_class"], 12)

    def test_no_style_means_no_bonus(self) -> None:
        spec = _base_spec(armor={"base_ac": 16, "max_dex_bonus": 2})
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["combat"]["armor_class"], 18)

    def test_dueling_does_not_affect_AC(self) -> None:
        spec = _base_spec(fighting_style="dueling",
                           armor={"base_ac": 16, "max_dex_bonus": 2})
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["combat"]["armor_class"], 18)


# ============================================================================
# Dueling — +2 damage on one-handed melee
# ============================================================================

class DuelingFightingStyleTest(unittest.TestCase):

    def test_one_handed_melee_gets_plus_two_damage(self) -> None:
        spec = _base_spec(fighting_style="dueling")
        template = build_pc_template(spec, _registry())
        # Longsword: 1d8 + STR +3 (mod). Dueling adds +2 → damage mod = 5
        damage_step = template["actions"][0]["pipeline"][1]
        self.assertEqual(damage_step["params"]["modifier"], 5)

    def test_two_handed_melee_does_NOT_get_bonus(self) -> None:
        spec = _base_spec(fighting_style="dueling", weapons=[{
            "id": "a_greatsword", "name": "Greatsword",
            "attack_ability": "str", "damage_dice": "2d6",
            "damage_type": "slashing", "reach_ft": 5,
            "two_handed": True,
        }])
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        # Damage mod = STR +3 only, no Dueling bonus
        self.assertEqual(damage_step["params"]["modifier"], 3)

    def test_ranged_does_NOT_get_bonus(self) -> None:
        spec = _base_spec(fighting_style="dueling", weapons=[{
            "id": "a_longbow", "name": "Longbow",
            "attack_ability": "dex", "damage_dice": "1d8",
            "damage_type": "piercing", "range_ft": 150,
        }])
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        # Damage mod = DEX +2 only, no Dueling
        self.assertEqual(damage_step["params"]["modifier"], 2)

    def test_no_style_no_damage_bonus(self) -> None:
        spec = _base_spec()
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        self.assertEqual(damage_step["params"]["modifier"], 3)


# ============================================================================
# Archery — +2 attack on ranged
# ============================================================================

class ArcheryFightingStyleTest(unittest.TestCase):

    def test_ranged_weapon_gets_plus_two_attack(self) -> None:
        spec = _base_spec(fighting_style="archery", weapons=[{
            "id": "a_longbow", "name": "Longbow",
            "attack_ability": "dex", "damage_dice": "1d8",
            "damage_type": "piercing", "range_ft": 150,
        }])
        template = build_pc_template(spec, _registry())
        attack_step = template["actions"][0]["pipeline"][0]
        # Attack bonus = DEX +2 + PB +2 = +4. Archery adds +2 → +6.
        self.assertEqual(attack_step["params"]["bonus"], 6)

    def test_melee_does_NOT_get_bonus(self) -> None:
        spec = _base_spec(fighting_style="archery")    # default longsword
        template = build_pc_template(spec, _registry())
        attack_step = template["actions"][0]["pipeline"][0]
        # Attack bonus = STR +3 + PB +2 = +5 only, no Archery
        self.assertEqual(attack_step["params"]["bonus"], 5)

    def test_archery_does_not_affect_damage(self) -> None:
        spec = _base_spec(fighting_style="archery", weapons=[{
            "id": "a_longbow", "name": "Longbow",
            "attack_ability": "dex", "damage_dice": "1d8",
            "damage_type": "piercing", "range_ft": 150,
        }])
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        # Damage mod = DEX +2 only (Archery is attack-only)
        self.assertEqual(damage_step["params"]["modifier"], 2)


# ============================================================================
# Template tagging
# ============================================================================

class TemplateTaggingTest(unittest.TestCase):

    def test_chosen_style_recorded_on_template(self) -> None:
        spec = _base_spec(fighting_style="defense",
                           armor={"base_ac": 16, "max_dex_bonus": 2})
        template = build_pc_template(spec, _registry())
        self.assertEqual(
            template["derived_from_pc_schema"]["fighting_style"],
            "defense")

    def test_no_style_recorded_as_none(self) -> None:
        spec = _base_spec()
        template = build_pc_template(spec, _registry())
        self.assertIsNone(
            template["derived_from_pc_schema"]["fighting_style"])


# ============================================================================
# Unknown style rejection at build time
# ============================================================================

class UnknownStyleRejectionTest(unittest.TestCase):

    def test_build_template_rejects_unknown_style(self) -> None:
        spec = _base_spec(fighting_style="interception")
        with self.assertRaises(ValueError):
            build_pc_template(spec, _registry())


if __name__ == "__main__":
    unittest.main()
