"""WS-A1 — entity-schema validation for the four PC building-block types
(background, feat, equipment, magic_item).

These exercise the *schemas themselves* against minimal inline fixtures — no
content YAML is created (that is A2–A8's territory; fixtures stay inline here).

Coverage per type:
  - the schema file is well-formed JSON Schema (Draft 2020-12 meta-check);
  - a minimal valid fixture passes full validation (cross-file $ref to
    common.schema.json resolved via a referencing registry);
  - a fixture missing a required field is rejected;
  - an enum violation (bad `source`, `category`, `rarity`, `kind`) is rejected;
  - the loader's actual enforcement path (_validate_lite — top-level required
    fields only) accepts the minimal fixture and rejects a missing-required one.

Plus loader-registration tests: the four types are wired into _ENTITY_DIRS /
_ENTITY_SCHEMAS, point at real schema files, and appear in a real load.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource

from engine.loader import (
    _ENTITY_DIRS, _ENTITY_SCHEMAS, _validate_lite, load_content,
)

REPO_ROOT = Path(__file__).parent.parent
DEFS = REPO_ROOT / "schema" / "definitions"
CONTENT_ROOT = REPO_ROOT / "schema" / "content"

NEW_TYPES = ("background", "feat", "equipment", "magic_item")


def _registry() -> Registry:
    """A referencing Registry of every schema in definitions/, keyed by its
    $id, so relative cross-file $refs (e.g. common.schema.json#/$defs/source)
    resolve against the referring schema's base URI."""
    resources = []
    for path in DEFS.glob("*.schema.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def _schema(entity_type: str) -> dict:
    return json.loads((DEFS / _ENTITY_SCHEMAS[entity_type]).read_text(encoding="utf-8"))


def _validator(entity_type: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_schema(entity_type), registry=_registry())


# ── Minimal VALID fixtures (only required fields + a representative extra) ──

VALID = {
    "background": {
        "id": "bg_test_soldier",
        "name": "Test Soldier",
        "source": "srd_5.2.1",
        "ability_scores": {"choices": ["strength", "dexterity", "constitution"]},
        "feat": "ft_savage_attacker",
        "skill_proficiencies": ["athletics", "intimidation"],
    },
    "feat": {
        "id": "ft_test_feat",
        "name": "Test Feat",
        "source": "srd_5.2.1",
        "category": "general",
    },
    "equipment": {
        "id": "eq_test_longsword",
        "name": "Test Longsword",
        "source": "srd_5.2.1",
        "kind": "weapon",
    },
    "magic_item": {
        "id": "mi_test_ring",
        "name": "Test Ring",
        "source": "srd_5.2.1",
        "category": "ring",
        "rarity": "rare",
    },
}

# ── Rich fixtures (exercise the optional structure + the effect/casts hooks) ──

RICH = {
    "background": {
        "id": "bg_rich",
        "name": "Rich Background",
        "source": "phb_2024",
        "ability_scores": {
            "choices": ["intelligence", "wisdom", "charisma"],
            "increase_rule": "plus2_plus1_or_plus1_each",
        },
        "feat": "ft_magic_initiate",
        "skill_proficiencies": ["insight", "religion"],
        "tool_proficiency": {"choose_from": "artisans_tools"},
        "equipment": {
            "options": [
                {"label": "A", "items": [{"item": "eq_quarterstaff", "quantity": 1}, "Holy Symbol"], "gold_gp": 8},
                {"label": "B", "items": [], "gold_gp": 50},
            ]
        },
        "aliases": ["acolyte_variant"],
        "public_name": "Devotee",
        "stage4_stub": {"lore": {"ideals": "faith"}},
    },
    "feat": {
        "id": "ft_rich",
        "name": "Rich Feat",
        "source": "phb_2024",
        "category": "general",
        "prerequisites": {
            "min_level": 4,
            "ability_scores": [{"ability": "strength", "min": 13},
                               {"ability": "dexterity", "min": 13}],
            "ability_scores_all_required": False,
            "requires_feature": ["f_fighting_style"],
        },
        "repeatable": False,
        "ability_score_increase": {
            "points": 1, "per_ability_max": 1,
            "from": ["strength", "dexterity"], "max_score": 20,
        },
        "grants": {"skill_proficiencies": ["athletics"]},
        "effect_primitives": [
            {"primitive": "attack_modifier", "params": {"value": 1}},
        ],
        "aliases": ["gwm"],
        "stage4_stub": {"notes": "x"},
    },
    "equipment": {
        "id": "eq_rich_armor",
        "name": "Rich Armor",
        "source": "srd_5.2.1",
        "kind": "armor",
        "cost": {"quantity": 50, "unit": "gp"},
        "weight_lb": 20,
        "armor": {
            "category": "medium",
            "base_ac": 14,
            "add_dex_modifier": True,
            "max_dex_bonus": 2,
            "strength_requirement": 0,
            "stealth_disadvantage": True,
            "don_time": "5 minutes",
            "doff_time": "1 minute",
        },
        "aliases": ["scalemail"],
        "stage4_stub": {},
    },
    "magic_item": {
        "id": "mi_rich",
        "name": "Rich Item",
        "source": "srd_5.2.1",
        "category": "wand",
        "rarity": "rare",
        "attunement": {"required": True, "requirement": "by a Spellcaster"},
        "consumable": False,
        "activation": {"cost": "action"},
        "charges": {"max": 7, "recharge": {"dice": "1d6+1", "period": "dawn"},
                    "destroy_on_last_charge": True},
        "bonus": {"ac": 1, "saving_throws": 1},
        "casts": [{"spell": "sp_fireball", "charge_cost": 3, "save_dc": 15}],
        "effect_primitives": [{"primitive": "save_modifier", "params": {"value": 1}}],
        "applies_to": {"equipment_kind": "weapon", "restriction": "any Simple or Martial"},
        "public_name": "Mystic Wand",
        "stage4_stub": {"lore": "x"},
    },
}

# ── A required field to drop, and an enum field to corrupt, per type ──

DROP_REQUIRED = {
    "background": "ability_scores",
    "feat": "category",
    "equipment": "kind",
    "magic_item": "rarity",
}

BAD_ENUM = {
    "background": ("source", "DnDBeyond"),
    "feat": ("category", "super_feat"),
    "equipment": ("kind", "vehicle"),
    "magic_item": ("category", "artifact_armor"),
}


class SchemaWellFormedTest(unittest.TestCase):
    """Each new schema is itself a valid Draft 2020-12 JSON Schema."""

    def test_schemas_are_valid_jsonschema(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                jsonschema.Draft202012Validator.check_schema(_schema(etype))

    def test_schemas_reuse_common_source_enum(self):
        # The plan requires the shared source enum is reused, not redefined.
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                src = _schema(etype)["properties"]["source"]
                self.assertEqual(src.get("$ref"),
                                 "common.schema.json#/$defs/source")

    def test_schemas_expose_alias_and_stage4_hooks(self):
        # §3.8 rename hook + §3.10 namespaced stub blob on every type.
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                props = _schema(etype)["properties"]
                self.assertIn("public_name", props)
                self.assertIn("stage4_stub", props)
                self.assertTrue(props["stage4_stub"].get("additionalProperties"))


class ValidFixtureTest(unittest.TestCase):
    """Minimal and rich fixtures validate fully (cross-file refs resolved)."""

    def test_minimal_fixtures_validate(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                _validator(etype).validate(VALID[etype])

    def test_rich_fixtures_validate(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                _validator(etype).validate(RICH[etype])


class RejectionTest(unittest.TestCase):
    """Bad fixtures are rejected under full validation."""

    def test_missing_required_field_rejected(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                bad = dict(VALID[etype])
                del bad[DROP_REQUIRED[etype]]
                with self.assertRaises(jsonschema.ValidationError):
                    _validator(etype).validate(bad)

    def test_bad_enum_value_rejected(self):
        for etype in NEW_TYPES:
            field, bad_value = BAD_ENUM[etype]
            with self.subTest(entity=etype, field=field):
                bad = dict(VALID[etype])
                bad[field] = bad_value
                with self.assertRaises(jsonschema.ValidationError):
                    _validator(etype).validate(bad)

    def test_bad_id_prefix_rejected(self):
        # Each type pins its own id prefix (bg_/ft_/eq_/mi_).
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                bad = dict(VALID[etype])
                bad["id"] = "wrongprefix_thing"
                with self.assertRaises(jsonschema.ValidationError):
                    _validator(etype).validate(bad)

    def test_malformed_effect_primitive_rejected(self):
        # The mechanical-effect hook reuses common.effect_primitive, whose
        # only required field is `primitive`. An entry without it must fail —
        # proving the cross-file ref is live for the effect hook too.
        bad_feat = dict(VALID["feat"])
        bad_feat["effect_primitives"] = [{"params": {"value": 1}}]
        with self.assertRaises(jsonschema.ValidationError):
            _validator("feat").validate(bad_feat)


class LiteValidationParityTest(unittest.TestCase):
    """The loader enforces only top-level required fields (_validate_lite).
    Confirm the minimal fixtures pass it and a missing-required one raises —
    this is the behavior real content load actually exercises."""

    def test_lite_accepts_minimal(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                _validate_lite(VALID[etype], _schema(etype))  # no raise

    def test_lite_rejects_missing_required(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                bad = dict(VALID[etype])
                del bad[DROP_REQUIRED[etype]]
                with self.assertRaises(jsonschema.ValidationError):
                    _validate_lite(bad, _schema(etype))


class LoaderRegistrationTest(unittest.TestCase):
    """The four types are registered and load cleanly (empty until A2–A8)."""

    def test_types_registered_in_both_dicts(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                self.assertIn(etype, _ENTITY_DIRS)
                self.assertIn(etype, _ENTITY_SCHEMAS)

    def test_registered_schema_files_exist(self):
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                self.assertTrue((DEFS / _ENTITY_SCHEMAS[etype]).exists())

    def test_load_content_includes_new_types(self):
        reg = load_content(CONTENT_ROOT, validate=True, schema_root=DEFS)
        counts = reg.count()
        for etype in NEW_TYPES:
            with self.subTest(entity=etype):
                self.assertIn(etype, counts)  # present (0 until content lands)

    def test_existing_content_still_loads(self):
        reg = load_content(CONTENT_ROOT, validate=True, schema_root=DEFS)
        # Regression guard: registering new types didn't disturb existing load.
        self.assertGreater(reg.count()["monster"], 0)


if __name__ == "__main__":
    unittest.main()
