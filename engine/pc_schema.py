"""PC schema — compact-spec → full-template derivation.

Per `docs/engine-capabilities.md` §7 roadmap item #1: replaces the
inline-monster-template hack that PC fixtures have been using since
the skeleton landed.

A fixture can now declare a PC via:

    pc:
      class: c_fighter
      level: 3
      ability_scores: { str: 16, dex: 12, con: 14, int: 10, wis: 12, cha: 10 }
      armor:
        base_ac: 16
        max_dex_bonus: 2
      weapons:
        - id: a_longsword
          name: Longsword
          attack_ability: str
          damage_dice: 1d8
          damage_type: slashing
          reach_ft: 5

…and `build_pc_template` derives a full template dict (HP, AC,
proficiency bonus, save bonuses, attack actions per weapon) ready to
feed into `engine.cli._build_actor`. The compact spec is the user-
facing surface; the derived template is what the engine actually
consumes.

**v1 scope:**
  - Reads from existing `schema/content/classes/c_*.yaml` for:
      - hit_die (HP calculation)
      - save_proficiencies (which saves get PB)
      - level_table.proficiency_bonus (PB lookup by level)
      - level_table.features (auto-wire class-feature resources —
        see `derive_pc_resources`)
      - level_table.class_resources (Second Wind use counts etc.)
  - Derives HP, AC, save bonuses
  - Generates per-weapon attack actions (melee + ranged via reach_ft /
    range_ft)
  - **Class-feature auto-wiring** (`derive_pc_resources`): scans the
    level_table up to the PC's level and returns the per-actor
    resources that engine systems need:
      - `action_surge_uses_remaining` (Fighter, L2+): 1 at L2-16,
        2 at L17+ — drives the runner's Action Surge activation
      - `second_wind_uses_remaining` (Fighter, L1+): from
        class_resources.second_wind_uses at the PC's level
    The compact `pc:` spec used to require fixture authors to hand-
    set these in a separate `resources:` block; auto-derivation
    closes that loop. Explicit `resources:` on the actor_spec still
    wins on conflict (lets tests force edge cases).
  - Backward compatible — existing `template:` and `template_ref:`
    fixture shapes still work; `pc:` is a third opt-in shape.

**Deferred:**
  - Second Wind ACTION generation — the resource counter is auto-
    derived; the bonus-action heal that consumes it isn't yet wired
    (needs a feature_uses consumption gate similar to spell-slot
    consumption; separate PR)
  - Fighting Style passive modifiers (damage / AC boosts) — needs a
    new always-on modifier path
  - Weapon Mastery — Mastery property tags + per-weapon effects
  - Extra Attack (L5/L11/L20) — would require multiattack action
    generation (the count varies by level)
  - Multiclass — additive PB / class_resources / shared HP table
  - Spellcasting → action generation (only Wizard has the block)
  - Subclasses
  - Starting equipment LIBRARY (longsword/chain_mail lookups) — for v1
    weapons are declared inline; armor is base_ac + max_dex_bonus
  - Skill / tool proficiencies (no skill check primitive)
  - ASI / feats
  - Race / species, background
"""
from __future__ import annotations

from typing import Any

from engine.core.state import ability_modifier


# ============================================================================
# Public API
# ============================================================================

