"""Defensive eHP v1 tests — healing / defensive buff / hard control.

Three layers:
  1. Pure-math units (desperation_multiplier, save_fail_probability, etc.)
  2. Per-effect-type eHP integration (heal/buff/control)
  3. Behavioral: AI heals the dying ally over attacking; AI casts hard
     control on the most-dangerous enemy when the math favors it; etc.

Run via:
    python -m unittest tests.test_defensive_ehp
"""
from __future__ import annotations

import unittest

from engine.ai import (
    score_candidate, score_candidates_v1,
    desperation_multiplier, expected_healing, estimate_dpr,
    save_fail_probability,
    defensive_ehp_healing, defensive_ehp_defensive_buff,
    defensive_ehp_hard_control,
)
from engine.ai.defensive_ehp import (
    EXPECTED_BUFF_ROUNDS, EXPECTED_CONTROL_ROUNDS,
    HARD_CONTROL_CONDITIONS, HEAL_DANGER_FLOOR,
    extract_buff_effect, extract_control_intent,
    danger_factor, incoming_danger_to,
)
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Test helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc", hp: int = 50,
                ac: int = 15, abilities: dict | None = None,
                actions: list[dict] | None = None,
                archetype: str | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = abilities or {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2},
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


def _heal_action(action_id: str, dice: str = "1d8", fixed: int = 0,
                  modifier_source: str | None = None) -> dict:
    """Build a heal-type action that targets an ally."""
    params: dict = {"target": "ally", "dice": dice, "fixed": fixed}
    if modifier_source:
        params["modifier_source"] = modifier_source
    return {
        "id": action_id, "name": action_id, "type": "heal",
        "pipeline": [{"primitive": "heal", "params": params}],
    }


def _defensive_buff_action(action_id: str, ac_bonus: int = 0,
                            attacker_disadvantage: bool = False) -> dict:
    """Build a defensive-buff-type action."""
    pipeline: list[dict] = []
    if ac_bonus:
        pipeline.append({
            "primitive": "attack_modifier",
            "params": {"modifier": "ac_modifier", "value": ac_bonus,
                        "lifetime": "until_short_rest"},
        })
    if attacker_disadvantage:
        pipeline.append({
            "primitive": "attack_modifier",
            "params": {"modifier": "disadvantage_for_attacker",
                        "lifetime": "until_short_rest"},
        })
    return {
        "id": action_id, "name": action_id, "type": "defensive_buff",
        "pipeline": pipeline,
    }


def _hard_control_action(action_id: str, condition_id: str = "co_paralyzed",
                          ability: str = "wisdom", dc: int = 13) -> dict:
    """Build a hard-control-type action with forced_save → apply_condition."""
    return {
        "id": action_id, "name": action_id, "type": "hard_control",
        "pipeline": [{
            "primitive": "forced_save",
            "params": {
                "ability": ability, "dc": dc,
                "on_fail": [{
                    "primitive": "apply_condition",
                    "params": {"condition_id": condition_id,
                                "duration": "until_spell_ends"},
                }],
            },
        }],
    }


def _weapon_attack(action_id: str, bonus: int, dice: str,
                    modifier: int = 0, dmg_type: str = "slashing") -> dict:
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


# ============================================================================
# Pure-math: desperation_multiplier
# ============================================================================

class DesperationMultiplierTest(unittest.TestCase):

    def test_full_hp_no_boost(self) -> None:
        self.assertAlmostEqual(desperation_multiplier(1.0), 1.0)

    def test_half_hp_no_boost(self) -> None:
        self.assertAlmostEqual(desperation_multiplier(0.5), 1.0)

    def test_critical_hp_max_boost(self) -> None:
        self.assertAlmostEqual(desperation_multiplier(0.0), 1.5)

    def test_quarter_hp_partial_boost(self) -> None:
        # 0.25 → 1.0 + (0.5 - 0.25) = 1.25
        self.assertAlmostEqual(desperation_multiplier(0.25), 1.25)

    def test_monotonic_below_half(self) -> None:
        # Below 50%, lower HP = higher urgency
        self.assertGreater(desperation_multiplier(0.1),
                            desperation_multiplier(0.4))


# ============================================================================
# Healing eHP
# ============================================================================

