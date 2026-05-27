"""CLI entry point: `python -m engine encounter <encounter.yaml> [--seed N]`.

Stage 1 internal grading driver. Loads an encounter spec from YAML,
runs the engine, prints a human-readable summary + optional JSON dump.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from engine.core.state import Actor, Encounter, ability_modifier
from engine.core.runner import EncounterRunner
from engine.loader import load_content, load_yaml_file
from engine.reports import EncounterReport
from engine import primitives as primitives_module


# Default content + schema roots (relative to repo root)
DEFAULT_CONTENT_ROOT = Path("schema/content")
DEFAULT_SCHEMA_ROOT = Path("schema/definitions")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim",
        description="D&D 5e combat simulator — Phase 1 engine skeleton.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enc = subparsers.add_parser("encounter", help="Run a single encounter from a YAML file.")
    enc.add_argument("encounter_file", type=Path, help="Path to encounter YAML.")
    enc.add_argument("--seed", type=int, default=None, help="RNG seed for deterministic runs.")
    enc.add_argument("--content", type=Path, default=DEFAULT_CONTENT_ROOT)
    enc.add_argument("--schemas", type=Path, default=DEFAULT_SCHEMA_ROOT)
    enc.add_argument("--json", action="store_true", help="Print full JSON report instead of summary.")
    enc.add_argument("--quiet", action="store_true", help="Suppress event log in summary.")

    val = subparsers.add_parser("validate", help="Load + validate all content; report counts.")
    val.add_argument("--content", type=Path, default=DEFAULT_CONTENT_ROOT)
    val.add_argument("--schemas", type=Path, default=DEFAULT_SCHEMA_ROOT)

    args = parser.parse_args(argv)

    if args.command == "encounter":
        return _cmd_encounter(args)
    if args.command == "validate":
        return _cmd_validate(args)
    return 1


def _cmd_validate(args: argparse.Namespace) -> int:
    registry = load_content(args.content, validate=True, schema_root=args.schemas)
    counts = registry.count()
    print("Content loaded successfully.")
    for etype, n in counts.items():
        print(f"  {etype:12} : {n:3d}")
    return 0


def _cmd_encounter(args: argparse.Namespace) -> int:
    # Load library content (monsters, classes, conditions, etc.)
    registry = load_content(args.content, validate=True, schema_root=args.schemas)

    # Load the encounter spec
    spec = load_yaml_file(args.encounter_file)
    if spec is None:
        print(f"Error: empty encounter file {args.encounter_file}", file=sys.stderr)
        return 2

    encounter = _build_encounter(spec, registry)

    # Inject the seeded RNG into the primitive module (skeleton-grade)
    import random
    if args.seed is not None:
        primitives_module.set_rng(random.Random(args.seed))

    runner = EncounterRunner.new(encounter, seed=args.seed,
                                  content_registry=registry)
    primitives_module.set_rng(runner.rng)        # share the RNG
    state = runner.run(seed=args.seed)

    report = EncounterReport.from_state(state)

    if args.json:
        print(report.to_json())
    else:
        print(report.to_summary())
        if not args.quiet:
            print("\nEvent log:")
            for ev in report.event_log:
                print(f"  {ev}")
    return 0


def _build_encounter(spec: dict, registry) -> Encounter:
    """Build an Encounter from a spec + content registry."""
    actors: list[Actor] = []
    for actor_spec in spec.get("actors", []):
        actors.append(_build_actor(actor_spec, registry))
    return Encounter(
        id=spec.get("id", "unnamed_encounter"),
        actors=actors,
        environment=spec.get("environment", {}),
        initial_distances=spec.get("initial_distances", {}),
    )


def _build_actor(actor_spec: dict, registry) -> Actor:
    """Build one Actor from a spec entry.

    Three shapes supported:
      - `template_ref`: { entity_type: 'monster', id: 'm_goblin_warrior' }
        — pull a stat block from the registry.
      - `template`: full inline template (monster-style stat block).
      - `pc`: compact PC spec (class + level + ability_scores + armor +
        weapons) — derived into a full template via `engine.pc_schema.
        build_pc_template`. The user-facing surface for PC fixtures
        going forward.
    """
    # Resources auto-derived from a `pc:` spec (filled below if applicable).
    # Merged with any explicit `resources:` block on actor_spec, with the
    # explicit block winning on conflict (so authors can force edge cases).
    derived_pc_resources: dict = {}

    if "template_ref" in actor_spec:
        ref = actor_spec["template_ref"]
        template = registry.get(ref["entity_type"], ref["id"])
    elif "pc" in actor_spec:
        from engine.pc_schema import build_pc_template, derive_pc_resources
        template = build_pc_template(actor_spec["pc"], registry)
        # Surface spell_slots from the PC spec onto the actor_spec for
        # _build_actor's slot-population block below.
        if actor_spec["pc"].get("spell_slots") is not None \
                and actor_spec.get("spell_slots") is None:
            actor_spec = dict(actor_spec)
            actor_spec["spell_slots"] = actor_spec["pc"]["spell_slots"]
        # Auto-wire class-feature resources from the class level table.
        # Action Surge / Second Wind etc. — fixture authors no longer
        # need a manual `resources:` block to use these features.
        derived_pc_resources = derive_pc_resources(actor_spec["pc"], registry)
    else:
        template = actor_spec["template"]

    instance_id = actor_spec.get("instance_id") or template["id"] + "_1"
    hp_max = template.get("combat", {}).get("hit_points", {}).get("average", 0) \
        or actor_spec.get("hp", 0)
    # Per-instance hp_current override — lets a fixture spawn a creature
    # at less-than-full HP (useful for "wounded ally" defensive-eHP tests).
    # Clamped to [0, hp_max]; defaults to hp_max if absent.
    hp_current = actor_spec.get("hp_current")
    if hp_current is None:
        hp_current = hp_max
    hp_current = max(0, min(int(hp_current), hp_max))
    abilities = template.get("abilities", {}) or actor_spec.get("abilities", {})
    ac = template.get("combat", {}).get("armor_class", actor_spec.get("ac", 10))
    speed = template.get("combat", {}).get("speed", {"walk": 30})
    # Optional starting position [x, y] in 5-ft squares; default (0, 0).
    # Fixtures use this to lay out ranged-vs-melee starting distances.
    position_raw = actor_spec.get("position") or [0, 0]
    position = (int(position_raw[0]), int(position_raw[1]))
    # Optional spell_slots {level: count} dict; default empty (no
    # spellcaster). Accepts integer-keyed dict from YAML. PR #73:
    # falls back to template's `spell_slots` (auto-derived from the
    # class table by pc_schema for half-/full-casters). Explicit
    # actor_spec.spell_slots wins on conflict so fixtures can still
    # override for "wounded Paladin with no slots" scenarios.
    spell_slots_raw = (actor_spec.get("spell_slots")
                          or template.get("spell_slots")
                          or {})
    spell_slots = {int(k): int(v) for k, v in spell_slots_raw.items()}
    # Maximum slots per level — for Arcane Recovery / future long-rest
    # restoration. Defaults to a copy of spell_slots (assumes the actor
    # spec declares the post-rest / full-loadout amount). Authors can
    # override via `spell_slots_max:` if a fixture wants a different
    # post-restoration ceiling than the starting slots.
    spell_slots_max_raw = actor_spec.get("spell_slots_max")
    if spell_slots_max_raw is None:
        spell_slots_max = dict(spell_slots)
    else:
        spell_slots_max = {int(k): int(v) for k, v in spell_slots_max_raw.items()}
    # Optional per-actor resources dict — feature uses, charges, etc.
    # (e.g., `action_surge_uses_remaining: 1` for a L2 Fighter). Default
    # empty. Distinct from spell_slots since resource decrementation
    # and refresh cadence (short / long rest) is feature-specific.
    #
    # Merge order: PC-schema derived resources first, then the explicit
    # `resources:` block from actor_spec on top (explicit wins on
    # conflict). For non-PC actors, derived_pc_resources is {} so this
    # is just the explicit block.
    resources = dict(derived_pc_resources)
    resources.update(dict(actor_spec.get("resources") or {}))

    # PR #48 + PR #76: optional per-actor cover state ('none' |
    # 'half' | 'three_quarters' | 'total'). Defaults to 'none'.
    # Fixture authors set this to model a creature behind a wall,
    # parapet, etc. 'total' is the auto-miss case — single-target
    # attacks against this actor are short-circuited and the
    # candidate generator filters them from single-target lists.
    cover = str(actor_spec.get("cover", "none"))

    # PR #50: darkvision range in feet. Precedence:
    #   1. Explicit `darkvision_range_ft:` on the actor_spec (fixture
    #      override — for PCs the racial darkvision lives here until
    #      race modeling lands)
    #   2. Template's `senses.special.darkvision` (numeric feet)
    #   3. 0 (no darkvision)
    # PR #52: truesight_range_ft + blindsight_range_ft follow the same
    # precedence pattern (override → template.senses.special.<name> → 0).
    def _load_sense(name: str) -> int:
        raw = actor_spec.get(f"{name}_range_ft")
        if raw is None:
            tpl_senses = (template.get("senses") or {})
            tpl_special = (tpl_senses.get("special") or {})
            raw = tpl_special.get(name, 0)
        return int(raw or 0)

    darkvision_range_ft = _load_sense("darkvision")
    truesight_range_ft = _load_sense("truesight")
    blindsight_range_ft = _load_sense("blindsight")

    # PR #51: passive Perception. Precedence:
    #   1. Explicit `passive_perception:` on actor_spec (fixture override)
    #   2. Template's `senses.passive_perception` — monsters declare this
    #      directly; PC templates have it baked by pc_schema
    #      (10 + WIS_mod + PB if perception-proficient)
    #   3. Fallback 10 (raw human with neutral WIS, no proficiency)
    passive_perception = actor_spec.get("passive_perception")
    if passive_perception is None:
        tpl_senses = (template.get("senses") or {})
        passive_perception = tpl_senses.get("passive_perception", 10)
    passive_perception = int(passive_perception)

    # PR #54: weapon mastery properties this actor knows. Precedence:
    #   1. Explicit `weapon_masteries:` on actor_spec (fixture override)
    #   2. Template `weapon_masteries` (PC schema bakes it; monster
    #      templates may declare directly)
    #   3. [] (no masteries)
    weapon_masteries = actor_spec.get("weapon_masteries")
    if weapon_masteries is None:
        weapon_masteries = template.get("weapon_masteries") or []
    weapon_masteries = list(weapon_masteries)

    # PR #65: creature size. Precedence:
    #   1. Explicit `size:` on actor_spec (fixture override)
    #   2. Template's top-level `size:` (monster SRD shape)
    #   3. 'medium' (default — Actor field default)
    # Normalized + validated via engine.core.sizes.normalize_size
    # (rejects typos with a clear error).
    raw_size = actor_spec.get("size")
    if raw_size is None:
        raw_size = template.get("size")
    from engine.core.sizes import normalize_size
    size = normalize_size(raw_size)

    # PR #75: racial traits from the template (stamped by
    # pc_schema when pc_spec.race is set). Empty list for non-PC
    # actors or PCs without a declared race. Fixture override via
    # actor_spec.racial_traits supported for test/fixture flexibility.
    racial_traits_raw = (actor_spec.get("racial_traits")
                            if actor_spec.get("racial_traits") is not None
                            else (template.get("racial_traits") or []))
    racial_traits = list(racial_traits_raw)

    return Actor(
        id=instance_id,
        name=actor_spec.get("name", template.get("name", instance_id)),
        template=template,
        side=actor_spec.get("side", "enemy"),
        hp_current=hp_current,
        hp_max=hp_max,
        ac=ac,
        speed=speed,
        position=position,
        abilities=abilities,
        spell_slots=spell_slots,
        spell_slots_max=spell_slots_max,
        resources=resources,
        cover=cover,
        darkvision_range_ft=darkvision_range_ft,
        truesight_range_ft=truesight_range_ft,
        blindsight_range_ft=blindsight_range_ft,
        passive_perception=passive_perception,
        weapon_masteries=weapon_masteries,
        size=size,
        racial_traits=racial_traits,
    )


if __name__ == "__main__":
    sys.exit(main())
