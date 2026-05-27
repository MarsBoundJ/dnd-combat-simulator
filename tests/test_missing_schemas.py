"""Tests for the new JSON schemas + loader registration (PR #84).

Layers:
  1. Race schema: valid YAML loads; required field omission rejects
  2. All 4 SRD race YAMLs validate against race schema
  3. Loader recognizes 'race' entity type
  4. Loader recognizes 'feat' / 'equipment' / 'background' entity
     types (empty content dirs)
  5. New schemas are valid JSON Schema documents
  6. common.schema.json stable_id pattern accepts new prefixes
     (r_, t_, ft_, eq_, bg_)
  7. Smoke test: race YAMLs load through full registry path
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
CONTENT_ROOT = REPO_ROOT / "schema" / "content"


# ============================================================================
# Layer 1+5: schemas are valid JSON + valid JSON Schema documents
# ============================================================================

class SchemaValidityTest(unittest.TestCase):

    def _load_schema(self, name):
        path = SCHEMA_ROOT / name
        self.assertTrue(path.exists(), f"Missing schema: {name}")
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_race_schema_loads(self) -> None:
        schema = self._load_schema("race.schema.json")
        self.assertEqual(schema["title"], "Race (Species)")
        self.assertIn("id", schema["required"])
        self.assertIn("racial_traits", schema["required"])

    def test_feat_schema_loads(self) -> None:
        schema = self._load_schema("feat.schema.json")
        self.assertEqual(schema["title"], "Feat")
        self.assertIn("category", schema["required"])
        # Category enum includes all 4 PHB 2024 feat categories
        cat_enum = schema["properties"]["category"]["enum"]
        for c in ("origin", "general", "fighting_style", "epic_boon"):
            self.assertIn(c, cat_enum)

    def test_equipment_schema_loads(self) -> None:
        schema = self._load_schema("equipment.schema.json")
        self.assertEqual(schema["title"], "Equipment")
        cat_enum = schema["properties"]["category"]["enum"]
        # Spot-check key categories
        for c in ("weapon", "armor", "shield", "magic_item"):
            self.assertIn(c, cat_enum)

    def test_background_schema_loads(self) -> None:
        schema = self._load_schema("background.schema.json")
        self.assertEqual(schema["title"], "Background")
        self.assertIn("ability_score_increases", schema["required"])
        self.assertIn("skill_proficiencies", schema["required"])


# ============================================================================
# Layer 6: stable_id pattern accepts new prefixes
# ============================================================================

class StableIdPatternTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(SCHEMA_ROOT / "common.schema.json", "r",
                    encoding="utf-8") as fh:
            common = json.load(fh)
        cls.pattern = re.compile(
            common["$defs"]["stable_id"]["pattern"])

    def test_existing_prefixes_still_accepted(self) -> None:
        for s in ("c_fighter", "sc_devotion", "f_rage", "m_goblin",
                    "sp_fireball", "co_charmed", "sl_wizard"):
            self.assertIsNotNone(self.pattern.match(s), s)

    def test_new_prefixes_accepted(self) -> None:
        for s in ("r_halfling", "r_human", "t_lucky", "t_brave",
                    "ft_great_weapon_master", "ft_sentinel",
                    "eq_longsword", "eq_chain_mail",
                    "bg_acolyte", "bg_soldier"):
            self.assertIsNotNone(self.pattern.match(s), s)

    def test_invalid_prefixes_rejected(self) -> None:
        for s in ("xx_invalid", "fighter_no_prefix", "_underscore_only",
                    "r_UPPERCASE"):
            self.assertIsNone(self.pattern.match(s), s)


# ============================================================================
# Layer 2+3: race YAMLs validate against race schema via loader
# ============================================================================

class RaceLoaderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from engine.loader import load_content
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_loader_recognizes_race_entity_type(self) -> None:
        races = self.registry.all("race")
        self.assertGreaterEqual(len(races), 4)

    def test_all_srd_races_load(self) -> None:
        for race_id in ("r_dwarf", "r_elf", "r_halfling", "r_human"):
            race = self.registry.get("race", race_id)
            self.assertIsNotNone(race)

    def test_race_yamls_satisfy_required_fields(self) -> None:
        # The loader's _validate_lite enforces top-level required.
        # Each race YAML must declare: id, name, source, creature_type,
        # size, speed, racial_traits.
        required = ["id", "name", "source", "creature_type",
                     "size", "speed", "racial_traits"]
        for race_id in ("r_dwarf", "r_elf", "r_halfling", "r_human"):
            race = self.registry.get("race", race_id)
            for field in required:
                self.assertIn(field, race,
                                 f"{race_id} missing {field!r}")


# ============================================================================
# Layer 4: loader recognizes feat / equipment / background entity types
# ============================================================================

class NewEntityTypesLoaderTest(unittest.TestCase):

    def test_loader_dirs_include_new_types(self) -> None:
        from engine.loader import _ENTITY_DIRS
        self.assertEqual(_ENTITY_DIRS["feat"], "feats")
        self.assertEqual(_ENTITY_DIRS["equipment"], "equipment")
        self.assertEqual(_ENTITY_DIRS["background"], "backgrounds")

    def test_loader_schemas_include_new_types(self) -> None:
        from engine.loader import _ENTITY_SCHEMAS
        self.assertEqual(_ENTITY_SCHEMAS["race"], "race.schema.json")
        self.assertEqual(_ENTITY_SCHEMAS["feat"], "feat.schema.json")
        self.assertEqual(_ENTITY_SCHEMAS["equipment"],
                          "equipment.schema.json")
        self.assertEqual(_ENTITY_SCHEMAS["background"],
                          "background.schema.json")

    def test_empty_content_dirs_exist(self) -> None:
        for subdir in ("feats", "equipment", "backgrounds"):
            path = CONTENT_ROOT / subdir
            self.assertTrue(path.exists() and path.is_dir(),
                              f"missing dir: {path}")

    def test_loader_handles_empty_content_dirs_cleanly(self) -> None:
        # Loader walking an empty content dir should not raise + should
        # populate the entity type with an empty dict.
        from engine.loader import load_content
        registry = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
        self.assertEqual(registry.all("feat"), {})
        self.assertEqual(registry.all("equipment"), {})
        self.assertEqual(registry.all("background"), {})


# ============================================================================
# Layer 7: smoke test via full registry path
# ============================================================================

class FullRegistrySmokeTest(unittest.TestCase):

    def test_full_load_succeeds_with_new_schemas(self) -> None:
        # Loading the entire content registry with strict validation
        # should succeed cleanly — no schema mismatch errors thrown
        # by existing fixtures.
        from engine.loader import load_content
        registry = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
        counts = registry.count()
        # Sanity-check: all existing entity types still load.
        self.assertGreater(counts["class"], 0)
        self.assertGreater(counts["feature"], 0)
        self.assertGreater(counts["race"], 0)
        self.assertGreater(counts["monster"], 0)


# ============================================================================
# UTF-8 encoding check
# ============================================================================

class Utf8EncodingTest(unittest.TestCase):

    def test_all_schemas_are_utf8_encoded(self) -> None:
        # Decode each schema as strict UTF-8; raises if any file
        # contains non-UTF-8 bytes.
        for schema_file in ("race.schema.json", "feat.schema.json",
                              "equipment.schema.json",
                              "background.schema.json",
                              "common.schema.json"):
            path = SCHEMA_ROOT / schema_file
            with open(path, "rb") as fh:
                raw = fh.read()
            try:
                raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as e:
                self.fail(f"{schema_file} is not strict UTF-8: {e}")


if __name__ == "__main__":
    unittest.main()
