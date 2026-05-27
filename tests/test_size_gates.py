"""Actor.size + Push size gate + Cleave/Graze Heavy gate (PR #65).

Layers:
  1. sizes module helpers
  2. Actor.size loading via cli._build_actor
  3. Push size gate: Large+ smaller pushed; Huge+ immune
  4. Cleave/Graze Heavy gate in _build_weapon_action
"""
from __future__ import annotations

import unittest

from engine.core.sizes import (
    KNOWN_SIZES, PUSH_SIZES, normalize_size, size_at_or_below,
    SIZE_MEDIUM, SIZE_LARGE, SIZE_HUGE,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.core.weapon_masteries import apply_mastery_effects
from engine.pc_schema import _build_weapon_action


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  size="medium") -> Actor:
    abilities = {k: {"score": 14 if k == "str" else 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=30, hp_max=30, ac=14,
                  speed={"walk": 30}, position=position,
                  abilities=abilities, size=size,
                  weapon_masteries=["push"])


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1: sizes module
# ============================================================================

class SizesModuleTest(unittest.TestCase):

    def test_known_sizes_count(self) -> None:
        self.assertEqual(len(KNOWN_SIZES), 6)

    def test_push_sizes_excludes_huge_gargantuan(self) -> None:
        self.assertNotIn("huge", PUSH_SIZES)
        self.assertNotIn("gargantuan", PUSH_SIZES)
        self.assertIn("medium", PUSH_SIZES)
        self.assertIn("large", PUSH_SIZES)

    def test_normalize_none_returns_medium(self) -> None:
        self.assertEqual(normalize_size(None), "medium")

    def test_normalize_empty_returns_medium(self) -> None:
        self.assertEqual(normalize_size(""), "medium")

    def test_normalize_case_insensitive(self) -> None:
        self.assertEqual(normalize_size("Large"), "large")

    def test_normalize_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_size("colossal")

    def test_size_at_or_below(self) -> None:
        self.assertTrue(size_at_or_below("medium", "large"))
        self.assertTrue(size_at_or_below("large", "large"))
        self.assertFalse(size_at_or_below("huge", "large"))
        self.assertTrue(size_at_or_below("tiny", "medium"))


# ============================================================================
# Layer 2: Actor.size loading
# ============================================================================

class ActorSizeLoadingTest(unittest.TestCase):

    def test_default_medium(self) -> None:
        actor = _make_actor()
        self.assertEqual(actor.size, "medium")

    def test_explicit_size_kept(self) -> None:
        actor = _make_actor(size="large")
        self.assertEqual(actor.size, "large")

    def test_cli_loads_from_template_size(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Big",
            "size": "huge",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 100}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
        }
        actor = _build_actor({"instance_id": "x", "template": template},
                                registry=None)
        self.assertEqual(actor.size, "huge")

    def test_cli_actor_spec_size_overrides_template(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Big",
            "size": "huge",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 100}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
        }
        actor = _build_actor({"instance_id": "x", "template": template,
                                 "size": "gargantuan"},
                                registry=None)
        self.assertEqual(actor.size, "gargantuan")

    def test_cli_unknown_size_raises(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Bad",
            "size": "colossal",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
        }
        with self.assertRaises(ValueError):
            _build_actor({"instance_id": "x", "template": template},
                            registry=None)

    def test_cli_defaults_when_template_omits(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Avg",
            # no `size:` field
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
        }
        actor = _build_actor({"instance_id": "x", "template": template},
                                registry=None)
        self.assertEqual(actor.size, "medium")


# ============================================================================
# Layer 3: Push size gate
# ============================================================================

