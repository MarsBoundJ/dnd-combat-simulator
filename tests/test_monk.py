"""Monk foundation — Martial Arts, Unarmored Defense, Focus Points,
Flurry of Blows, Extra Attack.

(Stunning Strike + Warrior of the Open Hand land in a follow-on.)

Layers:
  1. c_monk loads: DEX/WIS martial, d8, subclass L3, 20-level table
  2. Martial Arts: DEX-based unarmed strike with the MA die (scales by
     level) + a bonus-action strike
  3. Unarmored Defense: AC = 10 + DEX + WIS (no armor)
  4. Focus Points = Monk level (L2+)
  5. Flurry of Blows: BA 2× strike consuming focus_points_remaining
  6. Extra Attack: 2× unarmed-strike multiattack at L5
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _spec(level=5, dex=16, wis=14):
    return {"id": "m", "class": "c_monk", "level": level,
            "ability_scores": {"str": 10, "dex": dex, "con": 14,
                                 "int": 8, "wis": wis, "cha": 10},
            "weapons": []}


class ChassisTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = _registry()

    def test_monk_core_traits(self):
        c = self.r.get("class", "c_monk")
        self.assertEqual(c["core_traits"]["hit_die"], "d8")
        self.assertEqual(set(c["core_traits"]["save_proficiencies"]),
                          {"strength", "dexterity"})
        self.assertNotIn("spellcasting", c)  # non-caster
        self.assertEqual(c["subclass_grant_level"], 3)
        self.assertEqual(len(c["level_table"]), 20)

    def test_unarmed_strike_dex_and_madie(self):
        t = build_pc_template(_spec(level=1, dex=16), self.r)
        us = next(a for a in t["actions"] if a["id"] == "a_unarmed_strike")
        atk = us["pipeline"][0]["params"]
        dmg = us["pipeline"][1]["params"]
        self.assertEqual(atk["ability"], "dex")
        self.assertEqual(atk["bonus"], 5)        # DEX 16 (+3) + PB 2
        self.assertEqual(dmg["dice"], "1d6")     # L1 MA die
        self.assertEqual(dmg["modifier"], 3)     # DEX mod on damage
        self.assertEqual(dmg["type"], "bludgeoning")

    def test_bonus_action_strike_present(self):
        t = build_pc_template(_spec(level=1), self.r)
        ba = next(a for a in t["actions"]
                    if a["id"] == "a_unarmed_strike_bonus")
        self.assertEqual(ba["slot"], "bonus_action")

    def test_martial_arts_die_scales(self):
        for lvl, die in [(1, "1d6"), (5, "1d8"), (11, "1d10"), (17, "1d12")]:
            t = build_pc_template(_spec(level=lvl), self.r)
            us = next(a for a in t["actions"]
                        if a["id"] == "a_unarmed_strike")
            self.assertEqual(us["pipeline"][1]["params"]["dice"], die,
                              f"level {lvl}")


class UnarmoredDefenseTest(unittest.TestCase):

    def test_ac_is_ten_plus_dex_plus_wis(self):
        # DEX 16 (+3), WIS 14 (+2) → AC 15
        t = build_pc_template(_spec(level=1, dex=16, wis=14), _registry())
        self.assertEqual(t["combat"]["armor_class"], 15)

    def test_ac_scales_with_wis(self):
        # DEX 18 (+4), WIS 16 (+3) → AC 17
        t = build_pc_template(_spec(level=1, dex=18, wis=16), _registry())
        self.assertEqual(t["combat"]["armor_class"], 17)


class FocusAndFlurryTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = _registry()

    def test_no_focus_at_level_1(self):
        res = derive_pc_resources(_spec(level=1), self.r)
        self.assertIsNone(res.get("focus_points_remaining"))

    def test_focus_points_equal_level(self):
        for lvl, fp in [(2, 2), (5, 5), (11, 11), (20, 20)]:
            res = derive_pc_resources(_spec(level=lvl), self.r)
            self.assertEqual(res.get("focus_points_remaining"), fp,
                              f"level {lvl}")

    def test_flurry_present_at_l2_consumes_focus(self):
        t = build_pc_template(_spec(level=2), self.r)
        flurry = next((a for a in t["actions"]
                        if a["id"] == "a_flurry_of_blows"), None)
        self.assertIsNotNone(flurry)
        self.assertEqual(flurry["slot"], "bonus_action")
        self.assertEqual(flurry["type"], "multiattack")
        self.assertEqual(flurry["count"], 2)
        self.assertEqual(flurry["feature_use"], "focus_points_remaining")

    def test_no_flurry_at_l1(self):
        t = build_pc_template(_spec(level=1), self.r)
        ids = {a.get("id") for a in t["actions"]}
        self.assertNotIn("a_flurry_of_blows", ids)


class ExtraAttackTest(unittest.TestCase):

    def test_extra_attack_at_l5(self):
        t = build_pc_template(_spec(level=5), _registry())
        ea = next((a for a in t["actions"]
                    if a["id"] == "a_monk_extra_attack"), None)
        self.assertIsNotNone(ea)
        self.assertEqual(ea["count"], 2)
        self.assertEqual(ea["sub_actions"],
                          ["a_unarmed_strike", "a_unarmed_strike"])

    def test_no_extra_attack_at_l4(self):
        t = build_pc_template(_spec(level=4), _registry())
        ids = {a.get("id") for a in t["actions"]}
        self.assertNotIn("a_monk_extra_attack", ids)


if __name__ == "__main__":
    unittest.main()