def build_pc_template(pc_spec: dict, content_registry: Any) -> dict:
    """Build a full template dict from a compact PC spec.

    Args:
      pc_spec: the value of the `pc:` field on an actor_spec
      content_registry: the engine.loader ContentRegistry (used to look
        up class definitions)

    Returns:
      A full template dict shaped like a monster template:
        {id, name, abilities, cr, combat, actions, ...}

    Raises:
      KeyError if the referenced class isn't in the registry.
      ValueError if required fields are missing or out of range.
    """
    class_id = pc_spec.get("class")
    if not class_id:
        raise ValueError("pc spec missing required field: class")
    level = int(pc_spec.get("level", 1))
    if level < 1 or level > 20:
        raise ValueError(f"pc level must be in [1, 20], got {level}")

    abilities_raw = pc_spec.get("ability_scores") or {}
    ability_scores = _resolve_ability_scores(abilities_raw)

    class_def = content_registry.get("class", class_id)

    proficiency_bonus = _lookup_pb(class_def, level)
    save_profs = set(class_def.get("core_traits", {})
                       .get("save_proficiencies", []))

    # Derive HP
    hit_die = class_def.get("core_traits", {}).get("hit_die", "d8")
    con_mod = ability_modifier(ability_scores["con"]["score"])
    hp = _compute_hp(hit_die, level, con_mod)

    # Derive AC
    armor_spec = pc_spec.get("armor") or {}
    ac = _compute_ac(armor_spec, ability_scores)

    # Build abilities dict with save bonuses
    abilities = _build_abilities_with_saves(
        ability_scores, save_profs, proficiency_bonus
    )

    # Build action list from weapons
    actions = [_build_weapon_action(w, ability_scores, proficiency_bonus)
                for w in (pc_spec.get("weapons") or [])]

    # Composite template
    template = {
        "id": pc_spec.get("id") or f"pc_{class_id}_L{level}",
        "name": pc_spec.get("name") or f"{class_def.get('name', class_id)} L{level}",
        "source": "user_authored",
        "abilities": abilities,
        "cr": {
            "value": 0.0,            # PCs don't have CR
            "xp": 0,
            "proficiency_bonus": proficiency_bonus,
        },
        "combat": {
            "armor_class": ac,
            "hit_points": {
                "average": hp,
                "dice": f"{level}{hit_die}",
                "con_contribution": con_mod * level,
            },
            "speed": pc_spec.get("speed") or {"walk": 30},
            "initiative": {
                "modifier": ability_modifier(ability_scores["dex"]["score"]),
            },
        },
        "actions": actions,
        # Tag for telemetry / debugging
        "derived_from_pc_schema": {
            "class": class_id,
            "level": level,
        },
    }

    # Pass behavior_profile through verbatim if specified
    if "behavior_profile" in pc_spec:
        template["behavior_profile"] = pc_spec["behavior_profile"]

    return template


def derive_pc_resources(pc_spec: dict, content_registry: Any) -> dict:
    """Return per-actor resources derived from the PC's class + level.

    Scans the class's `level_table` for all rows up to (and including)
    the PC's current level, collecting:
      - feature IDs gained (`features` list per row)
      - class_resources counters (highest applicable value)

    Returns a dict keyed by resource name (e.g.,
    `action_surge_uses_remaining`, `second_wind_uses_remaining`).
    Resources whose driving feature isn't present at the PC's level
    are omitted entirely — the runner / candidate generator already
    treats missing keys as "feature not available."

    Caller (engine.cli._build_actor) merges this with any explicit
    `resources:` block on the actor_spec, with explicit winning on
    conflict (lets fixture authors force edge cases — e.g., zero
    charges to test "Action Surge unavailable" behavior on a L2
    Fighter).

    Returns {} if `class` is missing or the class isn't in the
    registry (e.g., custom inline-template fixtures that happen to
    declare a PC without a registry class).
    """
    class_id = pc_spec.get("class")
    if not class_id:
        return {}
    level = int(pc_spec.get("level", 1))
    if level < 1:
        return {}
    try:
        class_def = content_registry.get("class", class_id)
    except (KeyError, AttributeError):
        return {}
    if class_def is None:
        return {}

    # Walk the level_table, accumulating features + class_resources
    # up to the PC's level. `class_resources` at higher levels
    # OVERWRITES lower-level values — that matches the RAW pattern
    # (second_wind_uses goes 2 → 3 → 4 by level).
    features_known: set[str] = set()
    class_resources_at_level: dict = {}
    for row in (class_def.get("level_table") or []):
        if int(row.get("level", 0)) > level:
            continue
        for fid in (row.get("features") or []):
            features_known.add(fid)
        for k, v in (row.get("class_resources") or {}).items():
            class_resources_at_level[k] = v

    resources: dict = {}

    # ---- Action Surge ----
    # `f_action_surge_two_uses` (L17) supersedes `f_action_surge_one_use`
    # (L2). Per RAW the L17 upgrade gives 2 charges per short rest but
    # still only one Action Surge per turn (enforced in the runner).
    if "f_action_surge_two_uses" in features_known:
        resources["action_surge_uses_remaining"] = 2
    elif "f_action_surge_one_use" in features_known:
        resources["action_surge_uses_remaining"] = 1

    # ---- Second Wind ----
    # The counter is auto-derived from class_resources.second_wind_uses
    # at the PC's level. The action that CONSUMES this counter (bonus-
    # action 1d10+level heal on self) is NOT generated by v1 — the
    # feature_uses-gated action infrastructure lands in a follow-on PR.
    # We still surface the resource so it's there when that PR wires
    # the action.
    if "f_second_wind" in features_known:
        uses = int(class_resources_at_level.get("second_wind_uses", 0))
        if uses > 0:
            resources["second_wind_uses_remaining"] = uses

    return resources


# ============================================================================
# Internal helpers
# ============================================================================

_ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