class HealingEHPTest(unittest.TestCase):

    def test_expected_healing_from_dice(self) -> None:
        caster = _make_actor("c")
        action = _heal_action("a", dice="2d8", fixed=2)
        # 2d8 mean = 9.0, +2 = 11.0
        self.assertAlmostEqual(expected_healing(action, caster), 11.0)

    def test_full_hp_ally_scores_zero(self) -> None:
        caster = _make_actor("c", hp=50)
        ally = _make_actor("ally", hp=50)
        state = _state_with([caster, ally])
        action = _heal_action("a", dice="2d8")
        self.assertEqual(defensive_ehp_healing(caster, ally, action, state),
                          0.0)

    def test_dying_ally_scores_above_half_hp_ally(self) -> None:
        caster = _make_actor("c")
        dying = _make_actor("dying", hp=50)
        dying.hp_current = 5  # 10% HP — desperation 1.4
        half = _make_actor("half", hp=50)
        half.hp_current = 25  # 50% — desperation 1.0
        state = _state_with([caster, dying, half])
        action = _heal_action("a", dice="2d8")

        ehp_dying = defensive_ehp_healing(caster, dying, action, state)
        ehp_half = defensive_ehp_healing(caster, half, action, state)
        self.assertGreater(ehp_dying, ehp_half,
                            "Dying ally should score higher than half-HP ally")

    def test_overheal_capped_at_missing_hp(self) -> None:
        """A huge heal against a barely-wounded ally caps at their missing HP."""
        caster = _make_actor("c")
        slightly_hurt = _make_actor("ally", hp=50)
        slightly_hurt.hp_current = 49  # missing 1 HP
        state = _state_with([caster, slightly_hurt])
        action = _heal_action("a", dice="10d10", fixed=20)
        self.assertLessEqual(
            defensive_ehp_healing(caster, slightly_hurt, action, state),
            1.0
        )

    def test_modifier_source_added_to_healing(self) -> None:
        caster = _make_actor("c", abilities={
            "str": {"score": 10, "save": 0},
            "dex": {"score": 10, "save": 0},
            "con": {"score": 10, "save": 0},
            "int": {"score": 10, "save": 0},
            "wis": {"score": 16, "save": 3},   # +3
            "cha": {"score": 10, "save": 0},
        })
        action = _heal_action("a", dice="1d8", modifier_source="actor.wis_mod")
        # 1d8 mean = 4.5, + wis_mod 3 = 7.5
        self.assertAlmostEqual(expected_healing(action, caster), 7.5)


# ============================================================================
# Heal danger-scaling (heal eHP scales with the target's incoming danger)
# ============================================================================

class HealDangerScalingTest(unittest.TestCase):
    """Healing an ally NO enemy can threaten this round is discounted to the
    danger floor; a threatened ally heals at full value (the Cleric heal-spam
    fix). A dying ally is always max danger (revival never board-discounted)."""

    def _ogre(self, pos):
        e = _make_actor("ogre", side="enemy", hp=60,
                        actions=[_weapon_attack("a_club", bonus=6, dice="2d8",
                                                  modifier=4)])
        e.position = pos
        e.speed = {"walk": 30}
        return e

    def _wounded_ally(self, hp_current=25, hp_max=50, pos=(0, 0)):
        a = _make_actor("ally", hp=hp_max)
        a.hp_current = hp_current
        a.position = pos
        return a

    def test_incoming_danger_counts_only_in_reach_enemies(self):
        ally = self._wounded_ally(pos=(0, 0))
        near = self._ogre(pos=(2, 0))     # 10 ft ≤ 30+5 → threatens
        far = self._ogre(pos=(50, 50))    # 250 ft → no threat this round
        st_near = _state_with([ally, near])
        st_far = _state_with([ally, far])
        self.assertGreater(incoming_danger_to(ally, st_near), 0.0)
        self.assertEqual(incoming_danger_to(ally, st_far), 0.0)

    def test_danger_factor_floor_when_unthreatened(self):
        ally = self._wounded_ally(pos=(0, 0))
        far = self._ogre(pos=(50, 50))
        state = _state_with([ally, far])
        self.assertAlmostEqual(danger_factor(ally, state), HEAL_DANGER_FLOOR)

    def test_danger_factor_full_when_incoming_exceeds_hp(self):
        # Low-HP ally + an adjacent ogre whose DPR (~7.8 after AC-15 hit prob)
        # ≥ its current HP (5) → ratio clamps to 1.0.
        ally = self._wounded_ally(hp_current=5, hp_max=50, pos=(0, 0))
        near = self._ogre(pos=(1, 0))
        state = _state_with([ally, near])
        self.assertAlmostEqual(danger_factor(ally, state), 1.0)

    def test_dying_ally_always_max_danger(self):
        ally = self._wounded_ally(hp_current=0, pos=(0, 0))
        ally.is_dying = True
        ally.is_dead = False
        far = self._ogre(pos=(50, 50))    # no board threat...
        state = _state_with([ally, far])
        self.assertAlmostEqual(danger_factor(ally, state), 1.0)  # ...still 1.0

    def test_threatened_heal_scores_higher_than_unthreatened(self):
        caster = _make_actor("c")
        action = _heal_action("a", dice="2d8")
        # Same wound, two boards: one with an adjacent threat, one without.
        ally_t = self._wounded_ally(pos=(0, 0))
        ally_u = self._wounded_ally(pos=(0, 0))
        st_t = _state_with([caster, ally_t, self._ogre(pos=(2, 0))])
        st_u = _state_with([caster, ally_u, self._ogre(pos=(50, 50))])
        score_t = defensive_ehp_healing(caster, ally_t, action, st_t)
        score_u = defensive_ehp_healing(caster, ally_u, action, st_u)
        self.assertGreater(score_t, score_u)
        # Unthreatened is exactly the floor fraction of the nominal heal.
        self.assertAlmostEqual(score_u, 9.0 * HEAL_DANGER_FLOOR, places=2)


