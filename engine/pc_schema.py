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

    # Fighting Style — validated + applied at template build time.
    # PR #38: passive bonuses (AC / attack / damage) are baked into the
    # generated weapon actions / AC computation rather than registered
    # as runtime modifiers. See _validate_fighting_style for the
    # accepted set + _compute_ac / _build_weapon_action for application.
    fighting_style = _validate_fighting_style(pc_spec.get("fighting_style"))

    # Skill proficiencies (PR #51) — list of skill names the PC is
    # proficient in. Validated against the known 5e 2024 skill list.
    # Baked onto the template as `skill_proficiencies` so the runtime
    # skill_modifier helper can read it (mirrors the SRD-monster
    # `skills:` dict shape, just stored as a list of proficiencies
    # since PCs compute the bonus on demand from ability + PB).
    skill_proficiencies = _validate_skill_proficiencies(
        pc_spec.get("skill_proficiencies"))

    # Derive HP
    hit_die = class_def.get("core_traits", {}).get("hit_die", "d8")
    con_mod = ability_modifier(ability_scores["con"]["score"])
    hp = _compute_hp(hit_die, level, con_mod)

    # Derive AC (Defense Fighting Style adds +1 when armor is present)
    armor_spec = pc_spec.get("armor") or {}
    ac = _compute_ac(armor_spec, ability_scores,
                       fighting_style=fighting_style)

    # Build abilities dict with save bonuses
    abilities = _build_abilities_with_saves(
        ability_scores, save_profs, proficiency_bonus
    )

    # Build action list from weapons (Dueling / Archery may add to
    # damage / attack bonus on the qualifying weapon actions).
    weapon_actions = [_build_weapon_action(w, ability_scores,
                                              proficiency_bonus,
                                              fighting_style=fighting_style)
                       for w in (pc_spec.get("weapons") or [])]
    actions = list(weapon_actions)
    # Auto-append class-feature actions (Second Wind etc.) for features
    # the PC has at this level. Resource counters were derived
    # separately by `derive_pc_resources`; this generates the actual
    # action declarations that consume those counters at runtime.
    # `weapon_actions` is passed so Extra Attack can reference the
    # weapon ids in its sub_actions list (PR #39).
    features_known = _features_known_at_level(class_def, level)
    actions += _build_feature_actions(features_known, level, class_id,
                                         weapon_actions=weapon_actions)

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
            "fighting_style": fighting_style,    # None if not chosen
            "skill_proficiencies": list(skill_proficiencies),
        },
        # Top-level skill_proficiencies for the runtime skill_modifier
        # helper to read (engine/core/skills.py). Mirrors the monster-
        # template `skills:` dict shape, except PCs store the list of
        # proficient skills (bonus computed on demand from ability + PB).
        "skill_proficiencies": list(skill_proficiencies),
        # Passive Perception (PR #51): 10 + WIS_mod + PB if proficient.
        # Mirrors the monster-template `senses.passive_perception` shape.
        # Loaded by cli._build_actor onto Actor.passive_perception.
        "senses": {
            "passive_perception": _compute_passive_perception(
                ability_scores, skill_proficiencies, proficiency_bonus),
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

    features_known = _features_known_at_level(class_def, level)
    class_resources_at_level = _class_resources_at_level(class_def, level)

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
    # at the PC's level. PR #33 added the auto-generated bonus-action
    # heal that CONSUMES this counter; we still surface the resource
    # here.
    if "f_second_wind" in features_known:
        uses = int(class_resources_at_level.get("second_wind_uses", 0))
        if uses > 0:
            resources["second_wind_uses_remaining"] = uses

    # ---- Arcane Recovery (Wizard L1+) ----
    # 1/long rest. Consumed by `engine.core.rest.apply_short_rest` —
    # not exercised in-combat (RAW: end-of-short-rest only). We surface
    # the counter so the rest helper sees it; multi-encounter sim work
    # will invoke apply_short_rest between encounters.
    if "f_arcane_recovery" in features_known:
        resources["arcane_recovery_uses_remaining"] = 1

    return resources


# ============================================================================
# Internal helpers
# ============================================================================

_ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


# Fighting Styles the engine knows how to apply at template build time.
# Defense + Dueling are SRD CC v5.2.1. Archery / Protection are
# user_authored (non-SRD; common picks). GWF / Two-Weapon Fighting /
# Blind Fighting still deferred — each needs additional infrastructure
# (damage re-roll, off-hand weapons, vision).
#
# Note: Protection is a REACTION (declared in f_fs_protection.yaml's
# action_template); pc_schema doesn't bake in a passive modifier for
# it. The Fighting Style choice records that the actor has Protection,
# and the fixture (or future class-features auto-wiring) must attach
# the reaction action to the actor's template.actions list.
_KNOWN_FIGHTING_STYLES = frozenset({
    "defense",      # +1 AC when wearing armor (passive)
    "dueling",      # +2 damage on one-handed melee (passive)
    "archery",      # +2 attack on ranged weapons (passive)
    "protection",   # reaction: impose disadv on adjacent ally attacks
                    # (PR #45; action wired via f_fs_protection.yaml's
                    # action_template, attached by fixture for v1)
    "great_weapon_fighting",   # PR #49: damage_die_floor=3 on 2H
                                # melee weapons (RAW 2024: treat any
                                # 1 or 2 on a damage die as a 3).
                                # Versatile weapons wielded two-handed
                                # deferred until weapon-grip state is
                                # modeled.
})


def _validate_fighting_style(value):
    """Return the validated style id (lowercase string) or None.
    Raises ValueError if the value is set but not in the accepted set."""
    if value is None or value == "":
        return None
    s = str(value).lower()
    if s not in _KNOWN_FIGHTING_STYLES:
        raise ValueError(
            f"Unknown fighting_style {value!r}. Accepted: "
            f"{sorted(_KNOWN_FIGHTING_STYLES)}. (GWF / Protection / "
            "Two-Weapon Fighting / Blind Fighting are deferred — see "
            "f_fighting_style.yaml for status.)"
        )
    return s


def _validate_skill_proficiencies(value) -> list[str]:
    """Return a normalized list of validated skill names, or [] when
    None / empty. Raises ValueError on unknown skill names — keeps
    typos from silently dropping into an empty proficiency list.

    PR #51: PC schemas declare `skill_proficiencies: [stealth, ...]`.
    The list is baked onto the template (top-level + derived_from
    block) so engine/core/skills.py can read it at runtime.
    """
    if value is None or value == "":
        return []
    from engine.core.skills import validate_skill_name
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            f"skill_proficiencies must be a list, got {type(value).__name__}"
        )
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        n = validate_skill_name(str(raw))
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out


