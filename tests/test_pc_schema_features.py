"""PC schema class-feature auto-wiring tests (PR #32).

Layers:
  1. derive_pc_resources scans the level_table up to the PC's level
  2. Action Surge: present at L2-16 with 1 charge, L17+ with 2 charges
  3. Second Wind: counter scales per class_resources at the PC's level
  4. Missing / unknown class → returns {} (no crash)
  5. Explicit `resources:` block on actor_spec wins on conflict (so
     fixture authors can force edge cases like AS=0 at L2)
  6. End-to-end via cli._build_actor: PC actor's resources contain the
     auto-derived keys

Run via:
    python -m unittest tests.test_pc_schema_features
"""
from __future__ import annotations

import unittest

from engine.pc_schema import derive_pc_resources


# ============================================================================
# Mock registry — minimal class def mirroring c_fighter
# ============================================================================

class _MockRegistry:
    """Stand-in for ContentRegistry that returns canned class defs."""

    def __init__(self, classes: dict[str, dict] | None = None) -> None:
        self._classes = classes or {}

    def get(self, entity_type: str, entity_id: str) -> dict:
        if entity_type != "class":
            raise KeyError(f"unknown entity type {entity_type!r}")
        if entity_id not in self._classes:
            raise KeyError(f"unknown class {entity_id!r}")
        return self._classes[entity_id]


def _fighter_class_def() -> dict:
    """Minimal c_fighter shape for testing — features list at each
    relevant level + class_resources.second_wind_uses."""
    return {
        "id": "c_fighter",
        "name": "Fighter",
        "core_traits": {
            "hit_die": "d10",
            "save_proficiencies": ["strength", "constitution"],
        },
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": ["f_fighting_style", "f_second_wind",
                            "f_weapon_mastery"],
              "class_resources": {"second_wind_uses": 2}},
            {"level": 2, "proficiency_bonus": 2,
              "features": ["f_action_surge_one_use", "f_tactical_mind"],
              "class_resources": {"second_wind_uses": 2}},
            {"level": 4, "proficiency_bonus": 2,
              "features": ["grant_asi_or_feat"],
              "class_resources": {"second_wind_uses": 3}},
            {"level": 10, "proficiency_bonus": 4,
              "features": ["grant_subclass_feature"],
              "class_resources": {"second_wind_uses": 4}},
            {"level": 17, "proficiency_bonus": 6,
              "features": ["f_action_surge_two_uses",
                            "f_indomitable_three_uses"],
              "class_resources": {"second_wind_uses": 4}},
        ],
    }


def _registry_with_fighter() -> _MockRegistry:
    return _MockRegistry({"c_fighter": _fighter_class_def()})


# ============================================================================
# Per-level auto-derivation
# ============================================================================

class ActionSurgeAutoWireTest(unittest.TestCase):

    def test_no_action_surge_at_L1(self) -> None:
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 1}
        out = derive_pc_resources(spec, reg)
        self.assertNotIn("action_surge_uses_remaining", out)

    def test_one_charge_at_L2(self) -> None:
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 2}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["action_surge_uses_remaining"], 1)

    def test_one_charge_at_L5(self) -> None:
        """L2 feature persists into the L2-16 band."""
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 5}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["action_surge_uses_remaining"], 1)

    def test_one_charge_at_L16(self) -> None:
        """Boundary: L16 still has the L2 feature only."""
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 16}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["action_surge_uses_remaining"], 1)

    def test_two_charges_at_L17(self) -> None:
        """L17 f_action_surge_two_uses supersedes L2's one-use variant."""
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 17}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["action_surge_uses_remaining"], 2)

    def test_two_charges_at_L20(self) -> None:
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 20}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["action_surge_uses_remaining"], 2)


class SecondWindAutoWireTest(unittest.TestCase):

    def test_two_uses_at_L1(self) -> None:
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 1}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["second_wind_uses_remaining"], 2)

    def test_three_uses_at_L4(self) -> None:
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 4}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["second_wind_uses_remaining"], 3)

    def test_four_uses_at_L10(self) -> None:
        reg = _registry_with_fighter()
        spec = {"class": "c_fighter", "level": 10}
        out = derive_pc_resources(spec, reg)
        self.assertEqual(out["second_wind_uses_remaining"], 4)


# ============================================================================
# Edge cases: missing class / unknown class / no level
# ============================================================================

class DerivePCResourcesEdgeCasesTest(unittest.TestCase):

    def test_returns_empty_when_class_missing(self) -> None:
        reg = _registry_with_fighter()
        out = derive_pc_resources({"level": 5}, reg)
        self.assertEqual(out, {})

    def test_returns_empty_when_class_unknown(self) -> None:
        reg = _registry_with_fighter()
        out = derive_pc_resources(
            {"class": "c_nonexistent", "level": 5}, reg)
        self.assertEqual(out, {})

    def test_returns_empty_when_registry_get_raises(self) -> None:
        class _BrokenRegistry:
            def get(self, *a, **k): raise KeyError("nope")
        out = derive_pc_resources(
            {"class": "c_fighter", "level": 5}, _BrokenRegistry())
        self.assertEqual(out, {})

    def test_level_defaults_to_1(self) -> None:
        """No level field → treated as L1."""
        reg = _registry_with_fighter()
        out = derive_pc_resources({"class": "c_fighter"}, reg)
        # L1 has Second Wind but no Action Surge
        self.assertNotIn("action_surge_uses_remaining", out)
        self.assertEqual(out["second_wind_uses_remaining"], 2)

    def test_level_zero_returns_empty(self) -> None:
        reg = _registry_with_fighter()
        out = derive_pc_resources(
            {"class": "c_fighter", "level": 0}, reg)
        self.assertEqual(out, {})


# ============================================================================
# End-to-end: cli._build_actor merges derived + explicit resources
# ============================================================================

class CLIBuildActorMergesResourcesTest(unittest.TestCase):
    """Integration: an actor_spec with `pc:` block ends up with the
    auto-derived resources on the Actor instance, and explicit
    `resources:` overrides on conflict."""

    def test_actor_built_from_pc_spec_has_auto_derived_resources(self) -> None:
        from engine.cli import _build_actor
        reg = _registry_with_fighter()
        spec = {
            "instance_id": "fighter_test",
            "side": "pc",
            "pc": {
                "class": "c_fighter",
                "level": 2,
                "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                     "int": 10, "wis": 10, "cha": 10},
                "weapons": [{"id": "a_sword", "name": "Sword",
                              "attack_ability": "str",
                              "damage_dice": "1d8",
                              "damage_type": "slashing"}],
            },
        }
        actor = _build_actor(spec, reg)
        self.assertEqual(actor.resources.get("action_surge_uses_remaining"),
                          1)
        self.assertEqual(actor.resources.get("second_wind_uses_remaining"),
                          2)

    def test_explicit_resources_block_overrides_derived(self) -> None:
        """Fixture author can force `action_surge_uses_remaining: 0` on
        a L2 fighter (e.g., to test the 'no AS available' branch)."""
        from engine.cli import _build_actor
        reg = _registry_with_fighter()
        spec = {
            "instance_id": "fighter_no_as",
            "side": "pc",
            "pc": {
                "class": "c_fighter",
                "level": 2,
                "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                     "int": 10, "wis": 10, "cha": 10},
                "weapons": [{"id": "a_sword", "name": "Sword",
                              "attack_ability": "str",
                              "damage_dice": "1d8",
                              "damage_type": "slashing"}],
            },
            "resources": {
                "action_surge_uses_remaining": 0,
            },
        }
        actor = _build_actor(spec, reg)
        # Explicit override wins
        self.assertEqual(actor.resources.get("action_surge_uses_remaining"),
                          0)
        # Non-overridden derived key survives
        self.assertEqual(actor.resources.get("second_wind_uses_remaining"),
                          2)

    def test_non_pc_actor_unaffected(self) -> None:
        """Inline-template actors don't gain mystery resources."""
        from engine.cli import _build_actor
        reg = _registry_with_fighter()
        spec = {
            "instance_id": "ogre_test",
            "side": "enemy",
            "template": {
                "id": "tpl_ogre", "name": "Ogre",
                "abilities": {
                    "str": {"score": 16, "save": 3}, "dex": {"score": 10, "save": 0},
                    "con": {"score": 14, "save": 2}, "int": {"score": 8, "save": -1},
                    "wis": {"score": 10, "save": 0}, "cha": {"score": 8, "save": -1},
                },
                "cr": {"value": 2, "xp": 450, "proficiency_bonus": 2},
                "combat": {"armor_class": 14,
                            "hit_points": {"average": 30, "dice": "4d10",
                                            "con_contribution": 8},
                            "speed": {"walk": 30},
                            "initiative": {"modifier": 0}},
                "actions": [],
            },
        }
        actor = _build_actor(spec, reg)
        self.assertEqual(actor.resources, {})


if __name__ == "__main__":
    unittest.main()
