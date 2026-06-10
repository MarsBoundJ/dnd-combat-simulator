"""Encounter quality rubric (engine/core/encounter_quality.py).

Per-run analysis of tension/swing/deaths + aggregate grading across N runs.

Run via:
    python -m unittest tests.test_encounter_quality
"""
from __future__ import annotations

import unittest

from engine.core.encounter_quality import (
    aggregate_runs, analyze_run, format_quality, _quality_grade,
)
from engine.core.state import Actor, CombatState, Encounter


def _actor(actor_id, side, hp_max=40, is_dead=False):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    a = Actor(id=actor_id, name=actor_id,
              template={"id": f"t_{actor_id}", "abilities": ab,
                        "cr": {"proficiency_bonus": 2}, "actions": []},
              side=side, hp_current=hp_max if not is_dead else 0,
              hp_max=hp_max, ac=14, position=(0, 0), abilities=ab)
    a.is_dead = is_dead
    return a


def _state_with(events, pc_dead=False, termination="side_pc_victory"):
    pc = _actor("pc", "pc", hp_max=40)
    ally = _actor("ally", "pc", hp_max=40)
    foe = _actor("foe", "enemy", hp_max=100, is_dead=(termination == "side_pc_victory"))
    if pc_dead:
        pc.is_dead = True
        pc.hp_current = 0
    st = CombatState(encounter=Encounter(id="t", actors=[pc, ally, foe]))
    st.event_log = events
    st.termination_reason = termination
    st.round = max((e.get("round", 1) for e in events
                    if e.get("event") == "turn_start"), default=1)
    return st


class AnalyzeRunTest(unittest.TestCase):
    def test_win_outcome(self):
        st = _state_with([
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 20},
        ])
        r = analyze_run(st)
        self.assertEqual(r["outcome"], "WIN")
        self.assertEqual(r["rounds"], 1)
        self.assertEqual(r["pc_deaths"], 0)

    def test_loss_outcome(self):
        st = _state_with([
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 40},
        ], pc_dead=True, termination="side_enemy_victory")
        r = analyze_run(st)
        self.assertEqual(r["outcome"], "LOSS")
        self.assertEqual(r["pc_deaths"], 1)

    def test_tension_scales_with_damage(self):
        # Party takes 60/80 total HP worth of damage → tension ≈ 0.75.
        st = _state_with([
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 30},
            {"event": "damage_dealt", "actor": "foe", "target": "ally",
             "amount": 30},
        ])
        r = analyze_run(st)
        self.assertAlmostEqual(r["tension"], 0.75)

    def test_no_damage_zero_tension(self):
        st = _state_with([
            {"event": "turn_start", "actor": "pc", "round": 1},
        ])
        r = analyze_run(st)
        self.assertAlmostEqual(r["tension"], 0.0)

    def test_healing_recovers_hp_curve(self):
        # Take 30 damage, heal 20 → min HP was 50/80, tension = 30/80 = 0.375
        st = _state_with([
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 30},
            {"event": "turn_start", "actor": "ally", "round": 1},
            {"event": "healed", "target": "pc", "amount": 20},
        ])
        r = analyze_run(st)
        self.assertAlmostEqual(r["tension"], 30.0 / 80.0)

    def test_rounds_critical_counts_dangerous_rounds(self):
        # Round 1: foe deals 50 dmg to pc → party at 30/80 = 37.5% → critical.
        # Round 2: nothing → party still at 37.5% → critical.
        st = _state_with([
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 40},  # pc at 0, ally at 40 → 40/80 = 50% → barely not critical
        ])
        r = analyze_run(st)
        # 40/80 = exactly 50%, not strictly below → 0 critical rounds
        self.assertEqual(r["rounds_critical"], 0)

        st2 = _state_with([
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 40},
            {"event": "damage_dealt", "actor": "foe", "target": "ally",
             "amount": 1},  # party at 39/80 < 50% → critical
        ])
        r2 = analyze_run(st2)
        self.assertEqual(r2["rounds_critical"], 1)

    def test_swing_count_detects_reversals(self):
        # R1: party ahead (deals more than takes), R2: enemy ahead, R3: party.
        # That's 2 swings.
        st = _state_with([
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 20},
            {"event": "turn_start", "actor": "foe", "round": 2},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 30},
            {"event": "turn_start", "actor": "pc", "round": 3},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 25},
        ])
        r = analyze_run(st)
        self.assertEqual(r["swing_count"], 2)


