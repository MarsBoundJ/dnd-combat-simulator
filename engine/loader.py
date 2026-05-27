"""Content loader — YAML in, validated entities out.

Walks the schema/content/ tree, loads YAML files, validates against
the JSON Schemas in schema/definitions/, returns dict-of-dicts keyed
by entity id.

For the skeleton: loads what's needed for the smoke test. Robust
incremental loading (selective content packs, lazy loading) is post-MVP.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
import jsonschema


# Entity type → directory mapping
_ENTITY_DIRS = {
    "class": "classes",
    "subclass": "subclasses",
    "feature": "features",
    "monster": "monsters",
    "spell": "spells",
    "condition": "conditions",
    "race": "races",     # PR #75 — SRD species (Dwarf/Elf/Halfling/Human)
}

# Entity type → JSON Schema filename
_ENTITY_SCHEMAS = {
    "class": "class.schema.json",
    "subclass": "subclass.schema.json",
    "feature": "feature.schema.json",
    "monster": "monster.schema.json",
    "spell": "spell.schema.json",
    "condition": "condition.schema.json",
    # `race` schema deferred — loader silently skips validation for
    # entity types without a corresponding schema file. PR #75 ships
    # the race YAMLs + loader registration; a follow-up PR can add
    # the strict JSON Schema.
}


class ContentRegistry:
    """In-memory registry of all loaded content, keyed by entity type + id."""

    def __init__(self) -> None:
        self._content: dict[str, dict[str, Any]] = {
            etype: {} for etype in _ENTITY_DIRS
        }

    def add(self, entity_type: str, entity: dict) -> None:
        if entity_type not in self._content:
            raise ValueError(f"Unknown entity type: {entity_type!r}")
        self._content[entity_type][entity["id"]] = entity

    def get(self, entity_type: str, entity_id: str) -> dict:
        try:
            return self._content[entity_type][entity_id]
        except KeyError as e:
            raise KeyError(
                f"Content not found: {entity_type}/{entity_id}"
            ) from e

    def all(self, entity_type: str) -> dict[str, Any]:
        return dict(self._content[entity_type])

    def count(self) -> dict[str, int]:
        return {etype: len(items) for etype, items in self._content.items()}


def load_content(content_root: Path, validate: bool = True,
                 schema_root: Path | None = None) -> ContentRegistry:
    """Load all YAML files under content_root, organized by entity type.

    Validates against JSON Schemas in schema_root if validate=True.
    """
    if schema_root is None:
        schema_root = content_root.parent / "definitions"

    registry = ContentRegistry()
    schemas: dict[str, dict] = {}

    if validate:
        for etype, schema_file in _ENTITY_SCHEMAS.items():
            schema_path = schema_root / schema_file
            if schema_path.exists():
                with open(schema_path, "r", encoding="utf-8") as fh:
                    schemas[etype] = json.load(fh)

    for etype, subdir in _ENTITY_DIRS.items():
        entity_dir = content_root / subdir
        if not entity_dir.exists():
            continue
        for yaml_path in sorted(entity_dir.glob("*.yaml")):
            with open(yaml_path, "r", encoding="utf-8") as fh:
                entity = yaml.safe_load(fh)
            if entity is None:
                continue
            if validate and etype in schemas:
                # Note: $ref resolution to common.schema.json requires
                # a proper $ref resolver. For the skeleton we skip strict
                # validation when $refs cross files; just check the top-level
                # required fields.
                try:
                    _validate_lite(entity, schemas[etype])
                except jsonschema.ValidationError as e:
                    raise ValueError(
                        f"Validation failed for {yaml_path}: {e.message}"
                    ) from e
            registry.add(etype, entity)

    return registry


def _validate_lite(entity: dict, schema: dict) -> None:
    """Skeleton-grade validation: check required top-level fields only.

    Full JSON Schema validation with cross-file $ref resolution is a
    post-MVP enhancement.
    """
    for field in schema.get("required", []):
        if field not in entity:
            raise jsonschema.ValidationError(
                f"Missing required field: {field}"
            )


def load_yaml_file(path: Path) -> Any:
    """Convenience: load a single YAML file."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