def _compute_passive_perception(ability_scores: dict,
                                    skill_proficiencies: list[str],
                                    proficiency_bonus: int) -> int:
    """10 + WIS_mod + (PB if proficient in Perception).

    PR #51: PCs derive passive Perception so vision checks against
    hidden creatures (PR #48's Hide) have a number to compare
    against. Monster templates declare this directly under
    `senses.passive_perception`; we mirror that shape for PCs.

    Expertise (double PB) is deferred until skill expertise lands.
    Magic-item bonuses (e.g., Cloak of Elvenkind) deferred.
    """
    wis_score = int((ability_scores.get("wis") or {}).get("score", 10))
    mod = ability_modifier(wis_score)
    base = 10 + mod
    if "perception" in {s.lower() for s in skill_proficiencies}:
        base += int(proficiency_bonus)
    return base


def _features_known_at_level(class_def: dict, level: int) -> set[str]:
    """Set of feature IDs gained at or before `level` from class_def's
    level_table. Shared by `derive_pc_resources` (drives resource init)
    and `build_pc_template` (drives feature-action generation)."""
    features: set[str] = set()
    for row in (class_def.get("level_table") or []):
        if int(row.get("level", 0)) > level:
            continue
        for fid in (row.get("features") or []):
            features.add(fid)
    return features