def _resolve_ability_scores(raw: dict) -> dict:
    """Normalize ability_scores into the {key: {score: N, save: M}} shape
    expected by Actor.abilities. Accepts either:
      - {str: 16, dex: 12, ...}  (bare ints)
      - {str: {score: 16}, ...}  (verbose)
    """
    out: dict = {}
    for key in _ABILITY_KEYS:
        v = raw.get(key, 10)
        if isinstance(v, dict):
            score = int(v.get("score", 10))
        else:
            score = int(v)
        out[key] = {"score": score, "save": 0}  # save populated later
    return out


def _lookup_pb(class_def: dict, level: int) -> int:
    """Return proficiency_bonus at the given level from class.level_table."""
    for row in class_def.get("level_table") or []:
        if int(row.get("level", 0)) == level:
            return int(row.get("proficiency_bonus", 2))
    # Fallback to RAW 5e progression if level_table missing the row
    if level < 5:
        return 2
    if level < 9:
        return 3
    if level < 13:
        return 4
    if level < 17:
        return 5
    return 6


def _compute_hp(hit_die: str, level: int, con_mod: int) -> int:
    """HP per 5e RAW: L1 = max(die) + CON; each subsequent level = avg(die) + CON.

    hit_die is e.g. 'd10'. avg(d10) = 5.5; rounded up by 5e convention
    when taking average per level (5.5 → 6 for d10; 4.5 → 5 for d8;
    3.5 → 4 for d6; 5 → 5 for d10 in some shorthand; we use ceil).
    """
    die_size = int(hit_die.lstrip("d"))
    avg_per_level = (die_size // 2) + 1   # 5e convention: d10 = 6, d8 = 5, etc.
    hp = die_size + con_mod                # L1 max
    if level > 1:
        hp += (avg_per_level + con_mod) * (level - 1)
    return max(1, hp)


def _compute_ac(armor: dict, ability_scores: dict) -> int:
    """AC = base_ac + min(DEX_mod, max_dex_bonus). If no armor block,
    default to 10 + DEX (unarmored)."""
    dex_mod = ability_modifier(ability_scores["dex"]["score"])
    if not armor:
        return 10 + dex_mod
    base_ac = int(armor.get("base_ac", 10))
    max_dex = armor.get("max_dex_bonus")
    if max_dex is None:
        return base_ac + dex_mod
    return base_ac + min(dex_mod, int(max_dex))


def _build_abilities_with_saves(ability_scores: dict, save_profs: set,
                                  proficiency_bonus: int) -> dict:
    """Populate the .save field on each ability based on class proficiency."""
    # Map between short keys (str/dex/...) and the long names used in
    # class.save_proficiencies ("strength"/"dexterity"/...)
    short_to_long = {
        "str": "strength", "dex": "dexterity", "con": "constitution",
        "int": "intelligence", "wis": "wisdom", "cha": "charisma",
    }
    out: dict = {}
    for short, entry in ability_scores.items():
        score = entry["score"]
        mod = ability_modifier(score)
        is_prof = short_to_long[short] in save_profs
        save = mod + (proficiency_bonus if is_prof else 0)
        out[short] = {"score": score, "save": save}
    return out


def _build_weapon_action(weapon: dict, ability_scores: dict,
                          proficiency_bonus: int) -> dict:
    """Convert a compact weapon spec into a weapon_attack action dict.

    Weapon spec fields:
      id, name (required)
      attack_ability: str | dex   (which ability mod adds to attack + damage)
      damage_dice: e.g., "1d8"
      damage_modifier: optional int (added to ability mod for damage; rare)
      damage_type: slashing | piercing | bludgeoning | etc.
      reach_ft: melee reach (default 5) — mutually exclusive w/ range_ft
      range_ft: ranged weapon range (optional)
    """
    attack_ability = weapon.get("attack_ability", "str")
    ability_mod = ability_modifier(
        ability_scores[attack_ability]["score"]
    )
    attack_bonus = ability_mod + proficiency_bonus
    damage_mod = ability_mod + int(weapon.get("damage_modifier", 0))

    is_ranged = "range_ft" in weapon
    attack_params: dict = {
        "kind": "ranged" if is_ranged else "melee",
        "bonus": attack_bonus,
    }
    if is_ranged:
        attack_params["range_ft"] = int(weapon["range_ft"])
    else:
        attack_params["reach_ft"] = int(weapon.get("reach_ft", 5))

    return {
        "id": weapon.get("id") or f"a_{weapon.get('name', 'weapon').lower().replace(' ', '_')}",
        "name": weapon.get("name", "Weapon"),
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll", "params": attack_params},
            {"primitive": "damage",
              "params": {
                  "dice": weapon.get("damage_dice", "1d4"),
                  "modifier": damage_mod,
                  "type": weapon.get("damage_type", "bludgeoning"),
              },
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }
