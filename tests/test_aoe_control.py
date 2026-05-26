"""AoE control scoring tests — Hypnotic Pattern shape.

Layers:
  1. _aoe_control_components extraction (apply_condition in on_fail/on_success)
  2. _aoe_target_control_ehp per-target math
  3. offensive_ehp_aoe with control-only AoE (Hypnotic Pattern):
     scales with target DPR, scales with p_fail, friendly fire applies
  4. Mixed damage + control AoE: both contributions sum
  5. End-to-end: hypnotic_pattern_vs_fireball fixture chooses HP

Run via:
    python -m unittest tests.test_aoe_control
"""
from __future__ import annotations

import random
import unittest

from engine.ai import offensive_ehp_aoe, score_candidate, score_candidates_v1
from engine.ai.ehp_scoring import (
    _aoe_control_components, _aoe_target_control_ehp,
)
from engine.ai.defensive_ehp import EXPECTED_CONTROL_ROUNDS, estimate_dpr
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy", hp: int = 100,
                ac: int = 13, position: tuple[int, int] = (0, 0),
                actions: list[dict] | None = None,
                wis_save: int = 0, dex_save: int = 0) -> Actor:
    abilities = {
        "str": {"score": 14, "save": 2},
        "dex": {"score": 10 + 2 * dex_save, "save": dex_save},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10 + 2 * wis_save, "save": wis_save},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  position=position, abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _hp_action(condition: str = "co_incapacitated",
                radius_ft: int = 15, dc: int = 15) -> dict:
    """Hypnotic Pattern-shape AoE control action."""
    return {
        "id": "a_hp", "type": "aoe_attack",
        "concentration": True,
        "spell_slot_level": 3,
        "area": {"shape": "sphere", "radius_ft": radius_ft,
                  "range_ft": 120},
        "pipeline": [{
            "primitive": "forced_save",
            "params": {
                "ability": "wisdom", "dc": dc,
                "affected": "all_creatures_in_area",
                "on_fail": [{
                    "primitive": "apply_condition",
                    "params": {"condition_id": condition,
                                "duration": "until_spell_ends"},
                }],
            },
        }],
    }


def _strong_attack_action() -> dict:
    """A weapon attack that yields high estimate_dpr."""
    return {
        "id": "a_strong", "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 7, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "4d12", "modifier": 5, "type": "bludgeoning"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# _aoe_control_components
# ============================================================================

class AoEControlComponentsTest(unittest.TestCase):

    def test_extracts_hard_control_condition(self) -> None:
        action = _hp_action(condition="co_incapacitated")
        components = _aoe_control_components(action, on="fail")
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["condition_id"], "co_incapacitated")
        self.assertAlmostEqual(components[0]["denial_fraction"], 1.0)

    def test_extracts_partial_control_condition(self) -> None:
        action = _hp_action(condition="co_restrained")
        components = _aoe_control_components(action, on="fail")
        self.assertEqual(len(components), 1)
        # Restrained is partial → < 1.0
        self.assertLess(components[0]["denial_fraction"], 1.0)
        self.assertGreater(components[0]["denial_fraction"], 0)

    def test_ignores_non_control_conditions(self) -> None:
        """An apply_condition for a non-control marker (rare; just here
        to exercise the filter) is skipped."""
        action = {
            "type": "aoe_attack",
            "pipeline": [{
                "primitive": "forced_save",
                "params": {
                    "on_fail": [{
                        "primitive": "apply_condition",
                        "params": {"condition_id": "co_charmed"},
                    }],
                },
            }],
        }
        components = _aoe_control_components(action, on="fail")
        # co_charmed isn't in HARD or PARTIAL control sets → no entry
        self.assertEqual(components, [])

    def test_on_success_components_extracted(self) -> None:
        """Rare but possible: a spell that applies a debuff on save success."""
        action = {
            "type": "aoe_attack",
            "pipeline": [{
                "primitive": "forced_save",
                "params": {
                    "on_success": [{
                        "primitive": "apply_condition",
                        "params": {"condition_id": "co_blinded"},
                    }],
                },
            }],
        }
        on_succ = _aoe_control_components(action, on="success")
        self.assertEqual(len(on_succ), 1)


# ============================================================================
# _aoe_target_control_ehp
# ============================================================================