class PushSizeGateTest(unittest.TestCase):

    def _push_params(self):
        return {"id": "push", "ability_mod": 3,
                "damage_type": "bludgeoning", "save_dc": 13}

    def test_push_medium_target_pushed(self) -> None:
        attacker = _make_actor("a", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0),
                                size="medium")
        state = _state_with([attacker, target])
        apply_mastery_effects(self._push_params(),
                                 attacker, target, "hit", state)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "push"]
        self.assertEqual(len(applied), 1)

    def test_push_large_target_pushed(self) -> None:
        attacker = _make_actor("a", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0),
                                size="large")
        state = _state_with([attacker, target])
        apply_mastery_effects(self._push_params(),
                                 attacker, target, "hit", state)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "push"]
        self.assertEqual(len(applied), 1)

    def test_push_huge_target_immune(self) -> None:
        attacker = _make_actor("a", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0),
                                size="huge")
        original_pos = target.position
        state = _state_with([attacker, target])
        apply_mastery_effects(self._push_params(),
                                 attacker, target, "hit", state)
        # Target NOT moved
        self.assertEqual(target.position, original_pos)
        # Skip event logged with reason=size_immune
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"
                    and e.get("mastery") == "push"]
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]["reason"], "size_immune")
        self.assertEqual(skips[0]["target_size"], "huge")

    def test_push_gargantuan_target_immune(self) -> None:
        attacker = _make_actor("a", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0),
                                size="gargantuan")
        state = _state_with([attacker, target])
        apply_mastery_effects(self._push_params(),
                                 attacker, target, "hit", state)
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"]
        self.assertEqual(len(skips), 1)

    def test_push_tiny_target_pushed(self) -> None:
        attacker = _make_actor("a", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0),
                                size="tiny")
        state = _state_with([attacker, target])
        apply_mastery_effects(self._push_params(),
                                 attacker, target, "hit", state)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"]
        self.assertEqual(len(applied), 1)


# ============================================================================
# Layer 4: Cleave / Graze Heavy gate
# ============================================================================

class HeavyGateTest(unittest.TestCase):

    def _build(self, weapon):
        return _build_weapon_action(
            weapon,
            ability_scores={"str": {"score": 16}, "dex": {"score": 14}},
            proficiency_bonus=2,
        )

    def test_cleave_on_heavy_weapon_passes(self) -> None:
        weapon = {"id": "a_gs", "name": "Greatsword",
                    "attack_ability": "str", "damage_dice": "2d6",
                    "damage_type": "slashing", "reach_ft": 5,
                    "two_handed": True, "heavy": True,
                    "mastery": "cleave"}
        action = self._build(weapon)
        self.assertEqual(
            action["pipeline"][0]["params"]["mastery"]["id"],
            "cleave")

    def test_cleave_on_non_heavy_weapon_raises(self) -> None:
        weapon = {"id": "a_short", "name": "Shortsword",
                    "attack_ability": "str", "damage_dice": "1d6",
                    "damage_type": "piercing", "reach_ft": 5,
                    "mastery": "cleave"}    # not heavy
        with self.assertRaises(ValueError) as ctx:
            self._build(weapon)
        self.assertIn("heavy", str(ctx.exception).lower())

    def test_graze_on_heavy_weapon_passes(self) -> None:
        weapon = {"id": "a_maul", "name": "Maul",
                    "attack_ability": "str", "damage_dice": "2d6",
                    "damage_type": "bludgeoning", "reach_ft": 5,
                    "two_handed": True, "heavy": True,
                    "mastery": "graze"}
        action = self._build(weapon)
        self.assertEqual(
            action["pipeline"][0]["params"]["mastery"]["id"],
            "graze")

    def test_graze_on_non_heavy_weapon_raises(self) -> None:
        weapon = {"id": "a_short", "name": "Shortsword",
                    "attack_ability": "str", "damage_dice": "1d6",
                    "damage_type": "piercing", "reach_ft": 5,
                    "mastery": "graze"}
        with self.assertRaises(ValueError):
            self._build(weapon)

    def test_cleave_on_ranged_heavy_weapon_raises(self) -> None:
        # Heavy crossbow IS heavy AND ranged; Cleave requires melee.
        weapon = {"id": "a_hcb", "name": "Heavy Crossbow",
                    "attack_ability": "dex", "damage_dice": "1d10",
                    "damage_type": "piercing", "range_ft": 100,
                    "heavy": True, "two_handed": True,
                    "mastery": "cleave"}
        with self.assertRaises(ValueError) as ctx:
            self._build(weapon)
        self.assertIn("melee", str(ctx.exception).lower())

    def test_other_masteries_not_gated_on_heavy(self) -> None:
        # Vex / Sap / Topple / Push / Nick don't require Heavy
        for mastery_id in ("vex", "sap", "topple", "push", "nick"):
            weapon = {"id": "a_short", "name": "Shortsword",
                        "attack_ability": "str", "damage_dice": "1d6",
                        "damage_type": "piercing", "reach_ft": 5,
                        "light": True,
                        "mastery": mastery_id}
            # Should not raise
            action = self._build(weapon)
            self.assertEqual(
                action["pipeline"][0]["params"]["mastery"]["id"],
                mastery_id,
                msg=f"Mastery {mastery_id} failed to build on light weapon")


if __name__ == "__main__":
    unittest.main()