def _class_resources_at_level(class_def: dict, level: int) -> dict:
    """Class resources dict for the highest-applicable level row. Later
    levels OVERWRITE earlier values — matches RAW progression
    (second_wind_uses goes 2 → 3 → 4 across L1/L4/L10)."""
    out: dict = {}
    for row in (class_def.get("level_table") or []):
        if int(row.get("level", 0)) > level:
            continue
        for k, v in (row.get("class_resources") or {}).items():
            out[k] = v
    return out


def _build_feature_actions(features_known: set[str], level: int,
                             class_id: str,
                             weapon_actions: list[dict] | None = None
                             ) -> list[dict]:
    """Generate action dicts for the feature IDs the PC has at this
    level. v1 + PR #39: Second Wind + Extra Attack (count scales by
    level). Future features that need action representation get added
    here.

    Each generated action carries a `feature_use:` field naming the
    actor.resources key it consumes — the pipeline's feature-use gate
    filters out actions whose resource is depleted (see
    engine/core/feature_uses.py).

    `weapon_actions` is the list of weapon attack actions already
    built for the PC's weapons — Extra Attack needs them to reference
    the weapon ids in its sub_actions list. Pass `None` for callers
    that don't need feature actions tied to weapons (e.g., the
    second_wind-only generation path).
    """
    actions: list[dict] = []
    if "f_second_wind" in features_known and class_id == "c_fighter":
        actions.append(_build_second_wind_action(level))
    # Extra Attack: count scales with feature presence (RAW Fighter
    # progression at L5 / L11 / L20). Only one of the three feature
    # ids is meaningful at a time — higher-level features supersede
    # lower per the c_fighter level_table (the lower-level feature
    # remains in features_known by accumulation, but the higher-level
    # count wins).
    if class_id == "c_fighter":
        count = _extra_attack_count(features_known)
        if count > 1 and weapon_actions:
            actions.append(_build_extra_attack_action(count, weapon_actions))
    return actions


def _extra_attack_count(features_known: set[str]) -> int:
    """Total attacks per Attack action for the Fighter, based on which
    Extra Attack features have been gained. Returns 1 if none."""
    if "f_three_extra_attacks" in features_known:
        return 4        # L20
    if "f_two_extra_attacks" in features_known:
        return 3        # L11
    if "f_extra_attack" in features_known:
        return 2        # L5
    return 1


def _build_extra_attack_action(count: int,
                                  weapon_actions: list[dict]) -> dict:
    """Build a multiattack action that fires `count` swings using the
    fighter's first weapon. RAW: you use the SAME Attack action with
    each attack, so we reference one weapon id repeated rather than
    cycling through all weapons (cycling would be unusual and the
    multiattack execution does `sub_action_ids[i % len(...)]` anyway,
    which makes both shapes work).

    Drawn from the first weapon in the actions list for stability —
    fixtures usually declare one weapon. PCs with multiple weapons get
    multiattack on weapon #1; runtime weapon swap is out of scope.
    """
    primary = weapon_actions[0]
    primary_id = primary["id"]
    return {
        "id": "a_extra_attack",
        "name": f"Extra Attack ({count}× {primary.get('name', 'weapon')})",
        "type": "multiattack",
        "count": int(count),
        "sub_actions": [primary_id] * int(count),
    }


def _build_second_wind_action(fighter_level: int) -> dict:
    """RAW (2024 PHB): Bonus Action, regain 1d10 + fighter_level HP.
    Consumes one `second_wind_uses_remaining` charge.

    `fighter_level` is inlined as a flat damage modifier (computed at
    template-build time) rather than referenced via a `modifier_source`
    expression, because the value is fixed for the life of this PC
    instance — no need for runtime resolution.
    """
    return {
        "id": "a_second_wind",
        "name": "Second Wind",
        "type": "heal",
        "slot": "bonus_action",
        "feature_use": "second_wind_uses_remaining",
        # Marked signature so the bonus-slot gate (`should_use_bonus_
        # action`) rolls against the high signature_bonus threshold
        # (default 0.95) rather than the lower tactical_bonus default.
        # Matches `f_second_wind.yaml`'s declared `is_signature: true`.
        "is_signature": True,
        "pipeline": [
            {"primitive": "heal",
              "params": {
                  "target": "self",
                  "dice": "1d10",
                  "fixed": int(fighter_level),
              }},
        ],
    }


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


