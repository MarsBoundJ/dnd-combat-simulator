"""eHP scoring v1 tests — offensive-eHP math + AI behavioral effects.

Three layers:
  1. Unit tests on the pure-math helpers (dice_mean, hit_probability,
     expected_damage_on_hit).
  2. Integration tests on score_candidate (full eHP for a candidate).
  3. Behavioral tests proving the AI now picks the right thing:
     - AI prefers a Blinded target (advantage → higher eHP).
     - Tactical preset picks the highest-EV attack between two options.
     - Aggression coefficient scales the score.

Run via:
    python -m unittest tests.test_ehp_scoring
"""
from __future__ import annotations

import unittest

from engine.ai import (
    score_candidate, best_action_against,
    aggression_coefficient, hit_probability, expected_damage_on_hit,
    score_candidates_v1,
)
from engine.ai.ehp_scoring import (
    dice_mean, crit_probability,
    offensive_ehp_single_attack, offensive_ehp_multiattack,
)
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Test helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy", hp: int = 50,
                ac: int = 15, abilities: dict | None = None,
                actions: list[dict] | None = None,
                archetype: str | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = abilities or {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    if archetype:
        template["behavior_profile"] = {"archetype": archetype}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac, abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _weapon_attack(action_id: str, bonus: int, dice: str,
                    modifier: int = 0, dmg_type: str = "slashing") -> dict:
    """Build a standard weapon_attack action dict."""
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier, "type": dmg_type},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


def _advantage_modifier(target_id: str) -> dict:
    """A registry entry granting advantage to attackers vs the owner —
    the shape Blinded uses (per condition definition)."""
    return {
        "primitive": "attack_modifier",
        "params": {"when": "target_is_self",
                    "modifier": "advantage_for_attacker"},
        "lifetime": "until_condition_ends",
        "source": {"type": "condition", "condition_id": "co_blinded",
                    "source_creature_id": None},
        "applied_at_round": 0,
        "owner_id": target_id,
    }


# ============================================================================
# Pure-math unit tests
# ============================================================================

class DiceMeanTest(unittest.TestCase):

    def test_d6_mean(self) -> None:
        self.assertAlmostEqual(dice_mean("1d6"), 3.5)

    def test_d8_mean(self) -> None:
        self.assertAlmostEqual(dice_mean("1d8"), 4.5)

    def test_2d6_mean(self) -> None:
        self.assertAlmostEqual(dice_mean("2d6"), 7.0)

    def test_empty_is_zero(self) -> None:
        self.assertEqual(dice_mean(""), 0.0)
        self.assertEqual(dice_mean(None), 0.0)

    def test_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            dice_mean("bogus")


class HitProbabilityTest(unittest.TestCase):

    def test_simple_50_50(self) -> None:
        # +5 to hit vs AC 16: need 11+ on d20 = 10/20 = 0.50
        self.assertAlmostEqual(hit_probability(5, 16, "normal"), 0.50)

    def test_advantage_raises_hit(self) -> None:
        normal = hit_probability(5, 16, "normal")
        adv = hit_probability(5, 16, "advantage")
        self.assertGreater(adv, normal,
                            "advantage should raise hit probability")
        # 0.50 → 1 - (1-0.5)^2 = 0.75
        self.assertAlmostEqual(adv, 0.75)

    def test_disadvantage_lowers_hit(self) -> None:
        normal = hit_probability(5, 16, "normal")
        dis = hit_probability(5, 16, "disadvantage")
        self.assertLess(dis, normal)
        # 0.50 → 0.5^2 = 0.25
        self.assertAlmostEqual(dis, 0.25)

    def test_nat_1_always_misses(self) -> None:
        # +20 vs AC 5: math says auto-hit, but nat 1 still misses → 19/20
        self.assertAlmostEqual(hit_probability(20, 5, "normal"), 19/20)

    def test_nat_20_always_hits(self) -> None:
        # +0 vs AC 30: math says auto-miss, but nat 20 still hits → 1/20
        self.assertAlmostEqual(hit_probability(0, 30, "normal"), 1/20)


