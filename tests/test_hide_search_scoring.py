"""AI eHP scoring for Hide + Search (PR #59).

Layers:
  1. _stealth_success_probability helper
  2. offensive_ehp_hide:
     - Gate fail (no obscurement, no cover) → 0
     - No living enemies → 0
     - All enemies auto-spot via passive Perception → 0
     - Heavy obscurement + decent stealth + enemies in threat range
       → positive eHP
     - Higher stealth mod → higher p_success → higher score
     - More enemies in threat range → larger defensive value
     - Out-of-threat-range enemies don't contribute to defensive value
  3. offensive_ehp_search:
     - No hidden enemies → 0
     - Actor has no scorable attacks → 0
     - Hidden enemy with low stealth_total + high perception → high
       p_reveal → high score
     - Hidden enemy with high stealth_total + low perception → low
       p_reveal → low score
     - Multiple hidden enemies → score sums per-enemy
     - Spell-source Invisible ignored (only Hide-source counted)
  4. score_candidate dispatch:
     - kind='hide' routes to offensive_ehp_hide
     - kind='search' routes to offensive_ehp_search
  5. pipeline.generate_candidates emits search candidate for an
     explicit search action on the actor's template
"""
from __future__ import annotations

import unittest

from engine.ai.ehp_scoring import (
    HIDE_DC, _expected_stealth_total, _stealth_success_probability,
    offensive_ehp_hide, offensive_ehp_search, score_candidate,
)
from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  passive_perception=10,
                  dex_score=14, str_score=10, wis_score=10,
                  skill_proficiencies=None,
                  cover="none",
                  applied_conditions=None,
                  actions=None) -> Actor:
    abilities = {
        "str": {"score": str_score, "save": 0},
        "dex": {"score": dex_score, "save": 0},
        "con": {"score": 10, "save": 0},
        "int": {"score": 10, "save": 0},
        "wis": {"score": wis_score, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": actions or []}
    if skill_proficiencies:
        template["skill_proficiencies"] = list(skill_proficiencies)
    actor = Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=20, hp_max=20, ac=14,
                   speed={"walk": 30}, position=position,
                   abilities=abilities,
                   passive_perception=passive_perception,
                   cover=cover)
    if applied_conditions:
        actor.applied_conditions = list(applied_conditions)
    return actor


def _basic_weapon_attack():
    """A modest weapon attack so estimate_per_attack_damage > 0."""
    return {
        "id": "a_attack", "name": "Attack",
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "1d8", "modifier": 3, "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


def _state_with(actors, environment=None):
    enc = Encounter(id="t", actors=actors, environment=environment or {})
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _hide_condition(stealth_total=20):
    return {"condition_id": "co_invisible",
             "source_action_id": "a_hide",
             "stealth_total": stealth_total}


def _spell_invisible():
    return {"condition_id": "co_invisible",
             "source_action_id": "a_invisibility_spell"}


def _hide_action():
    return {"id": "a_hide", "name": "Hide",
             "type": "hide", "pipeline": []}


def _search_action():
    return {"id": "a_search", "name": "Search",
             "type": "search", "pipeline": []}


# ============================================================================
# Layer 1: _stealth_success_probability
# ============================================================================

class StealthProbabilityTest(unittest.TestCase):

    def test_dc_constant(self) -> None:
        self.assertEqual(HIDE_DC, 15)

    def test_mod_zero_5_in_20(self) -> None:
        # P(d20 >= 15) = 6/20 = 0.30
        self.assertAlmostEqual(_stealth_success_probability(0), 0.30,
                                  places=2)

    def test_mod_plus_5_11_in_20(self) -> None:
        # P(d20 + 5 >= 15) = P(d20 >= 10) = 11/20 = 0.55
        self.assertAlmostEqual(_stealth_success_probability(5), 0.55,
                                  places=2)

    def test_mod_plus_15_auto_pass(self) -> None:
        # P(d20 + 15 >= 15) = 1.0 (any roll)
        self.assertEqual(_stealth_success_probability(15), 1.0)

    def test_negative_mod_low_prob(self) -> None:
        # P(d20 - 5 >= 15) = P(d20 >= 20) = 1/20 = 0.05
        self.assertAlmostEqual(_stealth_success_probability(-5), 0.05,
                                  places=2)

    def test_very_negative_zero(self) -> None:
        # P(d20 - 100 >= 15) = 0
        self.assertEqual(_stealth_success_probability(-100), 0.0)


# ============================================================================
# Layer 2: offensive_ehp_hide
# ============================================================================

class HideScoringTest(unittest.TestCase):

    def test_gate_fail_no_obscurement_no_cover_returns_zero(self) -> None:
        actor = _make_actor("a", dex_score=20,
                              skill_proficiencies=["stealth"])
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              actions=[_basic_weapon_attack()])
        state = _state_with([actor, enemy])
        # No obscurement zone, no cover
        score = offensive_ehp_hide(actor, _hide_action(), state)
        self.assertEqual(score, 0.0)

    def test_no_enemies_returns_zero(self) -> None:
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        actor = _make_actor("a", dex_score=20,
                              skill_proficiencies=["stealth"],
                              position=(2, 2))
        state = _state_with([actor], environment=env)
        score = offensive_ehp_hide(actor, _hide_action(), state)
        self.assertEqual(score, 0.0)

    def test_all_enemies_auto_spot_returns_zero(self) -> None:
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        actor = _make_actor("a", dex_score=10,    # +0 stealth
                              position=(2, 2))
        # Enemy with very high passive Perception — easily auto-spots
        # the actor's expected stealth_total (11 + 0 = 11)
        enemy = _make_actor("e", side="enemy", position=(10, 0),
                              passive_perception=99,
                              actions=[_basic_weapon_attack()])
        state = _state_with([actor, enemy], environment=env)
        score = offensive_ehp_hide(actor, _hide_action(), state)
        self.assertEqual(score, 0.0)

    def test_heavy_obscurement_with_evading_enemy_positive_score(self) -> None:
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        actor = _make_actor("a", dex_score=18,   # +4
                              skill_proficiencies=["stealth"],   # +PB 2 = +6
                              position=(2, 2),
                              actions=[_basic_weapon_attack()])
        # Average enemy: PP 10 < expected stealth_total 17 → can't auto-spot
        enemy = _make_actor("e", side="enemy", position=(3, 2),
                              passive_perception=10,
                              actions=[_basic_weapon_attack()])
        state = _state_with([actor, enemy], environment=env)
        score = offensive_ehp_hide(actor, _hide_action(), state)
        self.assertGreater(score, 0.0)

    def test_three_quarters_cover_also_triggers(self) -> None:
        actor = _make_actor("a", dex_score=18,
                              skill_proficiencies=["stealth"],
                              cover="three_quarters",
                              actions=[_basic_weapon_attack()])
        enemy = _make_actor("e", side="enemy", position=(3, 0),
                              passive_perception=10,
                              actions=[_basic_weapon_attack()])
        state = _state_with([actor, enemy])
        score = offensive_ehp_hide(actor, _hide_action(), state)
        self.assertGreater(score, 0.0)

    def test_higher_stealth_higher_score(self) -> None:
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        enemy_args = dict(side="enemy", position=(3, 2),
                            passive_perception=10,
                            actions=[_basic_weapon_attack()])
        # Low stealth (dex 10, +0)
        actor_low = _make_actor("low", dex_score=10, position=(2, 2),
                                   actions=[_basic_weapon_attack()])
        state_low = _state_with([actor_low, _make_actor("e1", **enemy_args)],
                                  environment=env)
        # High stealth (dex 20 = +5, with proficiency PB 2 → +7)
        actor_high = _make_actor("high", dex_score=20,
                                    skill_proficiencies=["stealth"],
                                    position=(2, 2),
                                    actions=[_basic_weapon_attack()])
        state_high = _state_with([actor_high, _make_actor("e2", **enemy_args)],
                                    environment=env)
        score_low = offensive_ehp_hide(actor_low, _hide_action(),
                                           state_low)
        score_high = offensive_ehp_hide(actor_high, _hide_action(),
                                            state_high)
        self.assertGreater(score_high, score_low)

    def test_out_of_range_enemy_no_defensive_contribution(self) -> None:
        """An enemy too far to reach this turn doesn't contribute to
        the defensive value of Hiding (no incoming attack to debuff)."""
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        actor = _make_actor("a", dex_score=18,
                              skill_proficiencies=["stealth"],
                              position=(2, 2),
                              actions=[_basic_weapon_attack()])
        # Enemy nearby (in-threat)
        near_enemy = _make_actor("near", side="enemy", position=(3, 2),
                                    passive_perception=10,
                                    actions=[_basic_weapon_attack()])
        state_near = _state_with([actor, near_enemy], environment=env)
        score_near = offensive_ehp_hide(actor, _hide_action(), state_near)

        # Enemy way out of range (speed 30 + reach 5 = 35 ft; place at
        # 100 ft = 20 squares away)
        far_enemy = _make_actor("far", side="enemy", position=(22, 2),
                                   passive_perception=10,
                                   actions=[_basic_weapon_attack()])
        state_far = _state_with([actor, far_enemy], environment=env)
        score_far = offensive_ehp_hide(actor, _hide_action(), state_far)

        # near contributes both offensive+defensive value; far only
        # offensive (defensive=0 since out of reach)
        self.assertGreater(score_near, score_far)


# ============================================================================
# Layer 3: offensive_ehp_search
# ============================================================================

class SearchScoringTest(unittest.TestCase):

    def test_no_hidden_enemies_returns_zero(self) -> None:
        actor = _make_actor("a", actions=[_basic_weapon_attack()])
        enemy = _make_actor("e", side="enemy")    # not hidden
        state = _state_with([actor, enemy])
        score = offensive_ehp_search(actor, _search_action(), state)
        self.assertEqual(score, 0.0)

    def test_no_scorable_attacks_returns_zero(self) -> None:
        actor = _make_actor("a")    # no actions
        enemy = _make_actor("e", side="enemy",
                              applied_conditions=[_hide_condition(15)])
        state = _state_with([actor, enemy])
        score = offensive_ehp_search(actor, _search_action(), state)
        self.assertEqual(score, 0.0)

    def test_low_stealth_high_perception_high_score(self) -> None:
        # WIS 18 (+4) + perception proficiency (PB 2) = +6
        actor = _make_actor("a", wis_score=18,
                              skill_proficiencies=["perception"],
                              actions=[_basic_weapon_attack()])
        # Stealth total 10 — d20 + 6 vs DC 10 = very high p_success
        enemy = _make_actor("e", side="enemy",
                              applied_conditions=[_hide_condition(10)])
        state = _state_with([actor, enemy])
        score = offensive_ehp_search(actor, _search_action(), state)
        self.assertGreater(score, 0.0)

    def test_high_stealth_low_perception_low_score(self) -> None:
        # Higher stealth (25) vs same actor → smaller p_reveal
        actor = _make_actor("a", wis_score=18,
                              skill_proficiencies=["perception"],
                              actions=[_basic_weapon_attack()])
        easy_enemy = _make_actor("e", side="enemy",
                                    applied_conditions=[_hide_condition(10)])
        hard_enemy = _make_actor("e", side="enemy",
                                    applied_conditions=[_hide_condition(25)])
        score_easy = offensive_ehp_search(
            actor, _search_action(),
            _state_with([actor, easy_enemy]))
        score_hard = offensive_ehp_search(
            actor, _search_action(),
            _state_with([actor, hard_enemy]))
        self.assertGreater(score_easy, score_hard)

    def test_multiple_hidden_enemies_score_sums(self) -> None:
        actor = _make_actor("a", wis_score=14,
                              actions=[_basic_weapon_attack()])
        e1 = _make_actor("e1", side="enemy",
                            applied_conditions=[_hide_condition(15)])
        e2 = _make_actor("e2", side="enemy",
                            applied_conditions=[_hide_condition(15)])
        state_one = _state_with([actor, e1])
        state_two = _state_with([actor, e1, e2])
        score_one = offensive_ehp_search(actor, _search_action(),
                                              state_one)
        score_two = offensive_ehp_search(actor, _search_action(),
                                              state_two)
        # Two hidden enemies → ~2x the score
        self.assertGreater(score_two, score_one)
        self.assertAlmostEqual(score_two / score_one, 2.0, places=1)

    def test_spell_invisible_NOT_counted(self) -> None:
        actor = _make_actor("a", wis_score=14,
                              actions=[_basic_weapon_attack()])
        # Spell-source Invisible — not bypassable by Search
        enemy = _make_actor("e", side="enemy",
                              applied_conditions=[_spell_invisible()])
        state = _state_with([actor, enemy])
        score = offensive_ehp_search(actor, _search_action(), state)
        self.assertEqual(score, 0.0)

    def test_mixed_invisible_only_hide_counted(self) -> None:
        actor = _make_actor("a", wis_score=14,
                              actions=[_basic_weapon_attack()])
        # Both Hide-source AND spell-source on same enemy → only one
        # Hide entry counted
        enemy = _make_actor("e", side="enemy",
                              applied_conditions=[
                                  _hide_condition(15),
                                  _spell_invisible(),
                              ])
        state = _state_with([actor, enemy])
        score = offensive_ehp_search(actor, _search_action(), state)
        # Should equal the score of just the Hide-source case
        only_hide = _make_actor("only", side="enemy",
                                   applied_conditions=[_hide_condition(15)])
        baseline = offensive_ehp_search(
            actor, _search_action(),
            _state_with([actor, only_hide]))
        self.assertAlmostEqual(score, baseline, places=2)


# ============================================================================
# Layer 4: score_candidate dispatch
# ============================================================================

class DispatchTest(unittest.TestCase):

    def test_hide_kind_routes_correctly(self) -> None:
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        actor = _make_actor("a", dex_score=18,
                              skill_proficiencies=["stealth"],
                              position=(2, 2),
                              actions=[_basic_weapon_attack()])
        enemy = _make_actor("e", side="enemy", position=(3, 2),
                              passive_perception=10,
                              actions=[_basic_weapon_attack()])
        state = _state_with([actor, enemy], environment=env)
        candidate = {"kind": "hide", "actor": actor, "target": actor,
                       "action": _hide_action()}
        score = score_candidate(candidate, state)
        # Should be > 0 (matches offensive_ehp_hide directly)
        self.assertGreater(score, 0.0)

    def test_search_kind_routes_correctly(self) -> None:
        actor = _make_actor("a", wis_score=16,
                              skill_proficiencies=["perception"],
                              actions=[_basic_weapon_attack()])
        enemy = _make_actor("e", side="enemy",
                              applied_conditions=[_hide_condition(12)])
        state = _state_with([actor, enemy])
        candidate = {"kind": "search", "actor": actor, "target": actor,
                       "action": _search_action()}
        score = score_candidate(candidate, state)
        self.assertGreater(score, 0.0)


# ============================================================================
# Layer 5: pipeline emits search candidate
# ============================================================================

class PipelineEmissionTest(unittest.TestCase):

    def test_explicit_search_action_emits_candidate(self) -> None:
        """An explicit search action on the actor's template should
        appear in the candidate pool."""
        from engine.core.pipeline import generate_candidates
        actor = _make_actor("a", actions=[_search_action(),
                                              _basic_weapon_attack()])
        enemy = _make_actor("e", side="enemy",
                              applied_conditions=[_hide_condition(15)])
        state = _state_with([actor, enemy])
        candidates = generate_candidates(actor, state, slot="action")
        search_cands = [c for c in candidates
                          if c.get("kind") == "search"]
        self.assertGreaterEqual(len(search_cands), 1)


if __name__ == "__main__":
    unittest.main()