def _compute_ac(armor: dict, ability_scores: dict,
                fighting_style: str | None = None) -> int:
    """AC = base_ac + min(DEX_mod, max_dex_bonus). If no armor block,
    default to 10 + DEX (unarmored).

    Defense Fighting Style adds +1 when armor is present (v1 proxy for
    "wearing armor" per RAW). A Defense-style fighter without an
    armor block selects the style legally but the +1 doesn't apply.
    """
    dex_mod = ability_modifier(ability_scores["dex"]["score"])
    if not armor:
        # Defense doesn't apply without armor — return unarmored AC
        return 10 + dex_mod
    base_ac = int(armor.get("base_ac", 10))
    max_dex = armor.get("max_dex_bonus")
    if max_dex is None:
        ac = base_ac + dex_mod
    else:
        ac = base_ac + min(dex_mod, int(max_dex))
    if fighting_style == "defense":
        ac += 1
    return ac


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
                          proficiency_bonus: int,
                          fighting_style: str | None = None) -> dict:
    """Convert a compact weapon spec into a weapon_attack action dict.

    Weapon spec fields:
      id, name (required)
      attack_ability: str | dex   (which ability mod adds to attack + damage)
      damage_dice: e.g., "1d8"
      damage_modifier: optional int (added to ability mod for damage; rare)
      damage_type: slashing | piercing | bludgeoning | etc.
      reach_ft: melee reach (default 5) — mutually exclusive w/ range_ft
      range_ft: ranged weapon range (optional)
      two_handed: bool — if True, weapon is two-handed (PR #38, used by
        Dueling to exclude two-handed weapons)

    Fighting Style application:
      - Dueling: +2 damage on one-handed melee weapons
      - Archery: +2 attack on ranged weapons
      - Great Weapon Fighting (PR #49): damage_die_floor=3 on two-handed
        melee weapons. RAW 2024: any 1 or 2 rolled on a weapon's damage
        die is treated as a 3. Implemented via the `damage_die_floor`
        param on the damage primitive (clamps each individual die roll).
        Versatile weapons wielded two-handed are deferred until weapon-
        grip state is modeled — for now `two_handed: true` is the gate.
    """
    attack_ability = weapon.get("attack_ability", "str")
    ability_mod = ability_modifier(
        ability_scores[attack_ability]["score"]
    )
    attack_bonus = ability_mod + proficiency_bonus
    damage_mod = ability_mod + int(weapon.get("damage_modifier", 0))

    is_ranged = "range_ft" in weapon
    is_two_handed = bool(weapon.get("two_handed", False))

    # PR #38: Fighting Style passive bonuses baked in at build time
    if fighting_style == "archery" and is_ranged:
        attack_bonus += 2
    if (fighting_style == "dueling"
            and not is_ranged and not is_two_handed):
        damage_mod += 2

    # PR #49: Great Weapon Fighting — damage die floor on 2H melee.
    damage_die_floor = 0
    if (fighting_style == "great_weapon_fighting"
            and not is_ranged and is_two_handed):
        damage_die_floor = 3

    attack_params: dict = {
        "kind": "ranged" if is_ranged else "melee",
        "bonus": attack_bonus,
    }
    if is_ranged:
        attack_params["range_ft"] = int(weapon["range_ft"])
    else:
        attack_params["reach_ft"] = int(weapon.get("reach_ft", 5))

    damage_params: dict = {
        "dice": weapon.get("damage_dice", "1d4"),
        "modifier": damage_mod,
        "type": weapon.get("damage_type", "bludgeoning"),
    }
    if damage_die_floor > 0:
        damage_params["damage_die_floor"] = damage_die_floor

    return {
        "id": weapon.get("id") or f"a_{weapon.get('name', 'weapon').lower().replace(' ', '_')}",
        "name": weapon.get("name", "Weapon"),
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll", "params": attack_params},
            {"primitive": "damage",
              "params": damage_params,
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }
