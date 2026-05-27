"""Blind Fighting style tests (PR #63).

Layers:
  1. Style validation: blind_fighting in _KNOWN_FIGHTING_STYLES;
     _validate_fighting_style accepts it
  2. _build_pc_senses_block:
     - No fighting_style → senses has passive_perception only
     - blind_fighting → senses has special.blindsight=10
     - Other styles → no special block
  3. build_pc_template:
     - PC with blind_fighting: template.senses.special.blindsight=10
     - PC with another style: no special block
     - derived_from records the style
  4. End-to-end via cli._build_actor:
     - PC with blind_fighting → Actor.blindsight_range_ft=10
  5. Vision integration (PR #52 already covered the mechanic):
     - Blind Fighting actor pierces magical darkness within 10 ft
"""
from __future__ import annotations

import unittest

from engine.core.state import Actor, CombatState, Encounter
from engine.core.vision import can_actor_see
from engine.pc_schema import (
    _KNOWN_FIGHTING_STYLES, _build_pc_senses_block,
    _validate_fighting_style, build_pc_template,
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


def _fighter_class_def():
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


def _base_spec(fighting_style=None):
    spec = {
        "class": "c_fighter", "level": 1,
        "ability_scores": {"str": 16, "dex": 14, "con": 14,
                            "int": 10, "wis": 12, "cha": 10},
        "weapons": [{
            "id": "a_longsword", "name": "Longsword",
            "attack_ability": "str", "damage_dice": "1d8",
            "damage_type": "slashing", "reach_ft": 5,
        }],
    }
    if fighting_style:
        spec["fighting_style"] = fighting_style
    return spec


# ============================================================================
# Layer 1: validation
# ============================================================================

class BlindFightingValidationTest(unittest.TestCase):

    def test_in_known_set(self) -> None:
        self.assertIn("blind_fighting", _KNOWN_FIGHTING_STYLES)

    def test_validate_passes(self) -> None:
        self.assertEqual(_validate_fighting_style("blind_fighting"),
                            "blind_fighting")

    def test_normalize_case(self) -> None:
        self.assertEqual(_validate_fighting_style("Blind_Fighting"),
                            "blind_fighting")


# ============================================================================
# Layer 2: _build_pc_senses_block
# ============================================================================

class SensesBlockTest(unittest.TestCase):

    def _ability_scores(self, wis=12):
        return {
            "str": {"score": 10}, "dex": {"score": 10},
            "con": {"score": 10}, "int": {"score": 10},
            "wis": {"score": wis}, "cha": {"score": 10},
        }

    def test_no_style_no_special(self) -> None:
        block = _build_pc_senses_block(
            self._ability_scores(), skill_proficiencies=[],
            proficiency_bonus=2)
        self.assertIn("passive_perception", block)
        self.assertNotIn("special", block)

    def test_blind_fighting_adds_blindsight(self) -> None:
        block = _build_pc_senses_block(
            self._ability_scores(), skill_proficiencies=[],
            proficiency_bonus=2,
            fighting_style="blind_fighting")
        self.assertEqual(block["special"]["blindsight"], 10)

    def test_other_style_no_special(self) -> None:
        block = _build_pc_senses_block(
            self._ability_scores(), skill_proficiencies=[],
            proficiency_bonus=2,
            fighting_style="defense")
        self.assertNotIn("special", block)


# ============================================================================
# Layer 3: build_pc_template integration
# ============================================================================

class BuildTemplateBlindFightingTest(unittest.TestCase):

    def test_blind_fighting_template_has_blindsight(self) -> None:
        spec = _base_spec(fighting_style="blind_fighting")
        template = build_pc_template(spec, _registry())
        self.assertEqual(
            template["senses"]["special"]["blindsight"], 10)

    def test_blind_fighting_recorded_in_derived_from(self) -> None:
        spec = _base_spec(fighting_style="blind_fighting")
        template = build_pc_template(spec, _registry())
        self.assertEqual(
            template["derived_from_pc_schema"]["fighting_style"],
            "blind_fighting")

    def test_other_style_no_special_senses(self) -> None:
        spec = _base_spec(fighting_style="defense")
        template = build_pc_template(spec, _registry())
        self.assertNotIn("special", template["senses"])

    def test_no_style_no_special_senses(self) -> None:
        spec = _base_spec()
        template = build_pc_template(spec, _registry())
        self.assertNotIn("special", template["senses"])


# ============================================================================
# Layer 4: cli._build_actor loads blindsight_range_ft
# ============================================================================

class BuildActorBlindFightingTest(unittest.TestCase):

    def test_blind_fighting_loads_blindsight_10(self) -> None:
        from engine.cli import _build_actor
        spec = _base_spec(fighting_style="blind_fighting")
        actor = _build_actor({"instance_id": "fighter",
                                 "pc": spec},
                                registry=_registry())
        self.assertEqual(actor.blindsight_range_ft, 10)

    def test_other_style_no_blindsight(self) -> None:
        from engine.cli import _build_actor
        spec = _base_spec(fighting_style="defense")
        actor = _build_actor({"instance_id": "fighter",
                                 "pc": spec},
                                registry=_registry())
        self.assertEqual(actor.blindsight_range_ft, 0)


# ============================================================================
# Layer 5: vision integration end-to-end
# ============================================================================

class BlindFightingVisionIntegrationTest(unittest.TestCase):

    def test_blind_fighting_pierces_magical_darkness_in_range(self) -> None:
        # Build a Blind Fighting fighter via the schema
        from engine.cli import _build_actor
        spec = _base_spec(fighting_style="blind_fighting")
        bf_actor = _build_actor({"instance_id": "bf",
                                    "pc": spec,
                                    "position": [0, 0]},
                                   registry=_registry())
        # Make a target inside a magical darkness sphere within 10 ft
        target_template = {
            "id": "tpl_t", "name": "rogue",
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
            "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
            "actions": [],
        }
        target = Actor(id="t", name="rogue", template=target_template,
                        side="enemy", hp_current=20, hp_max=20, ac=14,
                        speed={"walk": 30}, position=(1, 0),
                        abilities=target_template["abilities"])
        enc = Encounter(id="t", actors=[bf_actor, target],
                          environment={
                              "magical_dark_zones": [
                                  {"shape": "sphere",
                                    "center": [1, 0],
                                    "radius_ft": 15},
                              ],
                          })
        state = CombatState(encounter=enc)
        state.turn_order = [bf_actor.id, target.id]
        state.round = 1
        # Distance = max(1, 0) = 1 square = 5 ft, within blindsight 10
        self.assertTrue(can_actor_see(bf_actor, target, state))


if __name__ == "__main__":
    unittest.main()
