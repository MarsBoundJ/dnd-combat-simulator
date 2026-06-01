"""Sorcerer chassis + Innate Sorcery + Sorcery Points + Draconic Sorcery.

(Metamagic itself is covered in test_metamagic.py.)

Layers:
  1. c_sorcerer loads: CHA full-caster, SP table, subclass L3
  2. A Sorcerer PC is a functional caster (Fireball/Fire Bolt wired)
  3. Sorcery Points = sorcerer level (L2+); Innate Sorcery uses = 2
  4. metamagic_known stamped from pc_spec.metamagic
  5. Draconic Sorcery via subclass consumption: HP += level, unarmored
     AC = 10+DEX+CHA, Elemental Affinity resistance
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


def _spec(level=5, cha=18, dex=14, subclass=None, metamagic=None,
           element=None):
    s = {"id": "s", "class": "c_sorcerer", "level": level,
         "ability_scores": {"str": 8, "dex": dex, "con": 14,
                              "int": 10, "wis": 10, "cha": cha},
         "weapons": []}
    if subclass:
        s["subclass"] = subclass
    if metamagic:
        s["metamagic"] = metamagic
    if element:
        s["draconic_element"] = element
    return s


class ChassisTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = _registry()

    def test_cha_full_caster(self):
        c = self.r.get("class", "c_sorcerer")
        self.assertEqual(c["spellcasting"]["ability"], "charisma")
        self.assertEqual(c["spellcasting"]["slots_progression"], "full_caster")
        self.assertEqual(c["core_traits"]["hit_die"], "d6")
        self.assertEqual(len(c["level_table"]), 20)

    def test_functional_caster(self):
        t = build_pc_template(_spec(level=5), self.r)
        self.assertEqual(t.get("spellcasting_ability"), "charisma")
        ids = {a.get("id") for a in t.get("actions", [])}
        self.assertIn("a_fireball", ids)
        self.assertIn("a_fire_bolt", ids)
        self.assertIn("a_innate_sorcery", ids)


class ResourceTest(unittest.TestCase):

    def test_sorcery_points_equal_level(self):
        for lvl, sp in [(2, 2), (5, 5), (11, 11), (20, 20)]:
            res = derive_pc_resources(_spec(level=lvl), _registry())
            self.assertEqual(res.get("sorcery_points_remaining"), sp,
                              f"level {lvl}")

    def test_no_sp_at_level_1(self):
        res = derive_pc_resources(_spec(level=1), _registry())
        self.assertIsNone(res.get("sorcery_points_remaining"))

    def test_innate_sorcery_two_uses(self):
        res = derive_pc_resources(_spec(level=1), _registry())
        self.assertEqual(res.get("innate_sorcery_uses_remaining"), 2)

    def test_metamagic_known_stamped(self):
        t = build_pc_template(
            _spec(level=5, metamagic=["quickened", "empowered"]), _registry())
        self.assertEqual(set(t.get("metamagic_known")),
                          {"quickened", "empowered"})


class DraconicTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = _registry()

    def test_subclass_features_wired(self):
        t = build_pc_template(
            _spec(level=6, subclass="sc_draconic_sorcery"), self.r)
        feats = set(t.get("features_known", []))
        self.assertIn("f_draconic_resilience", feats)
        self.assertIn("f_elemental_affinity", feats)

    def test_draconic_resilience_hp_and_ac(self):
        # L5 Draconic: HP += 5; unarmored AC = 10 + DEX(+2) + CHA(+4) = 16
        plain = build_pc_template(_spec(level=5, dex=14, cha=18), self.r)
        drac = build_pc_template(
            _spec(level=5, dex=14, cha=18, subclass="sc_draconic_sorcery"),
            self.r)
        plain_hp = plain["combat"]["hit_points"]["average"]
        drac_hp = drac["combat"]["hit_points"]["average"]
        self.assertEqual(drac_hp - plain_hp, 5)  # += sorcerer level
        self.assertEqual(drac["combat"]["armor_class"], 16)  # 10+2+4

    def test_elemental_affinity_resistance(self):
        t = build_pc_template(
            _spec(level=6, subclass="sc_draconic_sorcery", element="cold"),
            self.r)
        self.assertIn("cold", t.get("damage_resistances", []))

    def test_elemental_affinity_defaults_fire(self):
        t = build_pc_template(
            _spec(level=6, subclass="sc_draconic_sorcery"), self.r)
        self.assertIn("fire", t.get("damage_resistances", []))


if __name__ == "__main__":
    unittest.main()
