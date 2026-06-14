"""B2 buildout tests — the ordered `classes:` PC spec through build_pc_template.

Asserts the four B2 derivations (total level, PB, HP, merged/first-class
proficiencies) plus back-compat: `class:`+`level:` sugar builds byte-identically
to a one-entry `classes:` list, and single-class templates are unchanged.

The risky multiclass spell-slot ALLOCATION is deliberately B4 — a multiclass
caster's pool is left EMPTY here (asserted), never stamped with wrong
single-class slots.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core import multiclass as mc
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources, ability_modifier

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _scores(str_=16, dex=12, con=14, int_=14, wis=10, cha=8):
    return {"str": str_, "dex": dex, "con": con, "int": int_, "wis": wis, "cha": cha}


def _save(tmpl, ability):
    return tmpl["abilities"][ability]["save"]


def _mod(tmpl, ability):
    return ability_modifier(tmpl["abilities"][ability]["score"])


class BackCompatTest(unittest.TestCase):
    """Single-class behavior must be unchanged; sugar == one-entry list."""

    def test_sugar_and_one_entry_list_are_identical(self):
        reg = _registry()
        sugar = {"class": "c_wizard", "level": 3, "ability_scores": _scores(),
                 "weapons": []}
        listed = {"classes": [{"class": "c_wizard", "level": 3}],
                  "ability_scores": _scores(), "weapons": []}
        t_sugar = build_pc_template(sugar, reg)
        t_list = build_pc_template(listed, reg)
        # Core derived numbers identical.
        self.assertEqual(t_sugar["cr"]["proficiency_bonus"],
                         t_list["cr"]["proficiency_bonus"])
        self.assertEqual(t_sugar["combat"]["hit_points"],
                         t_list["combat"]["hit_points"])
        self.assertEqual(t_sugar["levels"], t_list["levels"])
        self.assertEqual(t_sugar["abilities"], t_list["abilities"])
        self.assertEqual(t_sugar["spell_slots"], t_list["spell_slots"])

    def test_single_class_wizard3_unchanged(self):
        reg = _registry()
        t = build_pc_template(
            {"class": "c_wizard", "level": 3, "ability_scores": _scores(),
             "weapons": []}, reg)
        self.assertEqual(t["levels"], {"wizard": 3})
        self.assertEqual(t["cr"]["proficiency_bonus"], 2)        # total level 3
        self.assertEqual(t["combat"]["hit_points"]["dice"], "3d6")
        # Single-class caster still gets its single-class slot pool (non-empty).
        self.assertTrue(t["spell_slots"], "single-class wizard should have slots")
        # Wizard saves: INT + WIS proficient.
        self.assertEqual(_save(t, "int") - _mod(t, "int"), 2)
        self.assertEqual(_save(t, "wis") - _mod(t, "wis"), 2)
        self.assertEqual(_save(t, "str") - _mod(t, "str"), 0)


class MulticlassDerivationTest(unittest.TestCase):
    """Fighter 2 / Wizard 3 — the named oracle build."""

    def setUp(self):
        self.reg = _registry()
        self.spec = {
            "classes": [{"class": "c_fighter", "level": 2},
                        {"class": "c_wizard", "level": 3}],
            "ability_scores": _scores(),   # STR16 (Fighter), INT14 (Wizard) ok
            "weapons": [],
        }
        self.t = build_pc_template(self.spec, self.reg)

    def test_total_level_and_pb(self):
        # total level 5 → PB +3, even though each class alone is +2.
        self.assertEqual(self.t["cr"]["proficiency_bonus"], 3)
        self.assertEqual(self.t["derived_from_pc_schema"]["total_level"], 5)

    def test_levels_dict_has_both_classes(self):
        self.assertEqual(self.t["levels"], {"fighter": 2, "wizard": 3})

    def test_hp_across_hit_dice(self):
        con_mod = ability_modifier(self.spec["ability_scores"]["con"])
        expected = mc.multiclass_hit_points(
            [("c_fighter", 2), ("c_wizard", 3)], con_mod)
        self.assertEqual(self.t["combat"]["hit_points"]["average"], expected)
        self.assertEqual(self.t["combat"]["hit_points"]["dice"], "2d10+3d6")
        self.assertEqual(self.t["combat"]["hit_points"]["con_contribution"],
                         con_mod * 5)

    def test_saves_from_first_class_only(self):
        # Fighter is the initial class → STR + CON saves proficient (+PB);
        # Wizard's INT/WIS saves are NOT granted by multiclassing in.
        self.assertEqual(_save(self.t, "str") - _mod(self.t, "str"), 3)  # +PB
        self.assertEqual(_save(self.t, "con") - _mod(self.t, "con"), 3)  # +PB
        self.assertEqual(_save(self.t, "int") - _mod(self.t, "int"), 0)  # not granted
        self.assertEqual(_save(self.t, "wis") - _mod(self.t, "wis"), 0)

    def test_multiclass_caster_pool_is_empty_pending_b4(self):
        # The shared slot pool is B4's allocation; we must NOT stamp the
        # primary class's single-class slots onto a multiclass caster.
        self.assertEqual(self.t["spell_slots"], {})

    def test_telemetry_records_full_class_set(self):
        classes = self.t["derived_from_pc_schema"]["classes"]
        self.assertEqual(classes,
                         [{"class": "c_fighter", "level": 2, "subclass": None},
                          {"class": "c_wizard", "level": 3, "subclass": None}])
        # Primary class/level kept for back-compat single-class readers.
        self.assertEqual(self.t["derived_from_pc_schema"]["class"], "c_fighter")


class FirstClassDrivesIdentityTest(unittest.TestCase):
    """Order matters: the FIRST entry drives saves + the L1 (max) hit die."""

    def test_wizard_first_gives_wizard_saves_and_d6_l1(self):
        reg = _registry()
        spec = {"classes": [{"class": "c_wizard", "level": 3},
                            {"class": "c_fighter", "level": 2}],
                "ability_scores": _scores(), "weapons": []}
        t = build_pc_template(spec, reg)
        # Wizard initial → INT + WIS saves proficient; STR/CON not.
        self.assertEqual(_save(t, "int") - _mod(t, "int"), 3)
        self.assertEqual(_save(t, "wis") - _mod(t, "wis"), 3)
        self.assertEqual(_save(t, "str") - _mod(t, "str"), 0)
        # HP: Wizard L1 uses max d6; the dice string leads with the pooled d6.
        con_mod = ability_modifier(spec["ability_scores"]["con"])
        self.assertEqual(t["combat"]["hit_points"]["average"],
                         mc.multiclass_hit_points(
                             [("c_wizard", 3), ("c_fighter", 2)], con_mod))
        self.assertEqual(t["levels"], {"wizard": 3, "fighter": 2})


class PrerequisiteEnforcementTest(unittest.TestCase):
    def test_multiclass_requires_prereqs(self):
        reg = _registry()
        # INT 11 → fails the Wizard prerequisite (needs INT >= 13).
        bad = {"classes": [{"class": "c_fighter", "level": 2},
                           {"class": "c_wizard", "level": 3}],
               "ability_scores": _scores(int_=11), "weapons": []}
        with self.assertRaises(ValueError) as ctx:
            build_pc_template(bad, reg)
        self.assertIn("prerequisite", str(ctx.exception).lower())
        self.assertIn("c_wizard", str(ctx.exception))

    def test_single_class_has_no_ability_prereq(self):
        # A single-class Wizard with INT 8 still builds (initial class has no
        # multiclass prereq).
        reg = _registry()
        t = build_pc_template(
            {"class": "c_wizard", "level": 1,
             "ability_scores": _scores(int_=8), "weapons": []}, reg)
        self.assertEqual(t["levels"], {"wizard": 1})

    def test_pb_boundary_crossed_by_total_level(self):
        # Cleric 4 / Wizard 1 = total 5 → PB +3 (each class alone would be +2).
        reg = _registry()
        t = build_pc_template(
            {"classes": [{"class": "c_cleric", "level": 4},
                         {"class": "c_wizard", "level": 1}],
             "ability_scores": _scores(wis=16, int_=13), "weapons": []}, reg)
        self.assertEqual(t["cr"]["proficiency_bonus"], 3)


class SpecValidationTest(unittest.TestCase):
    def test_both_classes_and_class_is_error(self):
        reg = _registry()
        with self.assertRaises(ValueError):
            build_pc_template(
                {"class": "c_wizard", "level": 1,
                 "classes": [{"class": "c_wizard", "level": 1}],
                 "ability_scores": _scores()}, reg)

    def test_total_level_over_20_is_error(self):
        reg = _registry()
        with self.assertRaises(ValueError):
            build_pc_template(
                {"classes": [{"class": "c_fighter", "level": 11},
                             {"class": "c_wizard", "level": 11}],
                 "ability_scores": _scores(int_=13)}, reg)

    def test_duplicate_class_is_error(self):
        reg = _registry()
        with self.assertRaises(ValueError):
            build_pc_template(
                {"classes": [{"class": "c_wizard", "level": 2},
                             {"class": "c_wizard", "level": 3}],
                 "ability_scores": _scores()}, reg)


class ResourcesMulticlassTest(unittest.TestCase):
    def test_primary_class_resources_derived_for_classes_list(self):
        # Fighter-primary multiclass: Second Wind (Fighter L1) resource present,
        # derived from the primary class even with a `classes:` spec.
        reg = _registry()
        spec = {"classes": [{"class": "c_fighter", "level": 2},
                            {"class": "c_wizard", "level": 3}],
                "ability_scores": _scores(), "weapons": []}
        res = derive_pc_resources(spec, reg)
        self.assertIn("second_wind_uses_remaining", res)

    def test_malformed_spec_returns_empty(self):
        reg = _registry()
        self.assertEqual(derive_pc_resources({}, reg), {})


if __name__ == "__main__":
    unittest.main()