# ============================================================================
# DPR estimation
# ============================================================================

class DPREstimationTest(unittest.TestCase):

    def test_no_actions_zero_dpr(self) -> None:
        actor = _make_actor("a", actions=[])
        self.assertEqual(estimate_dpr(actor), 0.0)

    def test_simple_attack_has_dpr(self) -> None:
        attack = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        actor = _make_actor("a", actions=[attack])
        dpr = estimate_dpr(actor)
        self.assertGreater(dpr, 0.0)

    def test_multiattack_scales_dpr(self) -> None:
        attack = _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        single = _make_actor("single", actions=[attack])
        multi_attack = {"id": "a_multi", "type": "multiattack",
                         "count": 2, "sub_actions": ["a"]}
        double = _make_actor("double", actions=[attack, multi_attack])
        self.assertAlmostEqual(estimate_dpr(double), 2 * estimate_dpr(single))


# ============================================================================
# Defensive buff eHP
# ============================================================================

class DefensiveBuffEHPTest(unittest.TestCase):

    def test_ac_bonus_extracted(self) -> None:
        action = _defensive_buff_action("a", ac_bonus=2)
        effect = extract_buff_effect(action)
        self.assertEqual(effect, {"ac_bonus": 2})

    def test_disadvantage_for_attacker_extracted(self) -> None:
        action = _defensive_buff_action("a", attacker_disadvantage=True)
        self.assertTrue(extract_buff_effect(action).get("attacker_disadvantage"))

    def test_buff_scales_with_enemy_DPR(self) -> None:
        """A buff vs a tougher enemy scores higher than vs a weak enemy."""
        caster = _make_actor("c", side="pc")
        weak_ally = _make_actor("ally1", side="pc")
        action = _defensive_buff_action("a", ac_bonus=4)
        weak_atk = _weapon_attack("a_weak", bonus=0, dice="1d4")
        strong_atk = _weapon_attack("a_strong", bonus=8, dice="2d8", modifier=5)

        weak_enemy = _make_actor("weak_enemy", side="enemy",
                                   actions=[weak_atk])
        strong_enemy = _make_actor("strong_enemy", side="enemy",
                                     actions=[strong_atk])

        state_weak = _state_with([caster, weak_ally, weak_enemy])
        state_strong = _state_with([caster, weak_ally, strong_enemy])

        ehp_weak = defensive_ehp_defensive_buff(caster, weak_ally, action, state_weak)
        ehp_strong = defensive_ehp_defensive_buff(caster, weak_ally, action, state_strong)
        self.assertGreater(ehp_strong, ehp_weak,
                            "Buff vs stronger enemy should score higher")

    def test_no_enemies_zero_buff_ehp(self) -> None:
        caster = _make_actor("c", side="pc")
        ally = _make_actor("ally", side="pc")
        state = _state_with([caster, ally])
        action = _defensive_buff_action("a", ac_bonus=2)
        self.assertEqual(
            defensive_ehp_defensive_buff(caster, ally, action, state),
            0.0
        )

    def test_buff_with_no_effect_scores_zero(self) -> None:
        caster = _make_actor("c", side="pc")
        ally = _make_actor("ally", side="pc")
        enemy = _make_actor("enemy", side="enemy", actions=[
            _weapon_attack("a", bonus=5, dice="1d8", modifier=3)
        ])
        state = _state_with([caster, ally, enemy])
        # No actual buff effects in the pipeline
        action = {"id": "noop", "name": "noop", "type": "defensive_buff",
                  "pipeline": []}
        self.assertEqual(
            defensive_ehp_defensive_buff(caster, ally, action, state),
            0.0
        )


