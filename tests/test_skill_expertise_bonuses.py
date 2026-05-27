"""Skill expertise + magic-item bonuses tests (PR #62).

Layers:
  1. has_skill_expertise helper
  2. _skill_magic_bonus helper
  3. skill_modifier with expertise (2×PB) + bonuses (flat add)
     - Proficient + expertise → 2×PB
     - Proficient + no expertise → 1×PB (unchanged)
     - Not proficient + expertise (shouldn't happen, but tested
       to confirm helper returns just ability mod)
     - Magic bonus added regardless of proficiency
     - Magic bonus added on top of monster-listed total
  4. _validate_skill_expertise:
     - None → []
     - Unknown skill raises
     - Expertise without proficiency raises (RAW gate)
     - Normalized + deduped
     - Non-list raises
  5. _validate_skill_bonuses:
     - None → {}
     - Unknown skill raises
     - Non-int value raises
     - Non-dict raises
  6. pc_schema baking:
     - Template carries skill_expertise + skill_bonuses
     - Passive Perception includes expertise + magic bonus
"""
from __future__ import annotations

import unittest

from engine.core.skills import (
    _skill_magic_bonus, has_skill_expertise, has_skill_proficiency,
    skill_modifier,
)
from engine.core.state import Actor
from engine.pc_schema import (
    _compute_passive_perception, _validate_skill_bonuses,
    _validate_skill_expertise, build_pc_template,
)


# ============================================================================
# Mock registry helpers (mirrors test_perception_stealth + test_fighting_style)
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


def _rogue_class_def():
    return {
        "id": "c_rogue", "name": "Rogue",
        "core_traits": {"hit_die": "d8",
                         "save_proficiencies": ["dexterity", "intelligence"]},
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": [], "class_resources": {}},
        ],
    }


def _registry():
    return _MockRegistry({"c_rogue": _rogue_class_def()})


def _base_pc(skill_proficiencies=None, skill_expertise=None,
                skill_bonuses=None, wis_score=14, dex_score=16):
    spec = {
        "class": "c_rogue", "level": 1,
        "ability_scores": {"str": 10, "dex": dex_score, "con": 12,
                            "int": 12, "wis": wis_score, "cha": 10},
        "weapons": [{
            "id": "a_dagger", "name": "Dagger",
            "attack_ability": "dex", "damage_dice": "1d4",
            "damage_type": "piercing", "reach_ft": 5,
            "light": True,
        }],
    }
    if skill_proficiencies is not None:
        spec["skill_proficiencies"] = skill_proficiencies
    if skill_expertise is not None:
        spec["skill_expertise"] = skill_expertise
    if skill_bonuses is not None:
        spec["skill_bonuses"] = skill_bonuses
    return spec


def _make_actor(actor_id="a", *, dex_score=14, pb=3,
                  skill_proficiencies=None, skill_expertise=None,
                  skill_bonuses=None, skills_dict=None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": dex_score, "save": 0},
        "con": {"score": 10, "save": 0},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": pb},
        "actions": [],
    }
    if skill_proficiencies:
        template["skill_proficiencies"] = list(skill_proficiencies)
    if skill_expertise:
        template["skill_expertise"] = list(skill_expertise)
    if skill_bonuses:
        template["skill_bonuses"] = dict(skill_bonuses)
    if skills_dict:
        template["skills"] = dict(skills_dict)
    return Actor(id=actor_id, name=actor_id, template=template, side="pc",
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities)


# ============================================================================
# Layer 1: has_skill_expertise helper
# ============================================================================

class HasExpertiseTest(unittest.TestCase):

    def test_in_list(self) -> None:
        actor = _make_actor(skill_expertise=["stealth", "perception"])
        self.assertTrue(has_skill_expertise(actor, "stealth"))

    def test_not_in_list(self) -> None:
        actor = _make_actor(skill_expertise=["stealth"])
        self.assertFalse(has_skill_expertise(actor, "perception"))

    def test_empty(self) -> None:
        actor = _make_actor()
        self.assertFalse(has_skill_expertise(actor, "stealth"))

    def test_normalized(self) -> None:
        # case-insensitive match
        actor = _make_actor(skill_expertise=["Stealth"])
        self.assertTrue(has_skill_expertise(actor, "stealth"))


# ============================================================================
# Layer 2: _skill_magic_bonus helper
# ============================================================================

