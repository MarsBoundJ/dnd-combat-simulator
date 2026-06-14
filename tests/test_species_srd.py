"""A3 — the 5 remaining SRD species (Dragonborn, Gnome, Goliath, Orc, Tiefling).

Each species is verified two ways:
  1. RUNTIME stamp — build a real PC with `race: r_<species>` through
     build_pc_template and assert the engine-consumed fields land on the
     template (Darkvision range, Size, Speed) exactly as the SRD prints them.
  2. DATA fidelity — assert the species' signature sub-option table is modeled
     correctly (Draconic Ancestry damage types, Breath Weapon scaling, Giant
     Ancestry options, Orc Relentless Endurance / Adrenaline Rush, Fiendish
     Legacy resistances). Traits needing new engine primitives are captured as
     data (see each r_*.yaml header + the PR description), so these assert the
     data is faithful pending the deferred wiring.

SRD source: docs/srd/SRD_CC_v5.2.1.pdf pages 84-86.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.loader import load_content
from engine.pc_schema import build_pc_template

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

NEW_SPECIES = ["r_dragonborn", "r_gnome", "r_goliath", "r_orc", "r_tiefling"]

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _race(rid):
    return _registry().get("race", rid)


def _scores():
    return {"str": 14, "dex": 14, "con": 14, "int": 12, "wis": 12, "cha": 12}


def _pc_with_race(race_id, class_id="c_fighter"):
    """Build a real PC template carrying the species, so we test the actual
    pc_schema → template stamping path the engine uses."""
    spec = {"class": class_id, "level": 1, "race": race_id,
            "ability_scores": _scores(), "weapons": []}
    return build_pc_template(spec, _registry())


class RosterTest(unittest.TestCase):
    def test_all_five_registered(self):
        for rid in NEW_SPECIES:
            r = _race(rid)
            self.assertIsNotNone(r, f"{rid} not registered")
            self.assertEqual(r["source"], "srd_5.2.1")
            self.assertEqual(r["creature_type"], "humanoid")

    def test_does_not_include_aasimar(self):
        # Aasimar is the PHB delta — must NOT be built here (needs Phil's PHB).
        self.assertFalse(
            (CONTENT_ROOT / "races" / "r_aasimar.yaml").exists(),
            "Aasimar is the PHB delta and must not be built in the SRD lane")


class DragonbornTest(unittest.TestCase):
    def test_runtime_darkvision_60(self):
        t = _pc_with_race("r_dragonborn")
        self.assertEqual(t["darkvision_range_ft"], 60)
        self.assertEqual(t["size"], "medium")

    def test_draconic_ancestry_damage_types(self):
        anc = _race("r_dragonborn")["draconic_ancestry"]
        self.assertEqual(anc["black"], "acid")
        self.assertEqual(anc["blue"], "lightning")
        self.assertEqual(anc["red"], "fire")
        self.assertEqual(anc["green"], "poison")
        self.assertEqual(anc["silver"], "cold")
        self.assertEqual(len(anc), 10)         # all ten SRD dragons

    def test_breath_weapon_spec(self):
        bw = _race("r_dragonborn")["breath_weapon"]
        self.assertEqual(bw["save"]["ability"], "dexterity")
        self.assertEqual(bw["base_dice"], "1d10")
        self.assertTrue(bw["half_on_success"])
        # Scales +1d10 at character levels 5/11/17 (SRD p84).
        self.assertEqual(bw["scaling"][1], "1d10")
        self.assertEqual(bw["scaling"][5], "2d10")
        self.assertEqual(bw["scaling"][11], "3d10")
        self.assertEqual(bw["scaling"][17], "4d10")
        self.assertEqual(bw["uses_per"], "proficiency_bonus")
        shapes = {s["shape"] for s in bw["shapes"]}
        self.assertEqual(shapes, {"cone", "line"})

    def test_no_baked_resistance_choice_is_deferred(self):
        # Resistance is the chosen ancestry type → not baked (would mis-model).
        self.assertEqual(_pc_with_race("r_dragonborn")["damage_resistances"], [])


class GnomeTest(unittest.TestCase):
    def test_runtime_small_and_darkvision(self):
        t = _pc_with_race("r_gnome")
        self.assertEqual(t["size"], "small")
        self.assertEqual(t["darkvision_range_ft"], 60)

    def test_lineage_options(self):
        lin = _race("r_gnome")["gnomish_lineage"]
        self.assertIn("forest_gnome", lin)
        self.assertIn("rock_gnome", lin)
        self.assertIn("minor_illusion", lin["forest_gnome"]["cantrips"])
        self.assertIn("mending", lin["rock_gnome"]["cantrips"])

    def test_gnomish_cunning_flag_present(self):
        self.assertIn("t_gnomish_cunning", _race("r_gnome")["racial_traits"])


class GoliathTest(unittest.TestCase):
    def test_runtime_speed_35(self):
        t = _pc_with_race("r_goliath")
        # Goliaths are the fast Medium species — Speed 35 ft (SRD p85).
        self.assertEqual(t["combat"]["speed"]["walk"], 35)
        self.assertEqual(t["size"], "medium")
        self.assertEqual(t["darkvision_range_ft"], 0)     # no Darkvision RAW

    def test_giant_ancestry_all_six_options(self):
        ga = _race("r_goliath")["giant_ancestry"]
        self.assertEqual(ga["uses_per"], "proficiency_bonus")
        opts = ga["options"]
        self.assertEqual(
            set(opts),
            {"clouds_jaunt", "fires_burn", "frosts_chill",
             "hills_tumble", "stones_endurance", "storms_thunder"})
        self.assertEqual(opts["fires_burn"]["dice"], "1d10")
        self.assertEqual(opts["fires_burn"]["damage_type"], "fire")
        self.assertEqual(opts["stones_endurance"]["dice"], "1d12")
        self.assertEqual(opts["hills_tumble"]["condition"], "co_prone")


class OrcTest(unittest.TestCase):
    def test_runtime_darkvision_120(self):
        # The Orc's signature: Darkvision 120 ft (SRD p86).
        t = _pc_with_race("r_orc")
        self.assertEqual(t["darkvision_range_ft"], 120)
        # Trait flags land on the template for future wiring hooks.
        self.assertIn("t_relentless_endurance", t["racial_traits"])
        self.assertIn("t_adrenaline_rush", t["racial_traits"])

    def test_relentless_endurance_spec(self):
        re = _race("r_orc")["relentless_endurance"]
        self.assertEqual(re["effect"], "drop_to_1_hp")
        self.assertEqual(re["uses"], 1)
        self.assertEqual(re["recharge"], "long_rest")

    def test_adrenaline_rush_spec(self):
        ar = _race("r_orc")["adrenaline_rush"]
        self.assertEqual(ar["slot"], "bonus_action")
        self.assertEqual(ar["grants"], "dash")
        self.assertEqual(ar["temp_hp"], "proficiency_bonus")
        self.assertEqual(ar["recharge"], "short_or_long_rest")


class TieflingTest(unittest.TestCase):
    def test_runtime_darkvision_60(self):
        t = _pc_with_race("r_tiefling")
        self.assertEqual(t["darkvision_range_ft"], 60)

    def test_fiendish_legacy_resistances_and_cantrips(self):
        fl = _race("r_tiefling")["fiendish_legacy"]
        self.assertEqual(fl["abyssal"]["resistance"], "poison")
        self.assertEqual(fl["chthonic"]["resistance"], "necrotic")
        self.assertEqual(fl["infernal"]["resistance"], "fire")
        self.assertEqual(fl["infernal"]["cantrip"], "fire_bolt")
        # Level-3/5 prepared spells (SRD p86 table).
        self.assertEqual(fl["abyssal"]["level_5_spell"], "hold_person")
        self.assertEqual(fl["infernal"]["level_3_spell"], "hellish_rebuke")

    def test_resistance_not_baked_choice_is_deferred(self):
        self.assertEqual(_pc_with_race("r_tiefling")["damage_resistances"], [])


class ExistingSpeciesUnaffectedTest(unittest.TestCase):
    def test_built_in_four_still_load(self):
        for rid in ("r_dwarf", "r_elf", "r_halfling", "r_human"):
            self.assertIsNotNone(_race(rid))
        # Dwarf still bakes its innate poison resistance (regression guard).
        t = build_pc_template(
            {"class": "c_fighter", "level": 1, "race": "r_dwarf",
             "ability_scores": _scores(), "weapons": []}, _registry())
        self.assertIn("poison", t["damage_resistances"])


if __name__ == "__main__":
    unittest.main()