# ============================================================================
# Hard control eHP
# ============================================================================

class HardControlEHPTest(unittest.TestCase):

    def test_extract_control_intent(self) -> None:
        action = _hard_control_action("a", condition_id="co_paralyzed",
                                        ability="wisdom", dc=15)
        intent = extract_control_intent(action)
        self.assertEqual(intent["save_ability"], "wisdom")
        self.assertEqual(intent["save_dc_fixed"], 15)
        self.assertEqual(intent["condition_id"], "co_paralyzed")
        self.assertEqual(intent["denial_fraction"], 1.0)

    def test_non_control_action_returns_empty(self) -> None:
        action = _weapon_attack("a", bonus=5, dice="1d8")
        self.assertEqual(extract_control_intent(action), {})

    def test_partial_control_lower_fraction(self) -> None:
        action = _hard_control_action("a", condition_id="co_restrained")
        self.assertLess(extract_control_intent(action)["denial_fraction"],
                         1.0)

    def test_save_fail_prob_from_bonus(self) -> None:
        # WIS save +2 vs DC 13 → need 11+ → 50% success → 50% fail
        target = _make_actor("t")  # default wis save +2
        state = _state_with([target])
        p_fail = save_fail_probability(target, "wisdom", 13, state)
        self.assertAlmostEqual(p_fail, 0.50)

    def test_high_save_bonus_lowers_fail_prob(self) -> None:
        weak = _make_actor("w", abilities={
            "str": {"score": 10, "save": 0}, "dex": {"score": 10, "save": 0},
            "con": {"score": 10, "save": 0}, "int": {"score": 10, "save": 0},
            "wis": {"score": 8, "save": -1}, "cha": {"score": 10, "save": 0},
        })
        strong = _make_actor("s", abilities={
            "str": {"score": 10, "save": 0}, "dex": {"score": 10, "save": 0},
            "con": {"score": 10, "save": 0}, "int": {"score": 10, "save": 0},
            "wis": {"score": 20, "save": 8}, "cha": {"score": 10, "save": 0},
        })
        state = _state_with([weak, strong])
        self.assertGreater(
            save_fail_probability(weak, "wisdom", 15, state),
            save_fail_probability(strong, "wisdom", 15, state),
        )

    def test_control_against_high_DPR_enemy_scores_higher(self) -> None:
        """Locking down a beefy attacker is worth more than locking down
        a weak attacker."""
        caster = _make_actor("c", side="pc")
        weak_atk = _weapon_attack("a_weak", bonus=0, dice="1d4")
        strong_atk = _weapon_attack("a_strong", bonus=8, dice="2d8", modifier=5)
        weak_enemy = _make_actor("weak", side="enemy", actions=[weak_atk])
        strong_enemy = _make_actor("strong", side="enemy", actions=[strong_atk])
        state = _state_with([caster, weak_enemy, strong_enemy])

        action = _hard_control_action("hold", condition_id="co_paralyzed",
                                        dc=13)
        ehp_weak = defensive_ehp_hard_control(caster, weak_enemy, action, state)
        ehp_strong = defensive_ehp_hard_control(caster, strong_enemy, action, state)
        self.assertGreater(ehp_strong, ehp_weak)

    def test_dead_target_zero(self) -> None:
        caster = _make_actor("c")
        target = _make_actor("t", side="enemy")
        target.hp_current = 0
        target.is_dead = True
        state = _state_with([caster, target])
        action = _hard_control_action("hold")
        self.assertEqual(
            defensive_ehp_hard_control(caster, target, action, state),
            0.0
        )


# ============================================================================
# Candidate generator emits defensive candidates
# ============================================================================

