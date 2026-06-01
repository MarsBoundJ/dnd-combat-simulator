"""Subclass consumption in pc_schema.

Before this, subclass YAMLs (sc_champion, sc_evoker) were orphan content:
they loaded + validated but build_pc_template never applied them to a PC.
This wires `pc_spec.subclass: sc_<id>` into the feature-collection path so
a subclass's features_by_level merge into features_known.

Layers:
  1. A Champion Fighter gains the subclass's L3 features (was orphaned)
  2. Feature level-gating: higher-level subclass features only at level
  3. An Evoker Wizard gains its subclass features (second subclass proof)
  4. derive_pc_resources also sees subclass features
  5. template stamps the chosen subclass id
  6. No subclass → unchanged (backward compatibility)
  7. Validation: unknown id / wrong parent class / below grant level raise
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _abilities():
    return {"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10}


class SubclassConsumptionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                      schema_root=SCHEMA_ROOT)

    # --- Layer 1+2: Champion Fighter feature merge + level gating ---

    def test_champion_l3_gains_subclass_features(self) -> None:
        pc = {"id": "f1", "class": "c_fighter", "level": 3,
              "subclass": "sc_champion", "ability_scores": _abilities(),
              "weapons": []}
        tmpl = build_pc_template(pc, self.registry)
        feats = set(tmpl.get("features_known", []))
        # L3 Champion features (previously never applied)
        self.assertIn("f_improved_critical", feats)
        self.assertIn("f_remarkable_athlete", feats)
        # L15/L18 features NOT yet present at L3
        self.assertNotIn("f_superior_critical", feats)
        self.assertNotIn("f_survivor", feats)

    def test_champion_l18_gains_all_lower_features(self) -> None:
        pc = {"id": "f18", "class": "c_fighter", "level": 18,
              "subclass": "sc_champion", "ability_scores": _abilities(),
              "weapons": []}
        tmpl = build_pc_template(pc, self.registry)
        feats = set(tmpl.get("features_known", []))
        for fid in ("f_improved_critical", "f_remarkable_athlete",
                     "f_superior_critical", "f_survivor"):
            self.assertIn(fid, feats)

    # --- Layer 3: second subclass (Evoker Wizard) ---

    def test_evoker_gains_subclass_features(self) -> None:
        pc = {"id": "w3", "class": "c_wizard", "level": 3,
              "subclass": "sc_evoker", "ability_scores": _abilities(),
              "weapons": []}
        tmpl = build_pc_template(pc, self.registry)
        feats = set(tmpl.get("features_known", []))
        self.assertIn("f_evocation_savant", feats)
        self.assertIn("f_potent_cantrip", feats)

    # --- Layer 4: derive_pc_resources sees subclass features ---

    def test_derive_resources_includes_subclass(self) -> None:
        # Champion's L3 features don't drive a resource counter, but the
        # merge must not crash and must run the same path. We assert the
        # function completes and returns a dict (regression guard for the
        # merge wiring in derive_pc_resources).
        pc = {"id": "f3", "class": "c_fighter", "level": 3,
              "subclass": "sc_champion", "ability_scores": _abilities()}
        res = derive_pc_resources(pc, self.registry)
        self.assertIsInstance(res, dict)

    # --- Layer 5: template stamps the subclass id ---

    def test_template_stamps_subclass_id(self) -> None:
        pc = {"id": "f3", "class": "c_fighter", "level": 3,
              "subclass": "sc_champion", "ability_scores": _abilities(),
              "weapons": []}
        tmpl = build_pc_template(pc, self.registry)
        self.assertEqual(tmpl.get("subclass"), "sc_champion")

    # --- Layer 6: backward compatibility (no subclass) ---

    def test_no_subclass_is_unchanged(self) -> None:
        pc = {"id": "f3", "class": "c_fighter", "level": 3,
              "ability_scores": _abilities(), "weapons": []}
        tmpl = build_pc_template(pc, self.registry)
        feats = set(tmpl.get("features_known", []))
        self.assertNotIn("f_improved_critical", feats)
        self.assertIsNone(tmpl.get("subclass"))

    # --- Layer 7: validation ---

    def test_unknown_subclass_raises(self) -> None:
        pc = {"id": "f3", "class": "c_fighter", "level": 3,
              "subclass": "sc_nonexistent", "ability_scores": _abilities(),
              "weapons": []}
        with self.assertRaises(ValueError):
            build_pc_template(pc, self.registry)

    def test_wrong_parent_class_raises(self) -> None:
        # sc_evoker is a Wizard subclass — putting it on a Fighter fails.
        pc = {"id": "f3", "class": "c_fighter", "level": 3,
              "subclass": "sc_evoker", "ability_scores": _abilities(),
              "weapons": []}
        with self.assertRaises(ValueError):
            build_pc_template(pc, self.registry)

    def test_below_grant_level_raises(self) -> None:
        # Champion can't be chosen at L2 (Fighter grants subclass at L3).
        pc = {"id": "f2", "class": "c_fighter", "level": 2,
              "subclass": "sc_champion", "ability_scores": _abilities(),
              "weapons": []}
        with self.assertRaises(ValueError):
            build_pc_template(pc, self.registry)


if __name__ == "__main__":
    unittest.main()
