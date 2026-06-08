"""Barbarian class-feature tests — Extra Attack, Unarmored Defense, and
the completed/corrected level table.

The level table was previously sparse (rows only at L1-6, 9, 11, 16, 17,
20), which mis-stated the Rages and Weapon Mastery counts at the skipped
boundaries. It now spans all 20 levels with RAW values, and lists every
class feature at its level. This suite locks in:
  1. Extra Attack (L5): a 2-attack multiattack action is generated; the
     Barbarian caps at 2 (never gains a second Extra Attack).
  2. Unarmored Defense (L1): base AC = 10 + DEX + CON when unarmored.
  3. Corrected resource table at the previously-wrong boundaries.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources


_REPO = Path(__file__).resolve().parent.parent
_GREATAXE = {"id": "greataxe", "name": "Greataxe", "damage_dice": "1d12",
             "damage_type": "slashing", "attack_ability": "str"}


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                          schema_root=_REPO / "schema")


def _build(level, *, abilities=None, weapons=None, subclass=None):
    spec = {
        "id": f"barb{level}", "name": f"Barb{level}",
        "class": "c_barbarian", "level": level,
        "ability_scores": abilities or {"str": 18, "dex": 14, "con": 16,
                                          "int": 8, "wis": 10, "cha": 8},
        "weapons": weapons if weapons is not None else [dict(_GREATAXE)],
    }
    if subclass:
        spec["subclass"] = subclass
    return build_pc_template(spec, _registry())


def _table_row(level):
    """The c_barbarian level_table row for `level` (class data under test)."""
    cls = _registry().get("class", "c_barbarian")
    for row in cls["level_table"]:
        if row["level"] == level:
            return row
    raise AssertionError(f"no level_table row for L{level}")


class ExtraAttackTest(unittest.TestCase):

    def _multiattack(self, template):
        return [a for a in template.get("actions", [])
                if a.get("type") == "multiattack"]

    def test_no_extra_attack_before_l5(self) -> None:
        tpl = _build(4)
        self.assertNotIn("f_extra_attack", tpl.get("features_known", []))
        self.assertEqual(self._multiattack(tpl), [])

    def test_extra_attack_at_l5(self) -> None:
        tpl = _build(5)
        self.assertIn("f_extra_attack", tpl.get("features_known", []))
        ma = self._multiattack(tpl)
        self.assertEqual(len(ma), 1)
        self.assertEqual(ma[0]["count"], 2)

    def test_caps_at_two_attacks_at_l20(self) -> None:
        # Barbarians gain Extra Attack ONCE — no f_two/three_extra_attacks.
        tpl = _build(20)
        ma = self._multiattack(tpl)
        self.assertEqual(len(ma), 1)
        self.assertEqual(ma[0]["count"], 2)


class UnarmoredDefenseTest(unittest.TestCase):

    def test_unarmored_ac_uses_con(self) -> None:
        # STR 18, DEX 14 (+2), CON 16 (+3) → AC = 10 + 2 + 3 = 15
        tpl = _build(1)
        self.assertIn("f_unarmored_defense_barbarian",
                       tpl.get("features_known", []))
        self.assertEqual(tpl["combat"]["armor_class"], 15)

    def test_high_con_raises_ac(self) -> None:
        # CON 20 (+5), DEX 14 (+2) → AC = 10 + 2 + 5 = 17
        tpl = _build(1, abilities={"str": 18, "dex": 14, "con": 20,
                                      "int": 8, "wis": 10, "cha": 8})
        self.assertEqual(tpl["combat"]["armor_class"], 17)


class FastMovementTest(unittest.TestCase):

    def _speed(self, template):
        return template["combat"]["speed"]["walk"]

    def test_no_bonus_before_l5(self) -> None:
        tpl = _build(4)
        self.assertNotIn("f_fast_movement", tpl.get("features_known", []))
        self.assertEqual(self._speed(tpl), 30)

    def test_plus_ten_at_l5_unarmored(self) -> None:
        tpl = _build(5)
        self.assertIn("f_fast_movement", tpl.get("features_known", []))
        self.assertEqual(self._speed(tpl), 40)

    def test_suppressed_in_heavy_armor(self) -> None:
        # base_ac 18 / max_dex_bonus 0 → Heavy armor proxy → no bonus.
        spec = {
            "id": "barbplate", "class": "c_barbarian", "level": 5,
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                 "int": 8, "wis": 10, "cha": 8},
            "weapons": [dict(_GREATAXE)],
            "armor": {"base_ac": 18, "max_dex_bonus": 0},
        }
        tpl = build_pc_template(spec, _registry())
        self.assertEqual(tpl["combat"]["speed"]["walk"], 30)

    def test_applies_in_medium_armor(self) -> None:
        # Medium armor caps DEX at +2 (not 0) → not Heavy → bonus applies.
        spec = {
            "id": "barbhide", "class": "c_barbarian", "level": 5,
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                 "int": 8, "wis": 10, "cha": 8},
            "weapons": [dict(_GREATAXE)],
            "armor": {"base_ac": 14, "max_dex_bonus": 2},
        }
        tpl = build_pc_template(spec, _registry())
        self.assertEqual(tpl["combat"]["speed"]["walk"], 40)


class CorrectedResourceTableTest(unittest.TestCase):
    """The previously-sparse table mis-stated these. RAW (PHB 2024):
    Rages 1-2:2 / 3-5:3 / 6-11:4 / 12-16:5 / 17-20:6;
    Weapon Mastery 1-3:2 / 4-9:3 / 10-20:4."""

    def test_l11_rages_and_mastery(self) -> None:
        cr = _table_row(11)["class_resources"]
        self.assertEqual(cr["rage_uses"], 4)            # was wrongly 5
        self.assertEqual(cr["weapon_mastery_count"], 4)  # was wrongly 3

    def test_l16_rages_and_mastery(self) -> None:
        cr = _table_row(16)["class_resources"]
        self.assertEqual(cr["rage_uses"], 5)            # was wrongly 6
        self.assertEqual(cr["weapon_mastery_count"], 4)  # was wrongly 3

    def test_l17_l20_mastery_and_caps(self) -> None:
        self.assertEqual(_table_row(17)["class_resources"]["rage_uses"], 6)
        cr20 = _table_row(20)["class_resources"]
        self.assertEqual(cr20["rage_uses"], 6)
        self.assertEqual(cr20["rage_damage_bonus"], 4)
        self.assertEqual(cr20["weapon_mastery_count"], 4)  # was wrongly 3

    def test_rage_uses_feed_resources(self) -> None:
        # The corrected table feeds derive_pc_resources (L11 → 4 rages).
        spec = {
            "id": "b11", "class": "c_barbarian", "level": 11,
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                 "int": 8, "wis": 10, "cha": 8},
            "weapons": [dict(_GREATAXE)],
        }
        r = derive_pc_resources(spec, _registry())
        self.assertEqual(r.get("rage_uses_max"), 4)


if __name__ == "__main__":
    unittest.main()