class QualityGradeTest(unittest.TestCase):
    def test_sweet_spot_is_A(self):
        self.assertEqual(_quality_grade(
            win_rate=0.72, tpk_rate=0.03, death_rate=0.25,
            median_rounds=8, mean_tension=0.45), "A")

    def test_too_easy_is_F(self):
        self.assertEqual(_quality_grade(
            win_rate=0.98, tpk_rate=0.00, death_rate=0.02,
            median_rounds=4, mean_tension=0.1), "F")

    def test_too_hard_is_F(self):
        self.assertEqual(_quality_grade(
            win_rate=0.15, tpk_rate=0.60, death_rate=0.80,
            median_rounds=3, mean_tension=0.9), "F")

    def test_slog_is_F(self):
        self.assertEqual(_quality_grade(
            win_rate=0.70, tpk_rate=0.02, death_rate=0.20,
            median_rounds=25, mean_tension=0.3), "F")

    def test_moderate_imbalance_is_D(self):
        self.assertEqual(_quality_grade(
            win_rate=0.35, tpk_rate=0.12, death_rate=0.30,
            median_rounds=10, mean_tension=0.4), "D")

    def test_good_is_B(self):
        self.assertEqual(_quality_grade(
            win_rate=0.60, tpk_rate=0.04, death_rate=0.20,
            median_rounds=10, mean_tension=0.25), "B")


class AggregateTest(unittest.TestCase):
    def test_aggregate_computes_rates(self):
        runs = [
            {"outcome": "WIN", "rounds": 8, "pc_deaths": 1,
             "d_iff": 0.5, "difficulty_band": "Hard",
             "tension": 0.6, "rounds_critical": 2, "swing_count": 1},
            {"outcome": "WIN", "rounds": 6, "pc_deaths": 0,
             "d_iff": 0.3, "difficulty_band": "Medium",
             "tension": 0.3, "rounds_critical": 0, "swing_count": 0},
            {"outcome": "LOSS", "rounds": 4, "pc_deaths": 4,
             "d_iff": 1.2, "difficulty_band": "TPK",
             "tension": 1.0, "rounds_critical": 3, "swing_count": 2},
        ]
        agg = aggregate_runs(runs)
        self.assertAlmostEqual(agg["win_rate"], 2 / 3)
        self.assertAlmostEqual(agg["tpk_rate"], 1 / 3)
        self.assertAlmostEqual(agg["death_rate"], 2 / 3)
        self.assertEqual(agg["median_rounds"], 6)
        self.assertAlmostEqual(agg["mean_tension"], (0.6 + 0.3 + 1.0) / 3)

    def test_empty_runs(self):
        agg = aggregate_runs([])
        self.assertEqual(agg["n"], 0)
        self.assertEqual(agg["quality_grade"], "F")

    def test_format_quality_produces_output(self):
        runs = [
            {"outcome": "WIN", "rounds": 8, "pc_deaths": 0,
             "d_iff": 0.4, "difficulty_band": "Medium",
             "tension": 0.4, "rounds_critical": 1, "swing_count": 1},
        ]
        agg = aggregate_runs(runs)
        output = format_quality(agg)
        self.assertIn("Grade:", output)
        self.assertIn("Win rate:", output)
        self.assertIn("Tension:", output)


if __name__ == "__main__":
    unittest.main()