class AoETargetControlEHPTest(unittest.TestCase):

    def test_per_target_formula(self) -> None:
        target = _make_actor("t", actions=[_strong_attack_action()])
        components = [{"condition_id": "co_incapacitated",
                        "denial_fraction": 1.0}]
        ehp = _aoe_target_control_ehp(target, components)
        # ehp = target_DPR × denial_fraction × EXPECTED_CONTROL_ROUNDS
        target_dpr = estimate_dpr(target)
        expected = target_dpr * 1.0 * EXPECTED_CONTROL_ROUNDS
        self.assertAlmostEqual(ehp, expected)

    def test_zero_dpr_zero_ehp(self) -> None:
        target = _make_actor("t", actions=[])
        components = [{"condition_id": "co_incapacitated",
                        "denial_fraction": 1.0}]
        self.assertEqual(_aoe_target_control_ehp(target, components), 0.0)

    def test_no_components_zero_ehp(self) -> None:
        target = _make_actor("t", actions=[_strong_attack_action()])
        self.assertEqual(_aoe_target_control_ehp(target, []), 0.0)

    def test_partial_denial_lower_score(self) -> None:
        target = _make_actor("t", actions=[_strong_attack_action()])
        hard = [{"condition_id": "co_incapacitated", "denial_fraction": 1.0}]
        partial = [{"condition_id": "co_restrained",
                      "denial_fraction": 0.5}]
        hard_ehp = _aoe_target_control_ehp(target, hard)
        partial_ehp = _aoe_target_control_ehp(target, partial)
        self.assertGreater(hard_ehp, partial_ehp)
        self.assertAlmostEqual(partial_ehp, hard_ehp / 2.0, places=4)


# ============================================================================
# offensive_ehp_aoe with control component
# ============================================================================

class AoEControlScoringTest(unittest.TestCase):

    def test_hp_scales_with_target_dpr(self) -> None:
        caster = _make_actor("c", side="pc", position=(0, 0))
        # Strong enemy = high DPR
        strong = _make_actor("strong", side="enemy",
                                actions=[_strong_attack_action()],
                                wis_save=-2,
                                position=(5, 0))
        # Weak enemy = no actions = 0 DPR
        weak = _make_actor("weak", side="enemy", wis_save=-2,
                              position=(5, 0))
        action = _hp_action(condition="co_incapacitated")

        strong_state = _state_with([caster, strong])
        weak_state = _state_with([caster, weak])

        strong_score = offensive_ehp_aoe(
            caster, (5, 0), action, strong_state)
        weak_score = offensive_ehp_aoe(
            caster, (5, 0), action, weak_state)
        self.assertGreater(strong_score, weak_score,
                            "HP score should be much higher vs high-DPR enemy")

    def test_hp_scales_with_p_fail(self) -> None:
        """An enemy with terrible WIS save is more likely to be hypnotized
        (higher p_fail) → higher control eHP."""
        caster = _make_actor("c", side="pc", position=(0, 0))
        weak_save = _make_actor("weak_save", side="enemy",
                                  actions=[_strong_attack_action()],
                                  wis_save=-5,
                                  position=(5, 0))
        strong_save = _make_actor("strong_save", side="enemy",
                                    actions=[_strong_attack_action()],
                                    wis_save=10,
                                    position=(5, 0))
        action = _hp_action(condition="co_incapacitated", dc=15)

        s_weak = offensive_ehp_aoe(
            caster, (5, 0), action, _state_with([caster, weak_save]))
        s_strong = offensive_ehp_aoe(
            caster, (5, 0), action, _state_with([caster, strong_save]))
        self.assertGreater(s_weak, s_strong,
                            "Easier-to-fail-save enemy scores higher control eHP")

    def test_friendly_fire_subtracts_for_caught_ally(self) -> None:
        caster = _make_actor("c", side="pc", position=(0, 0))
        enemy = _make_actor("e", side="enemy",
                              actions=[_strong_attack_action()],
                              wis_save=-2, position=(5, 0))
        ally = _make_actor("ally", side="pc",
                              actions=[_strong_attack_action()],
                              wis_save=-2, position=(5, 1))
        action = _hp_action(condition="co_incapacitated")

        clean_state = _state_with([caster, enemy])
        ally_state = _state_with([caster, enemy, ally])

        clean_score = offensive_ehp_aoe(
            caster, (5, 0), action, clean_state)
        ally_score = offensive_ehp_aoe(
            caster, (5, 0), action, ally_state)
        self.assertLess(ally_score, clean_score,
                          "Friendly fire (incapacitating an ally) should "
                          "lower the AoE score")


# ============================================================================
# Mixed damage + control AoE
# ============================================================================