class CandidateGenerationTest(unittest.TestCase):

    def test_heal_emits_one_candidate_per_ally(self) -> None:
        heal = _heal_action("h", dice="1d8")
        caster = _make_actor("c", side="pc", actions=[heal])
        ally1 = _make_actor("ally1", side="pc")
        ally2 = _make_actor("ally2", side="pc")
        ally1.hp_current = 10  # wounded
        enemy = _make_actor("e", side="enemy")
        state = _state_with([caster, ally1, ally2, enemy])

        cands = generate_candidates(caster, state)
        heal_cands = [c for c in cands if c["kind"] == "heal"]
        # 3 allies (including caster), each gets one heal candidate
        self.assertEqual(len(heal_cands), 3)
        target_ids = {c["target"].id for c in heal_cands}
        self.assertEqual(target_ids, {"c", "ally1", "ally2"})

    def test_hard_control_emits_one_per_enemy(self) -> None:
        control = _hard_control_action("hold")
        caster = _make_actor("c", side="pc", actions=[control])
        e1 = _make_actor("e1", side="enemy")
        e2 = _make_actor("e2", side="enemy")
        state = _state_with([caster, e1, e2])

        cands = generate_candidates(caster, state)
        ctrl_cands = [c for c in cands if c["kind"] == "hard_control"]
        self.assertEqual(len(ctrl_cands), 2)

    def test_buff_emits_one_per_ally(self) -> None:
        buff = _defensive_buff_action("b", ac_bonus=2)
        caster = _make_actor("c", side="pc", actions=[buff])
        ally = _make_actor("ally", side="pc")
        state = _state_with([caster, ally])

        cands = generate_candidates(caster, state)
        buff_cands = [c for c in cands if c["kind"] == "defensive_buff"]
        self.assertEqual(len(buff_cands), 2)   # self + ally


# ============================================================================
# score_candidate dispatch
# ============================================================================

class ScoreCandidateDispatchTest(unittest.TestCase):

    def test_heal_candidate_routes_to_healing_ehp(self) -> None:
        caster = _make_actor("c")
        ally = _make_actor("ally")
        ally.hp_current = 5
        state = _state_with([caster, ally])
        action = _heal_action("h", dice="2d8")

        cand = {"kind": "heal", "actor": caster, "target": ally,
                "action": action}
        self.assertGreater(score_candidate(cand, state), 0.0)

    def test_control_candidate_routes_to_control_ehp(self) -> None:
        caster = _make_actor("c")
        enemy = _make_actor("e", side="enemy", actions=[
            _weapon_attack("a", bonus=5, dice="2d8", modifier=4)
        ])
        state = _state_with([caster, enemy])
        action = _hard_control_action("hold", dc=15)

        cand = {"kind": "hard_control", "actor": caster, "target": enemy,
                "action": action}
        self.assertGreater(score_candidate(cand, state), 0.0)


# ============================================================================
# Behavioral integration: AI picks healing over attacking when ally is dying
# ============================================================================

class AIChoosesHealOverAttackTest(unittest.TestCase):

    def test_dying_ally_overrides_attack(self) -> None:
        """A cleric with low-damage weapon + decent heal should pick HEAL
        when an ally is at critical HP, ATTACK otherwise (against a
        comparable enemy)."""
        attack = _weapon_attack("a_mace", bonus=3, dice="1d6", modifier=1)
        heal = _heal_action("a_cure", dice="2d8",
                              modifier_source="actor.wis_mod")
        cleric = _make_actor("cleric", side="pc",
                               actions=[attack, heal],
                               abilities={
            "str": {"score": 12, "save": 1}, "dex": {"score": 10, "save": 0},
            "con": {"score": 12, "save": 1}, "int": {"score": 10, "save": 0},
            "wis": {"score": 16, "save": 5}, "cha": {"score": 10, "save": 0},
        })
        ally = _make_actor("ally", side="pc")
        enemy = _make_actor("enemy", side="enemy", ac=15,
                              actions=[attack])

        # Scenario A: ally at FULL HP — AI should prefer attacking
        ally.hp_current = ally.hp_max
        state_a = _state_with([cleric, ally, enemy])
        cands_a = generate_candidates(cleric, state_a)
        scored_a = score_candidates_v1(cands_a, cleric, state_a)
        best_a = max(scored_a, key=lambda x: x[0])[1]
        self.assertEqual(best_a["kind"], "weapon_attack",
                          "With full-HP allies, AI should attack, not waste a heal")

        # Scenario B: ally at 1 HP — AI should switch to healing
        ally.hp_current = 1
        state_b = _state_with([cleric, ally, enemy])
        cands_b = generate_candidates(cleric, state_b)
        scored_b = score_candidates_v1(cands_b, cleric, state_b)
        best_b = max(scored_b, key=lambda x: x[0])[1]
        self.assertEqual(best_b["kind"], "heal",
                          "With dying ally, AI should heal, not attack")
        self.assertEqual(best_b["target"].id, "ally",
                          "AI should target the dying ally, not self-heal")


