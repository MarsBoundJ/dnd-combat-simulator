"""2024 DMG encounter XP budgeting — XP_BUDGET_PER_CHARACTER table, budget =
per-char × size, spend = SUM of raw stat-block XP (no 2014 multiplier), and
difficulty classification.

Anchored on the DMG 2024's own three worked examples and cross-checked
against live registry stat-block XP (Adult Red Dragon 18,000 / Fire Giant
5,000), which validates both the math and that the SRD values are 2024.

Run via:
    python -m unittest tests.test_encounter_budget
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.encounter_budget import (
    xp_budget, budgets_for, monster_xp, encounter_cost, many_creatures,
    classify_difficulty, encounter_report, DIFFICULTIES,
    XP_BUDGET_PER_CHARACTER,
)
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


# ============================================================================
# Budget table + math
# ============================================================================

class XpBudgetTest(unittest.TestCase):

    def test_table_covers_all_20_levels(self):
        self.assertEqual(sorted(XP_BUDGET_PER_CHARACTER), list(range(1, 21)))
        for lvl, row in XP_BUDGET_PER_CHARACTER.items():
            self.assertEqual(len(row), 3, f"level {lvl} row must be 3 tiers")
            low, mod, high = row
            self.assertTrue(low <= mod <= high,
                            f"level {lvl}: tiers must be non-decreasing")

    def test_budget_is_per_char_times_size(self):
        # L13: 2600/4200/5400 per char.
        self.assertEqual(xp_budget(13, 4, "low"), 2600 * 4)
        self.assertEqual(xp_budget(13, 4, "moderate"), 4200 * 4)
        self.assertEqual(xp_budget(13, 4, "high"), 5400 * 4)

    def test_budgets_for_returns_all_three(self):
        self.assertEqual(budgets_for(13, 4),
                         {"low": 10400, "moderate": 16800, "high": 21600})

    def test_difficulty_case_insensitive(self):
        self.assertEqual(xp_budget(5, 4, "HIGH"), xp_budget(5, 4, "high"))

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            xp_budget(13, 4, "deadly")           # 2014 tier, not 2024
        with self.assertRaises(ValueError):
            xp_budget(21, 4, "low")              # level out of range
        with self.assertRaises(ValueError):
            xp_budget(13, 0, "low")              # empty party


# ============================================================================
# DMG 2024 worked examples (the authoritative anchors)
# ============================================================================

class DMGWorkedExamplesTest(unittest.TestCase):

    def test_example1_low_4xL1_budget_200(self):
        # 50 × 4 = 200.
        self.assertEqual(xp_budget(1, 4, "low"), 200)
        # 1 Bugbear (200) / 2 Giant Wasps (100 each) / 6 Twig Blights (25) —
        # all summed RAW, no multiplier.
        self.assertEqual(encounter_cost([{"cr": {"xp": 200}}]), 200)
        self.assertEqual(encounter_cost([{"cr": {"xp": 100}}] * 2), 200)
        self.assertEqual(encounter_cost([{"cr": {"xp": 25}}] * 6), 150)

    def test_example2_moderate_5xL3_budget_1125(self):
        # 225 × 5 = 1125.
        self.assertEqual(xp_budget(3, 5, "moderate"), 1125)
        # 2 Nothics (450) + 9 Stirges (25) = 1125 — raw sum.
        cost = encounter_cost([{"cr": {"xp": 450}}] * 2
                              + [{"cr": {"xp": 25}}] * 9)
        self.assertEqual(cost, 1125)
        self.assertEqual(classify_difficulty(cost, 3, 5), "moderate")

    def test_example3_high_6xL15_budget_46800(self):
        # 7800 × 6 = 46800.
        self.assertEqual(xp_budget(15, 6, "high"), 46800)
        # 2 Adult Red Dragons (18000) + 2 Fire Giants (5000) = 46000.
        cost = encounter_cost([{"cr": {"xp": 18000}}] * 2
                              + [{"cr": {"xp": 5000}}] * 2)
        self.assertEqual(cost, 46000)
        self.assertEqual(classify_difficulty(cost, 15, 6), "high")


# ============================================================================
# Classification (budget = ceiling; lowest fitting tier)
# ============================================================================

class ClassifyTest(unittest.TestCase):

    def test_zero_is_none(self):
        self.assertEqual(classify_difficulty(0, 13, 4), "none")

    def test_at_low_ceiling_is_low(self):
        self.assertEqual(classify_difficulty(10400, 13, 4), "low")

    def test_just_over_low_is_moderate(self):
        self.assertEqual(classify_difficulty(10401, 13, 4), "moderate")

    def test_just_over_moderate_is_high(self):
        self.assertEqual(classify_difficulty(16801, 13, 4), "high")

    def test_over_high_ceiling_is_above_high(self):
        self.assertEqual(classify_difficulty(21601, 13, 4), "above_high")


# ============================================================================
# Many-creatures advisory (replaces the deleted 2014 multiplier)
# ============================================================================

class ManyCreaturesTest(unittest.TestCase):

    def test_at_two_per_char_not_flagged(self):
        self.assertFalse(many_creatures(8, 4))     # exactly 2/char

    def test_over_two_per_char_flagged(self):
        self.assertTrue(many_creatures(9, 4))      # >2/char


# ============================================================================
# Registry cross-check — proves stat-block XP is 2024 SRD
# ============================================================================

class RegistryXpTest(unittest.TestCase):

    def test_stat_block_xp_matches_dmg_anchors(self):
        reg = _registry()
        # Two independent DMG-example anchors.
        self.assertEqual(monster_xp(reg.get("monster", "m_adult_red_dragon")),
                         18000)
        self.assertEqual(monster_xp(reg.get("monster", "m_fire_giant")), 5000)

    def test_solo_adult_red_dragon_is_high_for_4xL13(self):
        reg = _registry()
        dragon = reg.get("monster", "m_adult_red_dragon")
        report = encounter_report([dragon], party_level=13, party_size=4)
        self.assertEqual(report["spent_xp"], 18000)
        # 18,000 sits above Moderate (16,800), under High (21,600) -> High,
        # with 3,600 XP of headroom. The climax is a textbook RAW High fight.
        self.assertEqual(report["difficulty"], "high")
        self.assertEqual(report["high_headroom"], 3600)
        self.assertFalse(report["many_creatures"])


if __name__ == "__main__":
    unittest.main()