class SkillMagicBonusTest(unittest.TestCase):

    def test_returns_bonus(self) -> None:
        actor = _make_actor(skill_bonuses={"stealth": 5})
        self.assertEqual(_skill_magic_bonus(actor, "stealth"), 5)

    def test_no_bonus_returns_zero(self) -> None:
        actor = _make_actor()
        self.assertEqual(_skill_magic_bonus(actor, "stealth"), 0)

    def test_unrelated_skill_zero(self) -> None:
        actor = _make_actor(skill_bonuses={"stealth": 5})
        self.assertEqual(_skill_magic_bonus(actor, "perception"), 0)

    def test_normalized_match(self) -> None:
        actor = _make_actor(skill_bonuses={"Stealth": 5})
        self.assertEqual(_skill_magic_bonus(actor, "stealth"), 5)


# ============================================================================
# Layer 3: skill_modifier with expertise + bonuses
# ============================================================================

class SkillModifierExpertiseBonusTest(unittest.TestCase):

    def test_proficient_no_expertise_one_pb(self) -> None:
        # DEX 14 (+2), PB 3, proficient (no expertise) = 2 + 3 = 5
        actor = _make_actor(dex_score=14, pb=3,
                              skill_proficiencies=["stealth"])
        self.assertEqual(skill_modifier(actor, "stealth"), 5)

    def test_proficient_with_expertise_double_pb(self) -> None:
        # DEX 14 (+2), PB 3, expertise = 2 + 6 = 8
        actor = _make_actor(dex_score=14, pb=3,
                              skill_proficiencies=["stealth"],
                              skill_expertise=["stealth"])
        self.assertEqual(skill_modifier(actor, "stealth"), 8)

    def test_not_proficient_no_pb(self) -> None:
        # DEX 14 (+2), no prof = +2
        actor = _make_actor(dex_score=14, pb=3)
        self.assertEqual(skill_modifier(actor, "stealth"), 2)

    def test_magic_bonus_added_with_proficiency(self) -> None:
        # DEX 14 (+2), PB 3, proficient, +5 cloak = 2 + 3 + 5 = 10
        actor = _make_actor(dex_score=14, pb=3,
                              skill_proficiencies=["stealth"],
                              skill_bonuses={"stealth": 5})
        self.assertEqual(skill_modifier(actor, "stealth"), 10)

    def test_magic_bonus_added_with_expertise(self) -> None:
        # DEX 14 (+2), PB 3, expertise, +5 cloak = 2 + 6 + 5 = 13
        actor = _make_actor(dex_score=14, pb=3,
                              skill_proficiencies=["stealth"],
                              skill_expertise=["stealth"],
                              skill_bonuses={"stealth": 5})
        self.assertEqual(skill_modifier(actor, "stealth"), 13)

    def test_magic_bonus_without_proficiency(self) -> None:
        # DEX 14 (+2), no prof, +3 item = 2 + 3 = 5
        actor = _make_actor(dex_score=14, pb=3,
                              skill_bonuses={"stealth": 3})
        self.assertEqual(skill_modifier(actor, "stealth"), 5)

    def test_monster_listed_bonus_stacks_with_magic(self) -> None:
        # Listed stealth +6; magic +2 → total 8
        actor = _make_actor(skills_dict={"stealth": 6},
                              skill_bonuses={"stealth": 2})
        self.assertEqual(skill_modifier(actor, "stealth"), 8)


# ============================================================================
# Layer 4: _validate_skill_expertise
# ============================================================================

class ValidateSkillExpertiseTest(unittest.TestCase):

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_validate_skill_expertise(None, []), [])

    def test_unknown_skill_raises(self) -> None:
        with self.assertRaises(ValueError):
            _validate_skill_expertise(["not_a_skill"], ["not_a_skill"])

    def test_expertise_without_proficiency_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _validate_skill_expertise(["stealth"], [])
        self.assertIn("requires also being proficient",
                        str(ctx.exception))

    def test_expertise_with_proficiency_passes(self) -> None:
        self.assertEqual(
            _validate_skill_expertise(["stealth"], ["stealth"]),
            ["stealth"])

    def test_normalized_and_deduped(self) -> None:
        self.assertEqual(
            _validate_skill_expertise(
                ["Stealth", "stealth", "perception"],
                ["stealth", "perception"]),
            ["stealth", "perception"])

    def test_non_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            _validate_skill_expertise("stealth", ["stealth"])


# ============================================================================
# Layer 5: _validate_skill_bonuses
# ============================================================================