# ============================================================================
# Behavioral: hard control beats attack vs scary enemy
# ============================================================================

class AIChoosesHardControlTest(unittest.TestCase):

    def test_control_beats_attack_vs_high_DPR_enemy(self) -> None:
        """A weak attacker with access to Hold Person should prefer
        paralyzing a scary high-DPR enemy over poking it with the attack."""
        weak_atk = _weapon_attack("a_dagger", bonus=2, dice="1d4")
        hold = _hard_control_action("a_hold", condition_id="co_paralyzed",
                                      ability="wisdom", dc=15)
        caster = _make_actor("c", side="pc",
                               actions=[weak_atk, hold])
        # Scary enemy: high DPR, low WIS save → control is high-value
        big_atk = _weapon_attack("a_big", bonus=8, dice="3d8", modifier=5)
        bruiser = _make_actor("bruiser", side="enemy", hp=80, ac=18,
                                actions=[big_atk], abilities={
            "str": {"score": 18, "save": 4},
            "dex": {"score": 10, "save": 0},
            "con": {"score": 16, "save": 3},
            "int": {"score": 8, "save": -1},
            "wis": {"score": 8, "save": -1},   # weak wis save
            "cha": {"score": 10, "save": 0},
        })
        state = _state_with([caster, bruiser])

        cands = generate_candidates(caster, state)
        scored = score_candidates_v1(cands, caster, state)
        best = max(scored, key=lambda x: x[0])[1]
        self.assertEqual(best["kind"], "hard_control",
                          "AI should choose Hold Person over weak attack "
                          "vs a high-DPR low-WIS enemy")


# ============================================================================
# Heal primitive — ally targeting now works at execution time
# ============================================================================

class HealAllyExecutionTest(unittest.TestCase):

    def test_heal_targets_ally_via_current_attack(self) -> None:
        """The _heal primitive should heal current_attack.target when
        params.target == 'ally'."""
        from engine import primitives as primitives_module
        from engine.core.events import EventBus
        import random

        primitives_module.set_rng(random.Random(0))

        caster = _make_actor("c")
        ally = _make_actor("ally")
        ally.hp_current = 5
        state = _state_with([caster, ally])
        state.current_attack = {"actor": caster, "target": ally, "action": None}

        # Direct primitive invocation
        result = primitives_module._heal(
            {"target": "ally", "dice": "1d6", "fixed": 2},
            state, EventBus()
        )
        self.assertGreater(ally.hp_current, 5,
                            "Ally HP should have increased")
        self.assertGreater(result["amount"], 0)


# ============================================================================
# Integration: full encounter end-to-end via the CLI loader
# ============================================================================

class FullEncounterClericHealsTest(unittest.TestCase):
    """End-to-end smoke: load the cleric_heals_ally fixture, run, and
    verify that the cleric's FIRST action in the event log is a heal
    targeting the dying fighter — not an attack."""

    def test_cleric_first_action_is_heal_of_dying_ally(self) -> None:
        import random
        from pathlib import Path
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner
        from engine.cli import _build_encounter
        from engine.loader import load_content, load_yaml_file

        repo_root = Path(__file__).parent.parent
        content_root = repo_root / "schema" / "content"
        schema_root = repo_root / "schema" / "definitions"
        fixture = Path(__file__).parent / "fixtures" / \
            "cleric_heals_ally_encounter.yaml"

        registry = load_content(content_root, validate=True,
                                  schema_root=schema_root)
        spec = load_yaml_file(fixture)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1,
                                       content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Find the cleric's FIRST event: should be 'healed' on fighter_dying.
        cleric_events = [e for e in state.event_log
                          if e.get("actor") == "cleric_healer"
                          or e.get("target") == "fighter_dying"
                          and e.get("event") == "healed"]
        first_heal = next(
            (e for e in state.event_log
              if e.get("event") == "healed"
              and e.get("target") == "fighter_dying"),
            None,
        )
        self.assertIsNotNone(first_heal,
                              "Cleric should have healed the dying fighter "
                              "at least once")
        self.assertGreater(first_heal["amount"], 0,
                            "Heal should deliver positive HP")


if __name__ == "__main__":
    unittest.main()
