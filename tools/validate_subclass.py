#!/usr/bin/env python3
"""Validate subclass + feature YAML files for completeness and consistency.

Usage:
    python tools/validate_subclass.py                          # validate ALL subclasses
    python tools/validate_subclass.py sc_battle_master          # validate one subclass
    python tools/validate_subclass.py --class c_fighter          # validate all subclasses for a class
    python tools/validate_subclass.py --summary                  # print coverage matrix
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SC_DIR = REPO / "schema" / "content" / "subclasses"
FEAT_DIR = REPO / "schema" / "content" / "features"
CLASS_DIR = REPO / "schema" / "content" / "classes"
SCHEMA_DIR = REPO / "schema" / "definitions"

SUBCLASS_FEATURE_LEVELS = {
    "c_barbarian": [3, 6, 10, 14],
    "c_bard":      [3, 6, 14],
    "c_cleric":    [3, 6, 17],
    "c_druid":     [3, 6, 10, 14],
    "c_fighter":   [3, 7, 10, 15, 18],
    "c_monk":      [3, 6, 11, 17],
    "c_paladin":   [3, 7, 15, 20],
    "c_ranger":    [3, 7, 11, 15],
    "c_rogue":     [3, 9, 13, 17],
    "c_sorcerer":  [3, 6, 14, 18],
    "c_warlock":   [3, 6, 10, 14],
    "c_wizard":    [3, 6, 10, 14],
}

VALID_TYPES = {"passive", "active", "triggered", "triggered_choice", "compound"}
VALID_ARCHETYPES = {
    "berserker_fanatic", "apex_predator", "cunning_tactician",
    "primal_guardian", "pack_alpha", "opportunistic_skirmisher",
    "cautious_defender",
}
VALID_ROLES = {
    "striker", "martial_striker", "arcane_striker", "blaster",
    "controller", "healer", "tank", "support", "skirmisher",
}


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def validate_subclass(sc_path: Path) -> list[str]:
    """Return a list of error strings (empty = valid)."""
    errors = []
    try:
        sc = load_yaml(sc_path)
    except Exception as e:
        return [f"YAML parse error: {e}"]

    sc_id = sc.get("id")
    if not sc_id:
        errors.append("missing 'id'")
        return errors

    expected_filename = f"{sc_id}.yaml"
    if sc_path.name != expected_filename:
        errors.append(f"filename '{sc_path.name}' != expected '{expected_filename}'")

    for field in ("name", "source", "parent_class"):
        if not sc.get(field):
            errors.append(f"missing required field '{field}'")

    parent = sc.get("parent_class", "")
    class_path = CLASS_DIR / f"{parent}.yaml"
    if parent and not class_path.exists():
        errors.append(f"parent_class '{parent}' has no file at {class_path}")

    tags = sc.get("archetype_tags", {})
    if not tags:
        errors.append("missing 'archetype_tags'")
    else:
        ba = tags.get("behavior_archetype")
        if ba and ba not in VALID_ARCHETYPES:
            errors.append(f"unknown behavior_archetype '{ba}' — known: {sorted(VALID_ARCHETYPES)}")
        role = tags.get("role")
        if role and role not in VALID_ROLES:
            errors.append(f"unknown role '{role}' — known: {sorted(VALID_ROLES)}")
        if not tags.get("flavor_tags"):
            errors.append("missing archetype_tags.flavor_tags")

    fbl = sc.get("features_by_level")
    if not fbl:
        errors.append("missing 'features_by_level'")
        return errors

    expected_levels = SUBCLASS_FEATURE_LEVELS.get(parent, [])
    defined_levels = sorted(entry.get("level", 0) for entry in fbl)

    if expected_levels:
        missing_levels = [l for l in expected_levels if l not in defined_levels]
        extra_levels = [l for l in defined_levels if l not in expected_levels]
        if missing_levels:
            errors.append(
                f"missing features_by_level entries for levels {missing_levels} "
                f"(2024 PHB expects {expected_levels} for {parent})")
        if extra_levels:
            errors.append(f"unexpected levels {extra_levels} not in 2024 PHB schedule for {parent}")

    all_feature_ids = []
    for entry in fbl:
        level = entry.get("level")
        fids = entry.get("feature_ids", [])
        if not fids:
            errors.append(f"level {level}: empty feature_ids list")
        for fid in fids:
            all_feature_ids.append((level, fid))

    for level, fid in all_feature_ids:
        feat_path = FEAT_DIR / f"{fid}.yaml"
        if not feat_path.exists():
            errors.append(f"level {level}: feature '{fid}' has no file at {feat_path}")
            continue

        try:
            feat = load_yaml(feat_path)
        except Exception as e:
            errors.append(f"level {level}: feature '{fid}' YAML parse error: {e}")
            continue

        if feat.get("id") != fid:
            errors.append(f"level {level}: feature file id '{feat.get('id')}' != expected '{fid}'")

        feat_type = feat.get("type")
        if feat_type not in VALID_TYPES:
            errors.append(f"level {level}: feature '{fid}' has invalid type '{feat_type}'")

        granted = feat.get("granted_by", {})
        # Shared features (e.g. f_extra_attack) are deliberately reused by
        # multiple classes/subclasses and declare `granted_by.class` instead
        # of a single subclass+level. Exempt them from the subclass/level
        # match — a subclass legitimately grants such a feature at its own
        # level (College of Valor grants the shared Extra Attack at L6).
        if "class" in granted:
            pass
        else:
            if granted.get("subclass") != sc_id:
                errors.append(
                    f"level {level}: feature '{fid}' granted_by.subclass = "
                    f"'{granted.get('subclass')}', expected '{sc_id}'")
            if granted.get("level") != level:
                errors.append(
                    f"level {level}: feature '{fid}' granted_by.level = "
                    f"{granted.get('level')}, expected {level}")

        for req in ("name", "source"):
            if not feat.get(req):
                errors.append(f"level {level}: feature '{fid}' missing '{req}'")

    return errors


def print_coverage_matrix():
    """Show which classes have subclasses and which levels are covered."""
    classes = sorted(SUBCLASS_FEATURE_LEVELS.keys())
    sc_files = list(SC_DIR.glob("sc_*.yaml"))
    sc_by_class: dict[str, list[dict]] = {c: [] for c in classes}
    for path in sc_files:
        try:
            sc = load_yaml(path)
            parent = sc.get("parent_class", "")
            if parent in sc_by_class:
                levels = sorted(e.get("level", 0) for e in sc.get("features_by_level", []))
                sc_by_class[parent].append({"id": sc["id"], "name": sc.get("name", "?"), "levels": levels})
        except Exception:
            pass

    total_expected = 0
    total_have = 0

    print(f"\n{'CLASS':<16} {'EXPECTED LEVELS':<22} {'SUBCLASSES'}")
    print("-" * 80)
    for cls in classes:
        expected = SUBCLASS_FEATURE_LEVELS[cls]
        subs = sc_by_class[cls]
        if subs:
            for i, sub in enumerate(subs):
                covered = [l for l in expected if l in sub["levels"]]
                missing = [l for l in expected if l not in sub["levels"]]
                status = "COMPLETE" if not missing else f"missing L{missing}"
                prefix = cls if i == 0 else ""
                exp_str = str(expected) if i == 0 else ""
                print(f"  {prefix:<14} {exp_str:<22} {sub['id']:<32} {status}")
                total_have += 1
        else:
            print(f"  {cls:<14} {str(expected):<22} --- NONE ---")
        total_expected += 4

    print("-" * 80)
    print(f"  Total: {total_have} subclasses defined across {len(classes)} classes")
    print(f"  2024 PHB has 4 subclasses per class = 48 total; {48 - total_have} remaining\n")


def main():
    parser = argparse.ArgumentParser(description="Validate subclass YAML files")
    parser.add_argument("subclass_id", nargs="?", help="Specific subclass ID to validate")
    parser.add_argument("--class", dest="class_id", help="Validate all subclasses for a class")
    parser.add_argument("--summary", action="store_true", help="Print coverage matrix")
    parser.add_argument("--all", action="store_true", help="Validate all subclasses")
    args = parser.parse_args()

    if args.summary:
        print_coverage_matrix()
        return

    if args.subclass_id:
        paths = [SC_DIR / f"{args.subclass_id}.yaml"]
        if not paths[0].exists():
            print(f"ERROR: {paths[0]} does not exist")
            sys.exit(1)
    elif args.class_id:
        paths = []
        for p in sorted(SC_DIR.glob("sc_*.yaml")):
            try:
                sc = load_yaml(p)
                if sc.get("parent_class") == args.class_id:
                    paths.append(p)
            except Exception:
                pass
        if not paths:
            print(f"No subclasses found for {args.class_id}")
            sys.exit(1)
    else:
        paths = sorted(SC_DIR.glob("sc_*.yaml"))

    if not paths:
        print("No subclass files found.")
        sys.exit(1)

    all_ok = True
    for path in paths:
        errors = validate_subclass(path)
        sc_id = path.stem
        if errors:
            all_ok = False
            print(f"\nFAIL  {sc_id}")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"OK    {sc_id}")

    if all_ok:
        print(f"\nAll {len(paths)} subclass(es) valid.")
    else:
        print(f"\nValidation errors found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
