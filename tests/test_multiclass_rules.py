"""B1 oracle tests — lock the SRD 5.2.1 multiclass rules as tested data.

This is the §9 G#1 BLOCKER made concrete: the Multiclass Spellcaster table and
the half-caster rounding are asserted DIRECTLY against the printed SRD (table +
the book's own worked example), not against any prose summary. If a future edit
drifts the table or flips the rounding, these fail loudly.

SRD sources (docs/srd/SRD_CC_v5.2.1.pdf): rules pages 24-25, the Multiclass
Spellcaster table page 26, per-class Primary Ability / Hit Point Die pages 28-78.
"""
from __future__ import annotations

import unittest

from engine.core import multiclass as mc
from engine.pc_schema import _compute_hp


class SpellcasterTableTranscriptionTest(unittest.TestCase):
    """The table must match the SRD page 26 cell-for-cell."""

    def test_has_all_twenty_levels(self):
        self.assertEqual(sorted(mc.MULTICLASS_SPELL_SLOTS), list(range(1, 21)))
        for lvl, row in mc.MULTICLASS_SPELL_SLOTS.items():
            self.assertEqual(len(row), 9, f"level {lvl} row must have 9 columns")

    def test_specific_rows_match_srd_page_26(self):
        T = mc.MULTICLASS_SPELL_SLOTS
        # Spot-check the rows that pin the table's shape.
        self.assertEqual(T[1],  (2, 0, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(T[2],  (3, 0, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(T[3],  (4, 2, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(T[5],  (4, 3, 2, 0, 0, 0, 0, 0, 0))
        self.assertEqual(T[11], (4, 3, 3, 3, 2, 1, 0, 0, 0))
        # L11 and L12 are identical on the SRD table (a key "no new slot" row).
        self.assertEqual(T[11], T[12])
        self.assertEqual(T[13], T[14])
        self.assertEqual(T[15], T[16])
        # L18 bumps the 5th-level column from 2 → 3.
        self.assertEqual(T[17], (4, 3, 3, 3, 2, 1, 1, 1, 1))
        self.assertEqual(T[18], (4, 3, 3, 3, 3, 1, 1, 1, 1))
        self.assertEqual(T[19], (4, 3, 3, 3, 3, 2, 1, 1, 1))
        self.assertEqual(T[20], (4, 3, 3, 3, 3, 2, 2, 1, 1))

    def test_first_column_is_always_capped_at_four(self):
        # The full-caster shape: 1st-level slots climb 2→3→4 then hold at 4.
        firsts = [mc.MULTICLASS_SPELL_SLOTS[l][0] for l in range(1, 21)]
        self.assertEqual(firsts[:3], [2, 3, 4])
        self.assertTrue(all(f == 4 for f in firsts[2:]))


class HalfCasterRoundingTest(unittest.TestCase):
    """THE blocker: Paladin/Ranger contribute ceil(level/2) — round UP."""

    def test_half_caster_contribution_rounds_up(self):
        # ceil(level/2): 1→1, 2→1, 3→2, 4→2, 5→3, 6→3 …
        for lvl, expected in [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3),
                              (6, 3), (7, 4), (19, 10), (20, 10)]:
            self.assertEqual(mc.spell_slot_contribution("c_paladin", lvl),
                             expected, f"paladin {lvl}")
            self.assertEqual(mc.spell_slot_contribution("c_ranger", lvl),
                             expected, f"ranger {lvl}")

    def test_round_up_not_round_down_at_paladin_1(self):
        # The discriminating case (plan-named). Round-UP: Pal1 contributes 1.
        # Round-down (the 2014 rule / G#1's garble) would give 0 — assert it's 1.
        self.assertEqual(mc.spell_slot_contribution("c_paladin", 1), 1)
        self.assertNotEqual(mc.spell_slot_contribution("c_paladin", 1), 0)

    def test_full_casters_contribute_full_level(self):
        for cid in ("c_bard", "c_cleric", "c_druid", "c_sorcerer", "c_wizard"):
            self.assertEqual(mc.spell_slot_contribution(cid, 7), 7)

    def test_pact_and_non_casters_contribute_zero_to_shared_pool(self):
        # Warlock Pact Magic is a separate pool (B5); martials cast nothing.
        for cid in ("c_warlock", "c_barbarian", "c_fighter", "c_monk", "c_rogue"):
            self.assertEqual(mc.spell_slot_contribution(cid, 5), 0)


class CombinedLevelAndSlotsOracleTest(unittest.TestCase):
    """Named oracle cases — each pins combined level + the resulting slots."""

    def test_srd_worked_example_ranger4_sorcerer3(self):
        # SRD page 25-26 VERBATIM: "level 4 Ranger / level 3 Sorcerer … count
        # as a level 5 character … four level 1 spell slots, three level 2
        # slots, and two level 3 slots."
        classes = [("c_ranger", 4), ("c_sorcerer", 3)]
        self.assertEqual(mc.combined_caster_level(classes), 5)
        self.assertEqual(mc.multiclass_spell_slots(classes),
                         {1: 4, 2: 3, 3: 2})

    def test_paladin1_sorcerer1_is_combined_level_2(self):
        # Round-UP → ceil(1/2)=1 + 1 = 2 → table row 2 → three 1st-level slots.
        # (Round-down would give combined level 1 → only two slots.)
        classes = [("c_paladin", 1), ("c_sorcerer", 1)]
        self.assertEqual(mc.combined_caster_level(classes), 2)
        self.assertEqual(mc.multiclass_spell_slots(classes), {1: 3})

    def test_paladin2_sorcerer1_also_combined_level_2(self):
        # ceil(2/2)=1 + 1 = 2 — same as Paladin1/Sorc1, the round-UP signature
        # (under round-down these two cases would DIFFER: 2 vs 1).
        classes = [("c_paladin", 2), ("c_sorcerer", 1)]
        self.assertEqual(mc.combined_caster_level(classes), 2)
        self.assertEqual(mc.multiclass_spell_slots(classes), {1: 3})

    def test_fighter2_wizard3_combined_level_3(self):
        # Fighter (none) contributes 0; Wizard (full) contributes 3.
        classes = [("c_fighter", 2), ("c_wizard", 3)]
        self.assertEqual(mc.combined_caster_level(classes), 3)
        self.assertEqual(mc.multiclass_spell_slots(classes), {1: 4, 2: 2})

    def test_no_caster_classes_gives_empty_pool(self):
        self.assertEqual(
            mc.multiclass_spell_slots([("c_fighter", 5), ("c_rogue", 5)]), {})


class ProficiencyBonusTest(unittest.TestCase):
    def test_pb_by_total_level_boundaries(self):
        for lvl, pb in [(1, 2), (4, 2), (5, 3), (8, 3), (9, 4), (12, 4),
                        (13, 5), (16, 5), (17, 6), (20, 6)]:
            self.assertEqual(mc.proficiency_bonus(lvl), pb, f"level {lvl}")

    def test_fighter3_rogue2_is_pb_plus3(self):
        # SRD page 25 example: level 3 Fighter / level 2 Rogue → PB of a level
        # 5 character = +3.
        self.assertEqual(mc.proficiency_bonus(3 + 2), 3)


class PrerequisitesTest(unittest.TestCase):
    def test_single_ability_requirement(self):
        self.assertTrue(mc.class_prerequisite_met("c_wizard", {"int": 13}))
        self.assertFalse(mc.class_prerequisite_met("c_wizard", {"int": 12}))

    def test_or_requirement_fighter(self):
        # Fighter: Strength OR Dexterity 13 — either alone suffices.
        self.assertTrue(mc.class_prerequisite_met("c_fighter", {"str": 13, "dex": 8}))
        self.assertTrue(mc.class_prerequisite_met("c_fighter", {"str": 8, "dex": 13}))
        self.assertFalse(mc.class_prerequisite_met("c_fighter", {"str": 12, "dex": 12}))

    def test_and_requirement_paladin(self):
        # Paladin: Strength AND Charisma 13 — both required.
        self.assertTrue(mc.class_prerequisite_met("c_paladin", {"str": 13, "cha": 13}))
        self.assertFalse(mc.class_prerequisite_met("c_paladin", {"str": 13, "cha": 12}))
        self.assertFalse(mc.class_prerequisite_met("c_paladin", {"str": 12, "cha": 13}))

    def test_and_requirement_monk_and_ranger(self):
        self.assertTrue(mc.class_prerequisite_met("c_monk", {"dex": 14, "wis": 13}))
        self.assertFalse(mc.class_prerequisite_met("c_monk", {"dex": 14, "wis": 12}))
        self.assertTrue(mc.class_prerequisite_met("c_ranger", {"dex": 13, "wis": 15}))

    def test_srd_barbarian_into_druid_example(self):
        # SRD page 24-25: a Barbarian multiclassing into Druid must have STR 13
        # (Barbarian primary) AND WIS 13 (Druid primary).
        scores = {"str": 13, "wis": 13}
        self.assertEqual(mc.check_prerequisites(["c_barbarian", "c_druid"], scores), [])
        # Drop WIS below 13 → the Druid prereq fails.
        bad = mc.check_prerequisites(["c_barbarian", "c_druid"], {"str": 13, "wis": 12})
        self.assertEqual(len(bad), 1)
        self.assertIn("c_druid", bad[0])

    def test_accepts_resolved_score_shape(self):
        # Works with the resolved {str: {score: 15}} shape too.
        self.assertTrue(mc.class_prerequisite_met("c_wizard", {"int": {"score": 13}}))


class HitPointsTest(unittest.TestCase):
    def test_single_class_matches_pc_schema_compute_hp(self):
        # multiclass_hit_points must reproduce the single-class engine result.
        for cid, die, lvl in [("c_fighter", "d10", 5), ("c_wizard", "d6", 3),
                              ("c_barbarian", "d12", 1), ("c_cleric", "d8", 9)]:
            for con in (-1, 0, 2, 3):
                self.assertEqual(
                    mc.multiclass_hit_points([(cid, lvl)], con),
                    _compute_hp(die, lvl, con),
                    f"{cid} L{lvl} con {con}")

    def test_only_the_first_class_first_level_uses_max_die(self):
        # Fighter 1 / Wizard 1, CON +0: Fighter L1 = max d10 = 10; Wizard's
        # single level is NOT character level 1, so it's avg d6 = 4. Total 14.
        self.assertEqual(mc.multiclass_hit_points([("c_fighter", 1), ("c_wizard", 1)], 0), 14)
        # Reverse order: Wizard first → max d6 = 6; Fighter avg d10 = 6 → 12.
        self.assertEqual(mc.multiclass_hit_points([("c_wizard", 1), ("c_fighter", 1)], 0), 12)

    def test_con_applies_to_every_level(self):
        # Fighter 2 / Wizard 3 (total 5 levels), CON +2:
        #   Fighter L1 = 10, Fighter L2 = avg6, Wizard ×3 = avg4 each
        #   = 10 + 6 + 4+4+4 = 28 base + 2*5 CON = 38
        self.assertEqual(
            mc.multiclass_hit_points([("c_fighter", 2), ("c_wizard", 3)], 2), 38)

    def test_hit_dice_pool_srd_examples(self):
        # SRD page 25: Fighter5/Paladin5 (both d10) → ten d10.
        self.assertEqual(mc.hit_dice_pool([("c_fighter", 5), ("c_paladin", 5)]),
                         {10: 10})
        # Cleric5/Paladin5 → five d8 and five d10 (tracked separately).
        self.assertEqual(mc.hit_dice_pool([("c_cleric", 5), ("c_paladin", 5)]),
                         {8: 5, 10: 5})

    def test_hit_dice_string(self):
        self.assertEqual(
            mc.hit_dice_string([("c_fighter", 2), ("c_wizard", 3)]), "2d10+3d6")


class ExtraAttackTest(unittest.TestCase):
    def test_no_feature_one_attack(self):
        self.assertEqual(mc.extra_attack_total(set()), 1)

    def test_baseline_extra_attack_two(self):
        self.assertEqual(mc.extra_attack_total({"f_extra_attack"}), 2)

    def test_does_not_stack_across_classes(self):
        # Two baseline Extra Attack sources → still 2 (SRD: don't stack).
        self.assertEqual(
            mc.extra_attack_total({"f_extra_attack", "f_monk_extra_attack"}), 2)

    def test_thirsting_blade_does_not_add(self):
        self.assertEqual(
            mc.extra_attack_total({"f_extra_attack", "f_thirsting_blade"}), 2)

    def test_fighter_higher_tiers_raise_ceiling(self):
        self.assertEqual(mc.extra_attack_total({"f_extra_attack_two"}), 3)
        self.assertEqual(
            mc.extra_attack_total({"f_extra_attack", "f_extra_attack_three"}), 4)


class ACCalculationTest(unittest.TestCase):
    def test_one_at_a_time_picks_best(self):
        # Monk/Sorcerer: Unarmored Defense (10+DEX+WIS) vs Draconic Resilience
        # (13+DEX) — benefit from only one (the higher).
        self.assertEqual(mc.choose_ac_calculation([16, 14]), 16)
        self.assertEqual(mc.choose_ac_calculation([]), 10)


class CasterTypeCoverageTest(unittest.TestCase):
    def test_all_twelve_classes_classified(self):
        self.assertEqual(set(mc.CASTER_TYPE), set(mc.HIT_DICE))
        self.assertEqual(len(mc.CASTER_TYPE), 12)

    def test_caster_type_assignments(self):
        full = {c for c, t in mc.CASTER_TYPE.items() if t == "full"}
        self.assertEqual(full, {"c_bard", "c_cleric", "c_druid",
                                "c_sorcerer", "c_wizard"})
        self.assertEqual({c for c, t in mc.CASTER_TYPE.items() if t == "half"},
                         {"c_paladin", "c_ranger"})
        self.assertEqual({c for c, t in mc.CASTER_TYPE.items() if t == "pact"},
                         {"c_warlock"})

    def test_hit_dice_values(self):
        self.assertEqual(mc.HIT_DICE["c_barbarian"], 12)
        self.assertEqual(mc.HIT_DICE["c_wizard"], 6)
        self.assertEqual(mc.HIT_DICE["c_paladin"], 10)


if __name__ == "__main__":
    unittest.main()
