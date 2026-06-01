"""Generic pc_builder dispatch (the spell-builder refactor).

A feature YAML can declare a `pc_builder` block instead of an
action_template when its action must be computed at PC-build time
(spell-attack bonus from ability + PB; cantrip die from character level;
heal +mod). build_pc_template dispatches it via _dispatch_pc_builder, so
NEW attack/heal spells are added by YAML alone — no per-feature edit in
pc_schema.

These tests exercise the dispatcher directly with synthetic feature defs
(so they prove the mechanism independent of any specific shipped spell),
plus a guard that an unknown kind raises.
"""
from __future__ import annotations

import unittest

from engine.pc_schema import _dispatch_pc_builder

_ABIL = {"str": {"score": 10}, "dex": {"score": 10}, "con": {"score": 10},
          "int": {"score": 18}, "wis": {"score": 10}, "cha": {"score": 16}}


def _feat(kind, params, aid="a_test", name="Test"):
    return {"id": "f_test", "pc_builder": {
        "kind": kind, "action_id": aid, "name": name, "params": params}}


class DispatchTest(unittest.TestCase):

    def test_no_pc_builder_returns_none(self) -> None:
        self.assertIsNone(_dispatch_pc_builder(
            {"id": "f_plain"}, 1, _ABIL, 2, "c_wizard"))

    def test_attack_cantrip(self) -> None:
        a = _dispatch_pc_builder(
            _feat("attack_cantrip",
                   {"damage_type": "cold", "die": 8, "range_ft": 60}),
            5, _ABIL, 3, "c_wizard")
        self.assertEqual(a["type"], "weapon_attack")
        self.assertEqual(a["spell_slot_level"], 0)
        atk = a["pipeline"][0]["params"]
        dmg = a["pipeline"][1]["params"]
        # INT 18 (+4) + PB 3 = +7 attack; 2d8 at character level 5
        self.assertEqual(atk["bonus"], 7)
        self.assertEqual(dmg["dice"], "2d8")
        self.assertEqual(dmg["type"], "cold")

    def test_save_cantrip(self) -> None:
        a = _dispatch_pc_builder(
            _feat("save_cantrip",
                   {"save_ability": "wisdom", "damage_type": "psychic",
                    "die": 6, "range_ft": 60}),
            11, _ABIL, 4, "c_bard")
        self.assertEqual(a["type"], "save_attack")
        self.assertEqual(a["save_ability"], "wisdom")
        # 3d6 at character level 11
        fail = a["pipeline"][0]["params"]["on_fail"][0]["params"]
        self.assertEqual(fail["dice"], "3d6")

    def test_spell_attack_with_upcast(self) -> None:
        a = _dispatch_pc_builder(
            _feat("spell_attack",
                   {"slot_level": 1, "range_ft": 120, "damage_dice": "4d6",
                    "damage_type": "radiant", "upcast_dice": "1d6"}),
            1, _ABIL, 2, "c_cleric")
        self.assertEqual(a["spell_slot_level"], 1)
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d6")
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "4d6")

    def test_spell_attack_multi_ray(self) -> None:
        a = _dispatch_pc_builder(
            _feat("spell_attack",
                   {"slot_level": 2, "range_ft": 120, "damage_dice": "2d6",
                    "damage_type": "fire", "ray_count": 3}),
            5, _ABIL, 3, "c_wizard")
        # 3 rays = 3 (attack_roll, damage) pairs = 6 pipeline steps
        self.assertEqual(len(a["pipeline"]), 6)

    def test_heal_single_and_multi(self) -> None:
        single = _dispatch_pc_builder(
            _feat("heal", {"slot": "action", "slot_level": 1,
                            "range_ft": 5, "dice": "2d8"}),
            1, _ABIL, 2, "c_cleric")
        self.assertEqual(single["type"], "heal")
        self.assertNotIn("max_targets", single)
        multi = _dispatch_pc_builder(
            _feat("heal", {"slot": "action", "slot_level": 5,
                            "range_ft": 60, "dice": "5d8",
                            "max_targets": 6}),
            9, _ABIL, 4, "c_cleric")
        self.assertEqual(multi["max_targets"], 6)

    def test_unknown_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            _dispatch_pc_builder(
                _feat("teleport", {}), 1, _ABIL, 2, "c_wizard")

    def test_missing_fields_raise(self) -> None:
        with self.assertRaises(ValueError):
            _dispatch_pc_builder(
                {"id": "f_x", "pc_builder": {"kind": "heal"}},
                1, _ABIL, 2, "c_cleric")


if __name__ == "__main__":
    unittest.main()
