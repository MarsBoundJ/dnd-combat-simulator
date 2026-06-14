"""WS-A2 — SRD equipment library (eq_*.yaml).

Loads the whole library, validates every file against equipment.schema.json
(full JSON-Schema, cross-file $refs resolved), checks the SRD inventory counts,
and spot-asserts exact stat lines read from the SRD 5.2.1 Equipment tables
(e.g. Longsword 1d8/1d10 Versatile + Sap; Chain Mail base_ac 16 + Str 13 +
Stealth disadvantage).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema
import yaml
from referencing import Registry, Resource

from engine.loader import load_content

REPO_ROOT = Path(__file__).parent.parent
DEFS = REPO_ROOT / "schema" / "definitions"
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
EQ_DIR = CONTENT_ROOT / "equipment"

MASTERIES = {"cleave", "graze", "nick", "push", "sap", "slow", "topple", "vex"}


def _registry():
    return load_content(CONTENT_ROOT, validate=True, schema_root=DEFS)


def _equipment():
    return _registry().all("equipment")


def _by_kind(kind):
    return {k: v for k, v in _equipment().items() if v["kind"] == kind}


def _validator():
    common = json.loads((DEFS / "common.schema.json").read_text())
    eqs = json.loads((DEFS / "equipment.schema.json").read_text())
    reg = Registry().with_resources([
        (common["$id"], Resource.from_contents(common)),
        (eqs["$id"], Resource.from_contents(eqs)),
    ])
    return jsonschema.Draft202012Validator(eqs, registry=reg)


class SchemaValidityTest(unittest.TestCase):
    """Every eq_*.yaml validates fully (not just lite) against the schema."""

    def test_all_files_validate(self):
        v = _validator()
        files = sorted(EQ_DIR.glob("eq_*.yaml"))
        self.assertTrue(files, "no equipment files found")
        for f in files:
            with self.subTest(file=f.name):
                doc = yaml.safe_load(f.read_text())
                errors = sorted(v.iter_errors(doc), key=str)
                self.assertEqual(errors, [],
                                 f"{f.name}: {[e.message for e in errors]}")

    def test_id_matches_filename_and_prefix(self):
        for f in sorted(EQ_DIR.glob("*.yaml")):
            with self.subTest(file=f.name):
                doc = yaml.safe_load(f.read_text())
                self.assertEqual(doc["id"], f.stem)
                self.assertTrue(doc["id"].startswith("eq_"))

    def test_all_srd_sourced(self):
        for eid, e in _equipment().items():
            with self.subTest(item=eid):
                self.assertEqual(e["source"], "srd_5.2.1")


class InventoryCountTest(unittest.TestCase):
    """SRD 5.2.1 inventory counts (docs/srd/srd-coverage-audit.md §4)."""

    def test_weapon_count_38(self):
        self.assertEqual(len(_by_kind("weapon")), 38)

    def test_weapon_category_breakdown(self):
        weapons = _by_kind("weapon").values()
        simple_melee = [w for w in weapons
                        if w["weapon"]["category"] == "simple"
                        and w["weapon"]["range_type"] == "melee"]
        simple_ranged = [w for w in weapons
                         if w["weapon"]["category"] == "simple"
                         and w["weapon"]["range_type"] == "ranged"]
        martial_melee = [w for w in weapons
                         if w["weapon"]["category"] == "martial"
                         and w["weapon"]["range_type"] == "melee"]
        martial_ranged = [w for w in weapons
                          if w["weapon"]["category"] == "martial"
                          and w["weapon"]["range_type"] == "ranged"]
        self.assertEqual(len(simple_melee), 10)
        self.assertEqual(len(simple_ranged), 4)
        self.assertEqual(len(martial_melee), 18)
        self.assertEqual(len(martial_ranged), 6)

    def test_armor_and_shield_counts(self):
        armor = _by_kind("armor").values()
        self.assertEqual(len(list(armor)), 12)
        self.assertEqual(len(_by_kind("shield")), 1)
        cats = {}
        for a in _by_kind("armor").values():
            cats[a["armor"]["category"]] = cats.get(a["armor"]["category"], 0) + 1
        self.assertEqual(cats, {"light": 3, "medium": 5, "heavy": 4})

    def test_ammunition_and_focus_counts(self):
        self.assertEqual(len(_by_kind("ammunition")), 5)
        self.assertEqual(len(_by_kind("focus")), 9)  # 5 arcane + 3 druidic + holy symbol

    def test_combat_gear_present(self):
        gear = _by_kind("gear")
        for needed in ("eq_acid", "eq_alchemists_fire", "eq_holy_water",
                       "eq_caltrops", "eq_ball_bearings", "eq_net", "eq_oil",
                       "eq_healers_kit", "eq_antitoxin", "eq_hunting_trap"):
            self.assertIn(needed, gear)


class WeaponStatTest(unittest.TestCase):
    """Exact weapon stat lines from the SRD weapon table."""

    def setUp(self):
        self.eq = _equipment()

    def test_longsword(self):
        w = self.eq["eq_longsword"]["weapon"]
        self.assertEqual(w["category"], "martial")
        self.assertEqual(w["range_type"], "melee")
        self.assertEqual(w["damage"], {"dice": "1d8", "type": "slashing"})
        self.assertEqual(w["versatile_damage"], "1d10")
        self.assertEqual(w["properties"], ["versatile"])
        self.assertEqual(w["mastery"], "sap")
        self.assertEqual(self.eq["eq_longsword"]["cost"],
                         {"quantity": 15, "unit": "gp"})
        self.assertEqual(self.eq["eq_longsword"]["weight_lb"], 3)

    def test_greatsword(self):
        w = self.eq["eq_greatsword"]["weapon"]
        self.assertEqual(w["damage"], {"dice": "2d6", "type": "slashing"})
        self.assertCountEqual(w["properties"], ["heavy", "two_handed"])
        self.assertEqual(w["mastery"], "graze")

    def test_dagger(self):
        w = self.eq["eq_dagger"]["weapon"]
        self.assertEqual(w["damage"], {"dice": "1d4", "type": "piercing"})
        self.assertCountEqual(w["properties"], ["finesse", "light", "thrown"])
        self.assertEqual(w["mastery"], "nick")
        self.assertEqual(w["range"], {"normal_ft": 20, "long_ft": 60})

    def test_shortbow(self):
        w = self.eq["eq_shortbow"]["weapon"]
        self.assertEqual(w["range_type"], "ranged")
        self.assertCountEqual(w["properties"], ["ammunition", "two_handed"])
        self.assertEqual(w["range"], {"normal_ft": 80, "long_ft": 320})
        self.assertEqual(w["ammunition_type"], "arrow")
        self.assertEqual(w["mastery"], "vex")

    def test_blowgun_fixed_one_damage(self):
        # SRD lists "1 Piercing" — a flat 1, not a die.
        w = self.eq["eq_blowgun"]["weapon"]
        self.assertEqual(w["damage"], {"dice": "", "modifier": 1, "type": "piercing"})

    def test_every_weapon_has_category_and_mastery(self):
        for eid, e in _by_kind("weapon").items():
            with self.subTest(weapon=eid):
                self.assertIn(e["weapon"]["category"], ("simple", "martial"))
                self.assertIn(e["weapon"]["mastery"], MASTERIES)

    def test_all_eight_masteries_present(self):
        used = {e["weapon"]["mastery"] for e in _by_kind("weapon").values()}
        self.assertEqual(used, MASTERIES)


class ArmorStatTest(unittest.TestCase):
    """Exact armor stat lines from the SRD armor table."""

    def setUp(self):
        self.eq = _equipment()

    def test_chain_mail(self):
        a = self.eq["eq_chain_mail"]["armor"]
        self.assertEqual(a["category"], "heavy")
        self.assertEqual(a["base_ac"], 16)
        self.assertFalse(a["add_dex_modifier"])
        self.assertEqual(a["strength_requirement"], 13)
        self.assertTrue(a["stealth_disadvantage"])

    def test_scale_mail(self):
        a = self.eq["eq_scale_mail"]["armor"]
        self.assertEqual(a["category"], "medium")
        self.assertEqual(a["base_ac"], 14)
        self.assertEqual(a["max_dex_bonus"], 2)
        self.assertTrue(a["add_dex_modifier"])
        self.assertTrue(a["stealth_disadvantage"])

    def test_padded_armor(self):
        a = self.eq["eq_padded_armor"]["armor"]
        self.assertEqual(a["category"], "light")
        self.assertEqual(a["base_ac"], 11)
        self.assertIsNone(a["max_dex_bonus"])
        self.assertTrue(a["stealth_disadvantage"])

    def test_plate_armor(self):
        a = self.eq["eq_plate_armor"]["armor"]
        self.assertEqual(a["base_ac"], 18)
        self.assertEqual(a["strength_requirement"], 15)

    def test_shield_ac_bonus(self):
        self.assertEqual(self.eq["eq_shield"]["shield"]["ac_bonus"], 2)


class CombatGearEffectTest(unittest.TestCase):
    """Combat gear carries the right effect/activation/consumable shape."""

    def setUp(self):
        self.eq = _equipment()

    def test_acid_throws_for_2d6(self):
        acid = self.eq["eq_acid"]
        self.assertTrue(acid["consumable"])
        self.assertEqual(acid["activation"]["cost"], "action")
        fs = acid["effect_primitives"][0]
        self.assertEqual(fs["primitive"], "forced_save")
        self.assertEqual(fs["params"]["ability"], "dexterity")
        dmg = fs["params"]["on_fail"][0]
        self.assertEqual(dmg["primitive"], "damage")
        self.assertEqual(dmg["params"], {"dice": "2d6", "type": "acid"})

    def test_net_restrains(self):
        net = self.eq["eq_net"]
        fs = net["effect_primitives"][0]
        cond = fs["params"]["on_fail"][0]
        self.assertEqual(cond["primitive"], "apply_condition")
        self.assertEqual(cond["params"]["condition_id"], "co_restrained")

    def test_caltrops_static_dc(self):
        # Caltrops use a fixed DC 15 (not wielder-derived).
        fs = self.eq["eq_caltrops"]["effect_primitives"][0]
        self.assertEqual(fs["params"]["dc"], 15)

    def test_ball_bearings_static_dc_prone(self):
        fs = self.eq["eq_ball_bearings"]["effect_primitives"][0]
        self.assertEqual(fs["params"]["dc"], 10)
        self.assertEqual(fs["params"]["on_fail"][0]["params"]["condition_id"],
                         "co_prone")

    def test_thrown_gear_uses_dynamic_dc_formula(self):
        # Wielder-derived DC is captured as a formula (engine flag in PR).
        for eid in ("eq_acid", "eq_alchemists_fire", "eq_holy_water", "eq_net"):
            with self.subTest(item=eid):
                fs = self.eq[eid]["effect_primitives"][0]
                self.assertIn("dc_formula", fs["params"])
                self.assertNotIn("dc", fs["params"])


if __name__ == "__main__":
    unittest.main()
