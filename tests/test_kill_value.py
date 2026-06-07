"""Kill-value / threshold eHP — the "beat the math" layer.

Mean damage isn't enough to decide a kill: Fireball (8d6, mean 28) clears a
27-HP gnoll only ~62% of the time, but upcast to 10d6 it's ~94%. So spell value
must use the full damage DISTRIBUTION to compute P(kill), and a kill is worth
the creature's REMOVED future DPR (permanent action-denial), on top of the raw
HP-removed damage eHP.

Run via:
    python -m unittest tests.test_kill_value
"""
from __future__ import annotations

import unittest

from engine.ai.ehp_scoring import (
    dice_distribution, components_damage_distribution, p_total_at_least,
    _effective_kill_hp, kill_value, KILL_VALUE_ROUNDS,
    offensive_ehp_single_attack, offensive_ehp_save_attack,
)
from engine.ai.defensive_ehp import estimate_dpr
from engine.core.state import Actor, Encounter, CombatState


def _actor(actor_id="t", side="enemy", hp=27, hp_max=27, ac=15,
           actions=None, resist=None, vuln=None, immune=None):
    ab = {k: {"score": 12, "save": 1}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    tmpl = {"id": f"tpl_{actor_id}", "name": actor_id, "abilities": ab,
            "cr": {"proficiency_bonus": 2}, "actions": actions or [],
            "damage_resistances": resist or [],
            "damage_vulnerabilities": vuln or [],
            "damage_immunities": immune or []}
    return Actor(id=actor_id, name=actor_id, template=tmpl, side=side,
                 hp_current=hp, hp_max=hp_max, ac=ac, position=(0, 0),
                 abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class DistributionTest(unittest.TestCase):

    def test_8d6_distribution_shape(self):
        d = dice_distribution("8d6")
        self.assertAlmostEqual(sum(d.values()), 1.0, places=9)
        self.assertEqual(min(d), 8)
        self.assertEqual(max(d), 48)
        mean = sum(t * p for t, p in d.items())
        self.assertAlmostEqual(mean, 28.0, places=6)

    def test_modifier_shifts_distribution(self):
        d = dice_distribution("2d6", modifier=3)
        self.assertEqual(min(d), 5)        # 2 + 3
        self.assertEqual(max(d), 15)       # 12 + 3

    def test_p_at_least_matches_known_fireball_numbers(self):
        # The numbers that motivate upcast-to-threshold (vs a 27-HP gnoll).
        self.assertAlmostEqual(
            p_total_at_least(dice_distribution("8d6"), 27), 0.620, places=2)
        self.assertAlmostEqual(
            p_total_at_least(dice_distribution("10d6"), 27), 0.942, places=2)

    def test_upcasting_raises_p_kill(self):
        p8 = p_total_at_least(dice_distribution("8d6"), 27)
        p9 = p_total_at_least(dice_distribution("9d6"), 27)
        p10 = p_total_at_least(dice_distribution("10d6"), 27)
        self.assertLess(p8, p9)
        self.assertLess(p9, p10)

    def test_components_convolution(self):
        # 1d6 + 1d4 fire+cold combined: min 2, max 10.
        d = components_damage_distribution(
            [{"dice": "1d6", "modifier": 0}, {"dice": "1d4", "modifier": 0}])
        self.assertEqual(min(d), 2)
        self.assertEqual(max(d), 10)
        self.assertAlmostEqual(sum(d.values()), 1.0, places=9)


class EffectiveKillHPTest(unittest.TestCase):

    def test_normal(self):
        t = _actor(hp=27)
        self.assertEqual(_effective_kill_hp(t, "fire"), 27)

    def test_resistance_doubles_threshold(self):
        t = _actor(hp=27, resist=["fire"])
        self.assertEqual(_effective_kill_hp(t, "fire"), 54)

    def test_vulnerability_halves_threshold(self):
        t = _actor(hp=40, vuln=["fire"])
        self.assertEqual(_effective_kill_hp(t, "fire"), 20)

    def test_immunity_unkillable_by_type(self):
        t = _actor(hp=27, immune=["fire"])
        self.assertIsNone(_effective_kill_hp(t, "fire"))


class KillValueTest(unittest.TestCase):

    def test_kill_value_is_dpr_times_horizon_times_pkill(self):
        slam = {"id": "a_slam", "type": "weapon_attack",
                "pipeline": [{"primitive": "attack_roll",
                              "params": {"bonus": 5}},
                             {"primitive": "damage",
                              "params": {"dice": "2d6", "modifier": 3,
                                         "type": "slashing"}}]}
        t = _actor(actions=[slam])
        dpr = estimate_dpr(t)
        self.assertGreater(dpr, 0)
        self.assertAlmostEqual(kill_value(t, 1.0), dpr * KILL_VALUE_ROUNDS)
        self.assertAlmostEqual(kill_value(t, 0.5), dpr * KILL_VALUE_ROUNDS * 0.5)
        self.assertEqual(kill_value(t, 0.0), 0.0)


class ScorerKillBonusTest(unittest.TestCase):

    def _attack(self, dice="3d6", mod=0):
        return {"id": "a_bolt", "type": "weapon_attack",
                "pipeline": [{"primitive": "attack_roll",
                              "params": {"bonus": 8}},
                             {"primitive": "damage",
                              "params": {"dice": dice, "modifier": mod,
                                         "type": "force"}}]}

    def _enemy_with_dpr(self, hp):
        slam = {"id": "a_slam", "type": "weapon_attack",
                "pipeline": [{"primitive": "attack_roll", "params": {"bonus": 5}},
                             {"primitive": "damage",
                              "params": {"dice": "2d8", "modifier": 4,
                                         "type": "slashing"}}]}
        return _actor(hp=hp, hp_max=hp, actions=[slam])

    def test_killable_target_scores_above_capped_damage(self):
        # Low-HP target the attack can drop → score exceeds the HP-capped
        # damage by the kill bonus.
        attacker = _actor("att", side="pc")
        low = self._enemy_with_dpr(hp=6)
        st = _state([attacker, low])
        score = offensive_ehp_single_attack(attacker, low, self._attack(), st)
        # The capped damage alone is <= 6 (its HP); a real kill bonus pushes
        # the score well above 6.
        self.assertGreater(score, 6.0)

    def test_huge_hp_target_gets_no_kill_bonus(self):
        attacker = _actor("att", side="pc")
        tank = self._enemy_with_dpr(hp=500)
        st = _state([attacker, tank])
        score = offensive_ehp_single_attack(attacker, tank, self._attack(), st)
        # P(kill) ~ 0 at 500 HP → score is just the expected capped damage
        # (well under, say, 30).
        self.assertLess(score, 30.0)

    def test_more_dice_raises_score_near_threshold(self):
        # A target right at the threshold: upcasting (more dice) raises P(kill)
        # → higher score (the upcast-to-guarantee-the-kill incentive).
        attacker = _actor("att", side="pc")
        t1 = self._enemy_with_dpr(hp=27)
        t2 = self._enemy_with_dpr(hp=27)
        st = _state([attacker, t1, t2])
        low = offensive_ehp_single_attack(attacker, t1, self._attack("8d6"), st)
        high = offensive_ehp_single_attack(attacker, t2, self._attack("12d6"), st)
        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()
