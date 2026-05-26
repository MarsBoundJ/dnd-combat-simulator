"""Help action v1 tests — the third basic action (Dodge / Disengage / Help).

Layers:
  1. Help candidate generation: adjacency gates (helper-near-enemy
     AND ally-near-helper), self-exclusion
  2. Help execution attaches an advantage modifier to the ally
  3. Help eHP scoring: per_attack_damage × 0.225 (one-attack uplift,
     NOT scaled by 2.5 buff rounds like Bless)
  4. Built-in Help: implicit on all actors via basic_actions
  5. Explicit-Help dedup against built-in
  6. Re-cast guard: don't pile new Help on top of an unconsumed one
  7. Behavioral integration: ally with strong attack gets advantage
     after helper uses Help

Run via:
    python -m unittest tests.test_help_action
"""
from __future__ import annotations

import random
import unittest

from engine.ai import (
    score_candidate, offensive_ehp_help, estimate_per_attack_damage,
)
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState
from engine.core.basic_actions import (
    BUILT_IN_HELP, built_in_actions_for, _has_explicit_help,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc", hp: int = 30,
                ac: int = 14, position: tuple[int, int] = (0, 0),
                speed: int = 30, actions: list[dict] | None = None) -> Actor:
    abilities = {
        "str": {"score": 14, "save": 2},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _help_action() -> dict:
    """Help per 5e RAW: ally within 5 ft gets advantage on next attack.
    Lifetime is per_owner_attack — consumed after one swing. The
    `when: attacker_is_self` gate ensures the modifier only fires when
    the helped ally is ATTACKING (not when being attacked)."""
    return {
        "id": "a_help", "name": "Help", "type": "help",
        "pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "ally",
                          "when": "attacker_is_self",
                          "modifier": "advantage_for_self",
                          "lifetime": "per_owner_attack"}},
        ],
    }


def _strong_attack(action_id: str = "a_sword", bonus: int = 6,
                    dice: str = "2d6", modifier: int = 4) -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


def _weak_attack(action_id: str = "a_punch", bonus: int = 0,
                  dice: str = "1d4", modifier: int = 0) -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "bludgeoning"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# Candidate generation — adjacency gates
# ============================================================================