class ValidateSkillBonusesTest(unittest.TestCase):

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_validate_skill_bonuses(None), {})

    def test_unknown_skill_raises(self) -> None:
        with self.assertRaises(ValueError):
            _validate_skill_bonuses({"not_a_skill": 5})

    def test_non_int_raises(self) -> None:
        with self.assertRaises(ValueError):
            _validate_skill_bonuses({"stealth": "five"})

    def test_non_dict_raises(self) -> None:
        with self.assertRaises(ValueError):
            _validate_skill_bonuses([("stealth", 5)])

    def test_normalized_keys(self) -> None:
        self.assertEqual(
            _validate_skill_bonuses({"Stealth": 5, "Perception": 2}),
            {"stealth": 5, "perception": 2})


# ============================================================================
# Layer 6: pc_schema baking
# ============================================================================

class PCSchemaBakingTest(unittest.TestCase):

    def test_expertise_baked_on_template(self) -> None:
        spec = _base_pc(skill_proficiencies=["stealth"],
                          skill_expertise=["stealth"])
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["skill_expertise"], ["stealth"])

    def test_bonuses_baked_on_template(self) -> None:
        spec = _base_pc(skill_proficiencies=["stealth"],
                          skill_bonuses={"stealth": 5})
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["skill_bonuses"], {"stealth": 5})

    def test_derived_from_has_both(self) -> None:
        spec = _base_pc(skill_proficiencies=["stealth"],
                          skill_expertise=["stealth"],
                          skill_bonuses={"stealth": 5})
        template = build_pc_template(spec, _registry())
        derived = template["derived_from_pc_schema"]
        self.assertEqual(derived["skill_expertise"], ["stealth"])
        self.assertEqual(derived["skill_bonuses"], {"stealth": 5})

    def test_passive_perception_with_expertise(self) -> None:
        # WIS 14 (+2), PB 2 (L1), proficient + expertise → 10 + 2 + 4 = 16
        spec = _base_pc(skill_proficiencies=["perception"],
                          skill_expertise=["perception"],
                          wis_score=14)
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["senses"]["passive_perception"], 16)

    def test_passive_perception_with_magic_bonus(self) -> None:
        # WIS 14 (+2), proficient, +3 Eyes of the Eagle → 10 + 2 + 2 + 3 = 17
        spec = _base_pc(skill_proficiencies=["perception"],
                          skill_bonuses={"perception": 3},
                          wis_score=14)
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["senses"]["passive_perception"], 17)

    def test_passive_perception_expertise_plus_magic(self) -> None:
        # WIS 14 (+2), expertise (2×PB=4), +3 magic → 10 + 2 + 4 + 3 = 19
        spec = _base_pc(skill_proficiencies=["perception"],
                          skill_expertise=["perception"],
                          skill_bonuses={"perception": 3},
                          wis_score=14)
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["senses"]["passive_perception"], 19)

    def test_unknown_expertise_skill_raises_at_build(self) -> None:
        spec = _base_pc(skill_proficiencies=["not_a_skill"])
        with self.assertRaises(ValueError):
            build_pc_template(spec, _registry())

    def test_expertise_without_proficiency_raises_at_build(self) -> None:
        spec = _base_pc(skill_proficiencies=["perception"],
                          skill_expertise=["stealth"])
        with self.assertRaises(ValueError):
            build_pc_template(spec, _registry())


# ============================================================================
# Layer 7: passive Perception helper directly
# ============================================================================

class PassivePerceptionHelperTest(unittest.TestCase):

    def test_no_proficiency(self) -> None:
        # WIS 14 (+2), no profs → 10 + 2 = 12
        ability_scores = {"wis": {"score": 14}}
        self.assertEqual(
            _compute_passive_perception(ability_scores, [], 2),
            12)

    def test_proficiency_only(self) -> None:
        # WIS 14 (+2), prof, PB 2 → 10 + 2 + 2 = 14
        ability_scores = {"wis": {"score": 14}}
        self.assertEqual(
            _compute_passive_perception(ability_scores,
                                            ["perception"], 2),
            14)

    def test_expertise(self) -> None:
        # WIS 14 (+2), expertise, PB 2 → 10 + 2 + 4 = 16
        ability_scores = {"wis": {"score": 14}}
        self.assertEqual(
            _compute_passive_perception(ability_scores,
                                            ["perception"], 2,
                                            skill_expertise=["perception"]),
            16)

    def test_magic_only_no_proficiency(self) -> None:
        # WIS 14 (+2), no prof, +3 item → 10 + 2 + 3 = 15
        ability_scores = {"wis": {"score": 14}}
        self.assertEqual(
            _compute_passive_perception(
                ability_scores, [], 2,
                skill_bonuses={"perception": 3}),
            15)


if __name__ == "__main__":
    unittest.main()