class CritProbabilityTest(unittest.TestCase):

    def test_default_crit_threshold(self) -> None:
        self.assertAlmostEqual(crit_probability("normal"), 1/20)

    def test_advantage_doubles_crit_chance(self) -> None:
        # 1/20 → 1 - (19/20)^2 ≈ 0.0975
        self.assertAlmostEqual(crit_probability("advantage"), 1 - (19/20)**2)

    def test_improved_critical(self) -> None:
        # Threshold 19 means nat 19 and 20 both crit = 2/20
        self.assertAlmostEqual(crit_probability("normal", crit_threshold=19), 2/20)


# ============================================================================
# Expected damage extraction
# ============================================================================

class ExpectedDamageTest(unittest.TestCase):

    def test_simple_attack_damage(self) -> None:
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        target = _make_actor("t", hp=50)
        # 4.5 + 3 = 7.5 mean (with no crit chance folded in)
        self.assertAlmostEqual(expected_damage_on_hit(action, target,
                                                       crit_prob=0.0),
                                7.5)

    def test_resistance_halves(self) -> None:
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3,
                                 dmg_type="fire")
        target = _make_actor("t", hp=50, template_extras={
            "damage_resistances": ["fire"]
        })
        self.assertAlmostEqual(expected_damage_on_hit(action, target), 7.5 / 2)

    def test_immunity_zeros(self) -> None:
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3,
                                 dmg_type="fire")
        target = _make_actor("t", hp=50, template_extras={
            "damage_immunities": ["fire"]
        })
        self.assertEqual(expected_damage_on_hit(action, target), 0.0)

    def test_vulnerability_doubles(self) -> None:
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3,
                                 dmg_type="cold")
        target = _make_actor("t", hp=50, template_extras={
            "damage_vulnerabilities": ["cold"]
        })
        self.assertAlmostEqual(expected_damage_on_hit(action, target), 7.5 * 2)


# ============================================================================
# Offensive eHP for single attack + multiattack
# ============================================================================

class OffensiveEHPSingleTest(unittest.TestCase):

    def test_basic_single_attack(self) -> None:
        attacker = _make_actor("att", side="pc")
        target = _make_actor("def", hp=50, ac=15)
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        state = _state_with([attacker, target])

        ehp = offensive_ehp_single_attack(attacker, target, action, state)
        # +5 vs AC 15 = need 10+ = 11/20 = 0.55 hit prob
        # crit = 1/20; crit-given-hit ≈ 0.0909
        # Dmg on hit ≈ 4.5 * 1.0909 + 3 ≈ 7.909
        # eHP ≈ 0.55 * 7.909 ≈ 4.35
        self.assertAlmostEqual(ehp, 0.55 * (4.5 * (1 + 1/20/0.55) + 3), places=4)
        # Sanity: positive, less than damage-on-hit, not capped (target has 50 HP)
        self.assertGreater(ehp, 0)
        self.assertLess(ehp, 10)

    def test_blinded_target_raises_ehp(self) -> None:
        """The headline behavioral test: a target with the Blinded
        advantage modifier scores higher than an otherwise-identical
        non-blinded target."""
        attacker = _make_actor("att", side="pc")
        blinded = _make_actor("blinded", hp=50, ac=15)
        normal = _make_actor("normal", hp=50, ac=15)
        # Drop the Blinded modifier on `blinded`
        blinded.active_modifiers.append(_advantage_modifier("blinded"))
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        state = _state_with([attacker, blinded, normal])

        ehp_blinded = offensive_ehp_single_attack(attacker, blinded, action, state)
        ehp_normal = offensive_ehp_single_attack(attacker, normal, action, state)
        self.assertGreater(ehp_blinded, ehp_normal,
                            "Blinded target (advantage) should score higher eHP")

    def test_overkill_capped_at_target_hp(self) -> None:
        """A huge damage attack against a 1-HP target can only deliver 1 eHP."""
        attacker = _make_actor("att", side="pc")
        target = _make_actor("def", hp=50, ac=10)
        target.hp_current = 1
        # Massive attack: huge dice, easy to hit
        action = _weapon_attack("a", bonus=20, dice="10d12", modifier=10)
        state = _state_with([attacker, target])

        ehp = offensive_ehp_single_attack(attacker, target, action, state)
        self.assertLessEqual(ehp, 1.0,
                              "Overkill should cap at target's remaining HP")

    def test_dead_target_zero_ehp(self) -> None:
        attacker = _make_actor("att", side="pc")
        target = _make_actor("def", hp=50)
        target.hp_current = 0
        target.is_dead = True
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        state = _state_with([attacker, target])

        candidate = {"actor": attacker, "target": target, "action": action,
                      "kind": "weapon_attack"}
        self.assertEqual(score_candidate(candidate, state), 0.0)

    def test_no_attack_roll_returns_zero(self) -> None:
        """Actions without an attack_roll step (auto-hit spells) score 0
        in this v1 — eHP for non-attack actions lands in later PRs."""
        attacker = _make_actor("att", side="pc")
        target = _make_actor("def", hp=50)
        action = {"id": "no_roll", "type": "weapon_attack",
                  "pipeline": [{"primitive": "damage",
                                "params": {"dice": "1d8", "modifier": 3,
                                            "type": "slashing"}}]}
        state = _state_with([attacker, target])
        self.assertEqual(
            offensive_ehp_single_attack(attacker, target, action, state),
            0.0
        )


class OffensiveEHPMultiattackTest(unittest.TestCase):

    def test_multiattack_sums_subattacks(self) -> None:
        sub = _weapon_attack("a_sword", bonus=5, dice="1d8", modifier=3)
        multi = {"id": "a_multi", "type": "multiattack",
                  "count": 2, "sub_actions": ["a_sword", "a_sword"]}
        attacker = _make_actor("att", side="pc",
                                actions=[sub, multi])
        target = _make_actor("def", hp=50, ac=15)
        state = _state_with([attacker, target])

        ehp_single = offensive_ehp_single_attack(attacker, target, sub, state)
        ehp_multi = offensive_ehp_multiattack(attacker, target, multi, state)
        self.assertAlmostEqual(ehp_multi, 2 * ehp_single, places=4,
                                msg="2-attack multiattack ≈ 2x single attack")

    def test_multiattack_overkill_capped_at_target_hp(self) -> None:
        sub = _weapon_attack("a_sword", bonus=10, dice="1d8", modifier=5)
        multi = {"id": "a_multi", "type": "multiattack",
                  "count": 5, "sub_actions": ["a_sword"]}
        attacker = _make_actor("att", side="pc", actions=[sub, multi])
        target = _make_actor("def", hp=50, ac=10)
        target.hp_current = 3
        state = _state_with([attacker, target])

        ehp = offensive_ehp_multiattack(attacker, target, multi, state)
        # Even 5 attacks at high damage can only deliver 3 eHP total
        self.assertLessEqual(ehp, 3.0)


# ============================================================================
# Aggression coefficient
# ============================================================================

class AggressionCoefficientTest(unittest.TestCase):

    def test_berserker_is_most_aggressive(self) -> None:
        actor = _make_actor("a", archetype="berserker_fanatic")
        self.assertGreater(aggression_coefficient(actor), 1.0)

    def test_cowardly_is_less_aggressive(self) -> None:
        actor = _make_actor("a", archetype="cowardly_skirmisher")
        self.assertLess(aggression_coefficient(actor), 1.0)

    def test_default_no_archetype(self) -> None:
        actor = _make_actor("a")
        self.assertEqual(aggression_coefficient(actor), 1.0)


# ============================================================================
# Tactical preset picks highest-EV action
# ============================================================================

class TacticalPicksHighestEVTest(unittest.TestCase):

    def test_tactical_prefers_higher_damage_when_hit_chance_equal(self) -> None:
        """Two attacks both at +5; longsword (1d8+3) beats dagger (1d4+3) on eHP."""
        from engine.ai import pick_action
        longsword = _weapon_attack("a_long", bonus=5, dice="1d8", modifier=3)
        dagger = _weapon_attack("a_dag", bonus=5, dice="1d4", modifier=3)
        actor = _make_actor("a", side="pc", actions=[dagger, longsword])
        target = _make_actor("def", hp=50, ac=15, side="enemy")
        state = _state_with([actor, target])

        chosen = pick_action(actor, target, state, "tactical")
        self.assertEqual(chosen["id"], "a_long",
                          "Tactical should pick higher-EV longsword over dagger")

    def test_tactical_picks_more_accurate_when_damage_close(self) -> None:
        """If two attacks have similar damage, tactical prefers the one
        with the higher hit chance."""
        from engine.ai import pick_action
        accurate = _weapon_attack("a_acc", bonus=10, dice="1d6", modifier=3)
        wild = _weapon_attack("a_wild", bonus=0, dice="1d6", modifier=3)
        actor = _make_actor("a", side="pc", actions=[wild, accurate])
        target = _make_actor("def", hp=50, ac=18, side="enemy")
        state = _state_with([actor, target])

        chosen = pick_action(actor, target, state, "tactical")
        self.assertEqual(chosen["id"], "a_acc",
                          "Tactical should pick the more-accurate attack")

    def test_tactical_falls_back_with_no_target(self) -> None:
        """With no target, tactical falls back to default priority."""
        from engine.ai import pick_action
        attack = _weapon_attack("a_atk", bonus=5, dice="1d8")
        multi = {"id": "a_multi", "type": "multiattack",
                  "count": 2, "sub_actions": ["a_atk"]}
        actor = _make_actor("a", actions=[attack, multi])
        state = _state_with([actor])

        chosen = pick_action(actor, None, state, "tactical")
        self.assertEqual(chosen["id"], "a_multi",
                          "Without target, tactical falls back to default "
                          "(multiattack-preferred)")

    def test_best_action_against_returns_first_when_tied(self) -> None:
        """Two identical attacks: stable selection picks first listed."""
        a1 = _weapon_attack("a1", bonus=5, dice="1d8", modifier=3)
        a2 = _weapon_attack("a2", bonus=5, dice="1d8", modifier=3)
        actor = _make_actor("a", actions=[a1, a2])
        target = _make_actor("def", hp=50, ac=15)
        state = _state_with([actor, target])

        chosen = best_action_against(actor, target, state, [a1, a2])
        self.assertEqual(chosen["id"], "a1",
                          "Tied scores break to first-listed")


# ============================================================================
# score_candidates_v1 — full integration: eHP + preference bonuses
# ============================================================================

class ScoreCandidatesV1Test(unittest.TestCase):

    def test_ai_prefers_blinded_target(self) -> None:
        """End-to-end: given two equivalent targets, one Blinded, the AI
        scores the Blinded candidate higher and select_max picks them."""
        attacker = _make_actor("att", side="pc")
        blinded = _make_actor("blinded", side="enemy", hp=50, ac=15)
        normal = _make_actor("normal", side="enemy", hp=50, ac=15)
        blinded.active_modifiers.append(_advantage_modifier("blinded"))
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        state = _state_with([attacker, blinded, normal])

        candidates = [
            {"kind": "weapon_attack", "actor": attacker,
              "target": normal, "action": action},
            {"kind": "weapon_attack", "actor": attacker,
              "target": blinded, "action": action},
        ]
        scored = score_candidates_v1(candidates, attacker, state)
        # Find each by target id
        by_target = {c["target"].id: s for s, c in scored}
        self.assertGreater(by_target["blinded"], by_target["normal"],
                            "AI should score Blinded target higher than equivalent normal target")

    def test_aggression_scales_score(self) -> None:
        """Berserker aggression > 1.0 → eHP-based scores higher than default."""
        action = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        target = _make_actor("def", side="enemy", hp=50, ac=15)
        state = _state_with([target])

        attacker_default = _make_actor("att1", side="pc")
        attacker_berserker = _make_actor("att2", side="pc",
                                            archetype="berserker_fanatic")

        c_default = [{"kind": "weapon_attack", "actor": attacker_default,
                       "target": target, "action": action}]
        c_berserker = [{"kind": "weapon_attack", "actor": attacker_berserker,
                         "target": target, "action": action}]

        score_default = score_candidates_v1(c_default, attacker_default, state)[0][0]
        score_berserker = score_candidates_v1(c_berserker, attacker_berserker, state)[0][0]
        # Both get preference bonuses (single candidate matches "preferred"), so
        # subtract them out for a clean comparison.
        from engine.ai.decision_layer import (
            TARGET_PREFERENCE_BONUS, ACTION_PREFERENCE_BONUS
        )
        offset = TARGET_PREFERENCE_BONUS  # action has no id match here
        self.assertGreater(score_berserker - offset, score_default - offset,
                            "Berserker aggression should scale eHP higher")

    def test_empty_candidates_returns_empty(self) -> None:
        attacker = _make_actor("att", side="pc")
        state = _state_with([attacker])
        self.assertEqual(score_candidates_v1([], attacker, state), [])


if __name__ == "__main__":
    unittest.main()