class MixedDamageControlAoETest(unittest.TestCase):

    def test_mixed_action_sums_both_contributions(self) -> None:
        """A spell that does damage AND applies a control condition
        scores higher than either alone."""
        caster = _make_actor("c", side="pc", position=(0, 0))
        enemy = _make_actor("e", side="enemy", hp=100,
                               actions=[_strong_attack_action()],
                               wis_save=-2, dex_save=-2, position=(5, 0))
        state = _state_with([caster, enemy])

        # Damage-only AoE
        dmg_only = {
            "id": "a_dmg", "type": "aoe_attack",
            "area": {"shape": "sphere", "radius_ft": 15, "range_ft": 60},
            "pipeline": [{
                "primitive": "forced_save",
                "params": {
                    "ability": "wisdom", "dc": 15,
                    "affected": "all_creatures_in_area",
                    "on_fail": [
                        {"primitive": "damage",
                          "params": {"dice": "4d6", "type": "fire"}}],
                },
            }],
        }
        # Control-only AoE
        ctrl_only = _hp_action()
        # Mixed: damage + control
        mixed = {
            "id": "a_mixed", "type": "aoe_attack",
            "area": {"shape": "sphere", "radius_ft": 15, "range_ft": 60},
            "pipeline": [{
                "primitive": "forced_save",
                "params": {
                    "ability": "wisdom", "dc": 15,
                    "affected": "all_creatures_in_area",
                    "on_fail": [
                        {"primitive": "damage",
                          "params": {"dice": "4d6", "type": "fire"}},
                        {"primitive": "apply_condition",
                          "params": {"condition_id": "co_incapacitated"}},
                    ],
                },
            }],
        }

        dmg_score = offensive_ehp_aoe(caster, (5, 0), dmg_only, state)
        ctrl_score = offensive_ehp_aoe(caster, (5, 0), ctrl_only, state)
        mixed_score = offensive_ehp_aoe(caster, (5, 0), mixed, state)

        # Mixed should be approximately sum of damage + control (both
        # multiplied by p_fail under the same save)
        self.assertGreater(mixed_score, dmg_score)
        self.assertGreater(mixed_score, ctrl_score)


# ============================================================================
# End-to-end: hypnotic_pattern_vs_fireball fixture
# ============================================================================

class HypnoticPatternFixtureTest(unittest.TestCase):

    def test_wizard_picks_hypnotic_pattern_over_fireball(self) -> None:
        import random as _random
        from pathlib import Path
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner
        from engine.cli import _build_encounter
        from engine.loader import load_content, load_yaml_file

        repo_root = Path(__file__).parent.parent
        content_root = repo_root / "schema" / "content"
        schema_root = repo_root / "schema" / "definitions"
        fixture = Path(__file__).parent / "fixtures" / \
            "hypnotic_pattern_vs_fireball_encounter.yaml"

        registry = load_content(content_root, validate=True,
                                  schema_root=schema_root)
        spec = load_yaml_file(fixture)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1,
                                       content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Wizard's first AoE should be Hypnotic Pattern, not Fireball
        first_aoe = next(
            (e for e in state.event_log
              if e.get("event") == "aoe_origin_placed"
              and e.get("actor") == "wizard_pc"),
            None,
        )
        self.assertIsNotNone(first_aoe)
        self.assertEqual(first_aoe["action"], "a_hypnotic_pattern",
                          f"Wizard should cast Hypnotic Pattern (not "
                          f"{first_aoe['action']}) against beefy ogres "
                          f"— HP delivers more eHP than Fireball when "
                          f"the targets are too tanky to drop")

        # At least one ogre should be Incapacitated
        applied = [e for e in state.event_log
                    if e.get("event") == "condition_applied"
                    and e.get("condition") == "co_incapacitated"]
        self.assertGreater(len(applied), 0,
                            "At least one ogre should have failed the WIS "
                            "save and been Incapacitated")

        # Concentration started
        concs = [e for e in state.event_log
                  if e.get("event") == "concentration_started"
                  and e.get("caster") == "wizard_pc"]
        self.assertGreater(len(concs), 0)

        # Slot consumed
        slots = [e for e in state.event_log
                  if e.get("event") == "spell_slot_consumed"
                  and e.get("actor") == "wizard_pc"]
        self.assertGreater(len(slots), 0)
        self.assertEqual(slots[0]["slot_level"], 3)


if __name__ == "__main__":
    unittest.main()