class HelpCandidateGenerationTest(unittest.TestCase):

    def test_help_requires_adjacent_enemy(self) -> None:
        """Helper has Help and an adjacent ally, but no enemy within 5
        ft — Help should NOT be a candidate (the advantage would have
        no creature it could trigger against per RAW)."""
        helper = _make_actor("helper", side="pc", position=(0, 0),
                              actions=[_help_action(), _weak_attack()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        # Enemy far away — outside helper's 5-ft requirement
        enemy = _make_actor("enemy", side="enemy", position=(10, 0),
                              actions=[_strong_attack()])
        state = _state_with([helper, ally, enemy])
        cands = generate_candidates(helper, state)
        help_cands = [c for c in cands if c["kind"] == "help"]
        self.assertEqual(len(help_cands), 0,
                          "Help should not be a candidate when no enemy is "
                          "within 5 ft of the helper")

    def test_help_requires_adjacent_ally(self) -> None:
        """Helper has Help, an enemy is adjacent, but no ally within 5
        ft — Help should produce zero candidates."""
        helper = _make_actor("helper", side="pc", position=(0, 0),
                              actions=[_help_action(), _weak_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(0, 1),
                              actions=[_strong_attack()])
        # Distant ally
        ally = _make_actor("ally", side="pc", position=(10, 0),
                            actions=[_strong_attack()])
        state = _state_with([helper, ally, enemy])
        cands = generate_candidates(helper, state)
        help_cands = [c for c in cands if c["kind"] == "help"]
        self.assertEqual(len(help_cands), 0,
                          "Help should not produce candidates when no "
                          "ally is within 5 ft of the helper")

    def test_help_excludes_self_target(self) -> None:
        """Helper has Help + an adjacent enemy + no other allies. Help
        should produce zero candidates (you can't Help yourself per RAW)."""
        helper = _make_actor("helper", side="pc", position=(0, 0),
                              actions=[_help_action(), _weak_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(0, 1),
                              actions=[_strong_attack()])
        state = _state_with([helper, enemy])
        cands = generate_candidates(helper, state)
        help_cands = [c for c in cands if c["kind"] == "help"]
        self.assertEqual(len(help_cands), 0,
                          "Help should never target self")

    def test_help_emits_candidate_when_gates_pass(self) -> None:
        """Helper adjacent to enemy AND adjacent to ally → one Help
        candidate (targeting the ally)."""
        helper = _make_actor("helper", side="pc", position=(0, 0),
                              actions=[_help_action(), _weak_attack()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(1, 0),
                              actions=[_strong_attack()])
        state = _state_with([helper, ally, enemy])
        cands = generate_candidates(helper, state)
        help_cands = [c for c in cands if c["kind"] == "help"]
        self.assertEqual(len(help_cands), 1)
        self.assertEqual(help_cands[0]["target"].id, "ally")


# ============================================================================
# Help execution — modifier application
# ============================================================================

class HelpExecutionTest(unittest.TestCase):

    def test_help_attaches_advantage_modifier_to_ally(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        helper = _make_actor("helper", side="pc", actions=[_help_action()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        state = _state_with([helper, ally])
        chosen = {"kind": "help", "actor": helper, "target": ally,
                  "action": _help_action()}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())

        # The advantage modifier should be on the ALLY (target), not the helper
        ally_mods = [m for m in ally.active_modifiers
                      if m.get("primitive") == "attack_modifier"]
        self.assertEqual(len(ally_mods), 1)
        self.assertEqual(ally_mods[0]["params"].get("modifier"),
                          "advantage_for_self")
        # Lifetime is per_owner_attack
        self.assertEqual(ally_mods[0].get("lifetime"), "per_owner_attack")
        # Helper has no new modifiers (Help doesn't buff the helper)
        helper_mods = [m for m in helper.active_modifiers
                        if m.get("primitive") == "attack_modifier"]
        self.assertEqual(len(helper_mods), 0)


# ============================================================================
# eHP scoring
# ============================================================================

class HelpEHPScoringTest(unittest.TestCase):

    def test_help_scores_per_attack_damage_times_advantage_delta(self) -> None:
        """Help eHP ≈ ally_per_attack_damage × 0.225 (single-attack
        advantage uplift, no buff-rounds multiplier)."""
        helper = _make_actor("helper", side="pc",
                              actions=[_help_action()])
        # Ally has greatsword: 2d6+4 → 11 mean damage on hit; at +6 vs
        # AC 15 needs 9 → p_hit = 0.6; per_attack = 6.6.
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        state = _state_with([helper, ally])
        score = offensive_ehp_help(helper, ally, _help_action(), state)
        per_attack = estimate_per_attack_damage(ally)
        self.assertGreater(per_attack, 0)
        # Score should equal per_attack × DELTA_HIT_FROM_ADVANTAGE (0.225)
        self.assertAlmostEqual(score, per_attack * 0.225, places=4)

    def test_help_scores_zero_for_ally_with_no_attacks(self) -> None:
        helper = _make_actor("helper", side="pc",
                              actions=[_help_action()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[])     # pure controller — no DPR
        state = _state_with([helper, ally])
        score = offensive_ehp_help(helper, ally, _help_action(), state)
        self.assertEqual(score, 0.0)

    def test_help_scores_zero_for_self(self) -> None:
        helper = _make_actor("helper", side="pc",
                              actions=[_help_action(), _strong_attack()])
        state = _state_with([helper])
        score = offensive_ehp_help(helper, helper, _help_action(), state)
        self.assertEqual(score, 0.0)

    def test_help_scores_zero_for_dead_ally(self) -> None:
        helper = _make_actor("helper", side="pc",
                              actions=[_help_action()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        ally.hp_current = 0
        state = _state_with([helper, ally])
        score = offensive_ehp_help(helper, ally, _help_action(), state)
        self.assertEqual(score, 0.0)

    def test_help_does_not_stack_on_unconsumed_help(self) -> None:
        """If the ally still has an unconsumed Help advantage from this
        helper, re-casting should score 0 (don't pile on a duplicate
        modifier that wastes the action)."""
        helper = _make_actor("helper", side="pc",
                              actions=[_help_action()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        # Simulate an active Help modifier already on the ally
        ally.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "ally", "modifier": "advantage_for_self"},
            "lifetime": "per_owner_attack",
            "source": {"type": "action", "action_id": "a_help",
                        "caster_id": "helper"},
        })
        state = _state_with([helper, ally])
        score = offensive_ehp_help(helper, ally, _help_action(), state)
        self.assertEqual(score, 0.0)

    def test_help_score_via_score_candidate_dispatch(self) -> None:
        """score_candidate routes 'help' kind to offensive_ehp_help."""
        helper = _make_actor("helper", side="pc",
                              actions=[_help_action()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        state = _state_with([helper, ally])
        candidate = {"kind": "help", "actor": helper, "target": ally,
                      "action": _help_action()}
        score = score_candidate(candidate, state)
        self.assertGreater(score, 0)


# ============================================================================
# Built-in Help injection
# ============================================================================

class BuiltInHelpTest(unittest.TestCase):

    def test_built_in_help_injected_when_ally_adjacent(self) -> None:
        helper = _make_actor("helper", side="pc",
                              actions=[_weak_attack()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(1, 0),
                              actions=[_strong_attack()])
        state = _state_with([helper, ally, enemy])
        built_ins = built_in_actions_for(helper, "action", state)
        help_built_ins = [a for a in built_ins if a.get("type") == "help"]
        self.assertEqual(len(help_built_ins), 1)
        self.assertEqual(help_built_ins[0]["id"], "_builtin_help")

    def test_built_in_help_skipped_when_no_ally_adjacent(self) -> None:
        helper = _make_actor("helper", side="pc",
                              actions=[_weak_attack()])
        # No ally — solo PC
        enemy = _make_actor("enemy", side="enemy", position=(0, 1),
                              actions=[_strong_attack()])
        state = _state_with([helper, enemy])
        built_ins = built_in_actions_for(helper, "action", state)
        help_built_ins = [a for a in built_ins if a.get("type") == "help"]
        self.assertEqual(len(help_built_ins), 0,
                          "No nearby ally → no built-in Help")

    def test_built_in_help_dedup_against_explicit_declaration(self) -> None:
        """Actor with explicit Help shouldn't also get the built-in
        (would generate two redundant candidates per ally)."""
        helper = _make_actor("helper", side="pc",
                              actions=[_help_action(), _weak_attack()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(1, 0),
                              actions=[_strong_attack()])
        state = _state_with([helper, ally, enemy])
        built_ins = built_in_actions_for(helper, "action", state)
        help_built_ins = [a for a in built_ins if a.get("type") == "help"]
        self.assertEqual(len(help_built_ins), 0)

    def test_explicit_help_detection(self) -> None:
        self.assertTrue(_has_explicit_help([_help_action()]))
        self.assertFalse(_has_explicit_help([_weak_attack()]))
        self.assertFalse(_has_explicit_help([]))


# ============================================================================
# Behavioral integration — helper picks Help when ally DPR is high
# ============================================================================

class HelpLifetimeTest(unittest.TestCase):

    def test_help_survives_incoming_attack_on_helped_ally(self) -> None:
        """Regression: Help uses per_owner_attack lifetime, NOT
        per_single_attack. If we used per_single_attack, the modifier
        would be consumed when the helped ally is ATTACKED — leaving
        no advantage for their own next swing. Verify the modifier
        persists across one incoming attack and only consumes on the
        ally's own attack."""
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        helper = _make_actor("helper", side="pc")
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(0, 2),
                              actions=[_strong_attack()])
        state = _state_with([helper, ally, enemy])
        # Attach Help modifier to ally manually (skip the action execution
        # plumbing — that's covered by HelpExecutionTest)
        ally.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "ally", "when": "attacker_is_self",
                        "modifier": "advantage_for_self"},
            "lifetime": "per_owner_attack",
            "source": {"type": "action", "action_id": "a_help",
                        "caster_id": "helper"},
        })

        # Step 1: enemy attacks the ally — Help should NOT be consumed
        primitives = PrimitiveRegistry.with_defaults()
        bus = EventBus()
        rng = random.Random(1)
        from engine import primitives as primitives_module
        primitives_module.set_rng(rng)
        state.current_attack = {"actor": enemy, "target": ally,
                                  "action": _strong_attack(),
                                  "state": None,
                                  "had_advantage": False,
                                  "had_disadvantage": False,
                                  "area_origin": None,
                                  "area_direction": None}
        primitives.invoke("attack_roll",
                            {"kind": "melee", "bonus": 6, "reach_ft": 5},
                            state, bus)
        help_mods = [m for m in ally.active_modifiers
                      if (m.get("source") or {}).get("action_id") == "a_help"]
        self.assertEqual(len(help_mods), 1,
                          "Help modifier should survive an incoming attack "
                          "on the helped ally (per_owner_attack lifetime)")

        # Step 2: ally attacks the enemy — Help SHOULD be consumed now
        state.current_attack = {"actor": ally, "target": enemy,
                                  "action": _strong_attack(),
                                  "state": None,
                                  "had_advantage": False,
                                  "had_disadvantage": False,
                                  "area_origin": None,
                                  "area_direction": None}
        primitives.invoke("attack_roll",
                            {"kind": "melee", "bonus": 6, "reach_ft": 5},
                            state, bus)
        help_mods = [m for m in ally.active_modifiers
                      if (m.get("source") or {}).get("action_id") == "a_help"]
        self.assertEqual(len(help_mods), 0,
                          "Help modifier should be consumed by the helped "
                          "ally's own attack (per_owner_attack lifetime)")


# ============================================================================
# Behavioral integration — helper picks Help when ally DPR is high
# ============================================================================

class HelpBehavioralTest(unittest.TestCase):

    def test_weak_helper_with_strong_ally_picks_help_over_own_attack(self) -> None:
        """A helper whose only attack is a weak punch should prefer
        Help-ing a strong-DPR ally over swinging the punch (one
        attack at advantage from a greatsword > one punch hit)."""
        from engine.ai import score_candidates_v1, select_action_v1
        from engine.ai.behavior_profile import resolve_archetype
        helper = _make_actor("helper", side="pc", position=(0, 0),
                              actions=[_help_action(), _weak_attack()])
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            actions=[_strong_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(1, 0),
                              hp=80, ac=18,
                              actions=[_strong_attack()])
        state = _state_with([helper, ally, enemy])
        cands = generate_candidates(helper, state)
        # Confirm both kinds are present
        kinds = {c["kind"] for c in cands}
        self.assertIn("help", kinds)
        self.assertIn("weapon_attack", kinds)
        # Score the Help vs the weak attack directly
        help_cand = [c for c in cands if c["kind"] == "help"][0]
        weak_cand = [c for c in cands if c["kind"] == "weapon_attack"][0]
        help_score = score_candidate(help_cand, state)
        weak_score = score_candidate(weak_cand, state)
        self.assertGreater(help_score, weak_score,
                            f"Help ({help_score:.2f}) should beat weak punch "
                            f"({weak_score:.2f}) — strong ally + tough enemy")


if __name__ == "__main__":
    unittest.main()
