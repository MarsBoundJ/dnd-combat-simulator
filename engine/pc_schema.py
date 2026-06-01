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

    # PR #75: race lookup. Optional — pc_spec without a `race` field
    # produces a "no race" PC (no racial traits, default size/speed).
    # When `race: r_<species>` is set, we look up the race YAML and
    # use its fields downstream to stamp size, speed, darkvision,
    # damage resistances, racial trait flags, and any extra skill
    # proficiencies (Human Skillful).
    race_def = None
    race_id = pc_spec.get("race")
    if race_id:
        try:
            race_def = content_registry.get("race", race_id)
        except (KeyError, AttributeError):
            raise ValueError(
                f"pc_spec.race={race_id!r} not found in content "
                f"registry. Known SRD species: r_dwarf, r_elf, "
                f"r_halfling, r_human."
            )

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

    # PR #75: Human Skillful trait — one extra skill proficiency
    # picked via pc_spec.extra_skill (e.g., `extra_skill: persuasion`).
    # The race YAML's `extra_skill_proficiency_slots: 1` flags that
    # this PC is allowed an extra; the slot value just bounds how
    # many extras can be added (v1 only handles 1, the Human case).
    if race_def and int(race_def.get("extra_skill_proficiency_slots", 0)) > 0:
        extra_skill = pc_spec.get("extra_skill")
        if extra_skill:
            from engine.core.skills import validate_skill_name
            normalized = validate_skill_name(str(extra_skill))
            if normalized not in skill_proficiencies:
                skill_proficiencies = list(skill_proficiencies) + [normalized]

    # Skill expertise (PR #62) — list of skill names the PC has
    # Expertise in (2× PB instead of 1× PB on those skill checks).
    # RAW: Expertise requires Proficiency in the same skill — v1
    # enforces this via `_validate_skill_expertise(expertise,
    # proficiencies)` which raises if any expertise entry is not
    # also in skill_proficiencies.
    skill_expertise = _validate_skill_expertise(
        pc_spec.get("skill_expertise"), skill_proficiencies)

    # Skill magic-item bonuses (PR #62) — flat int bonus per skill,
    # e.g. {stealth: 5, perception: 2} for a PC with Cloak of
    # Elvenkind + Eyes of the Eagle. Validated against the known
    # skill list. Stacks on top of any proficiency / expertise PB.
    skill_bonuses = _validate_skill_bonuses(pc_spec.get("skill_bonuses"))

    # Weapon masteries (PR #54) — list of mastery property ids this
    # PC "knows" via the Weapon Mastery class feature. Validated
    # against the known set in engine.core.weapon_masteries. Baked
    # onto the template top-level so cli._build_actor can read it
    # onto Actor.weapon_masteries.
    #
    # PR #64: enforce the class-level "masteries known" cap from
    # the level_table. _validate_weapon_masteries_cap reads
    # `class_resources.weapon_mastery_count` at the PC's level and
    # raises if `len(weapon_masteries)` exceeds it. Allows under-
    # budgeted PCs (RAW: you can know fewer than the max) but
    # rejects over-budgeted ones (no free masteries).
    from engine.core.weapon_masteries import validate_mastery_list
    weapon_masteries = validate_mastery_list(
        pc_spec.get("weapon_masteries"))
    _validate_weapon_masteries_cap(
        weapon_masteries, class_def, level, class_id)

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
    weapons_list = pc_spec.get("weapons") or []
    weapon_actions = [_build_weapon_action(w, ability_scores,
                                              proficiency_bonus,
                                              fighting_style=fighting_style)
                       for w in weapons_list]
    actions = list(weapon_actions)

    # PR #53: off-hand weapon → auto-generate a bonus-action attack.
    # RAW 2024: the primary weapon AND the off-hand must both be Light
    # melee. `_validate_off_hand_weapon` enforces this and surfaces a
    # clear error if either side fails the gate.
    off_hand_spec = pc_spec.get("off_hand_weapon")
    if off_hand_spec:
        _validate_off_hand_weapon(off_hand_spec, weapons_list)
        off_hand_action = _build_weapon_action(
            off_hand_spec, ability_scores, proficiency_bonus,
            fighting_style=fighting_style, off_hand=True)
        # PR #57: Nick mastery — if the actor knows Nick AND at least
        # one wielded Light melee weapon (off-hand OR a primary) has
        # mastery=nick, the off-hand attack happens as part of the
        # Attack action (slot='free') instead of as a Bonus Action.
        # The runner's free-phase fires slot=free actions
        # automatically after the main action.
        if _nick_active(off_hand_spec, weapons_list, weapon_masteries):
            off_hand_action["slot"] = "free"
            off_hand_action["nick_active"] = True
        actions.append(off_hand_action)
    # Auto-append class-feature actions (Second Wind etc.) for features
    # the PC has at this level. Resource counters were derived
    # separately by `derive_pc_resources`; this generates the actual
    # action declarations that consume those counters at runtime.
    # `weapon_actions` is passed so Extra Attack can reference the
    # weapon ids in its sub_actions list (PR #39).
    features_known = _features_known_at_level(class_def, level)
    # Subclass features. When the PC spec names a `subclass: sc_<id>`,
    # validate it (parent_class match + level gate) and merge its
    # features_by_level (up to the PC's level) into features_known, so
    # the SAME downstream paths — action generation, spell auto-attach,
    # resource derivation, runtime feature gates — pick them up with no
    # subclass-specific branching. A PC without a subclass is unchanged.
    subclass_def = _resolve_subclass(
        pc_spec, class_def, class_id, level, content_registry)
    if subclass_def:
        features_known = set(features_known) | _subclass_features_at_level(
            subclass_def, level)
    # PR #103: Eldritch Invocations — player-chosen Warlock features
    # (like fighting_style). Validated against the known-invocation
    # registry + prerequisites, then merged into features_known so
    # downstream builders (Eldritch Blast's Agonizing Blast damage
    # bump) + the features_known template stamp pick them up.
    invocations = _validate_invocations(
        pc_spec.get("invocations"), features_known, class_id, level)
    features_known = set(features_known) | set(invocations)
    actions += _build_feature_actions(features_known, level, class_id,
                                         weapon_actions=weapon_actions,
                                         ability_scores=ability_scores,
                                         proficiency_bonus=proficiency_bonus)
    # PR #82: auto-attach spell action_templates from features that
    # declare one. This covers Paladin Bless / Shield of Faith and
    # any future spell-shaped features whose YAML carries an
    # `action_template` block. Skipped when the feature's
    # action_template would clash with an action already generated
    # by the hardcoded builders above (e.g., a feature with the
    # same id).
    existing_ids = {a.get("id") for a in actions}
    for feature_id in features_known:
        try:
            feature = content_registry.get("feature", feature_id)
        except (KeyError, AttributeError):
            continue
        # Data-driven spell-action builders (pc_builder block) — new
        # attack/heal spells declare their builder in YAML and are built
        # here, no per-feature dispatch in _build_feature_actions needed.
        builder_action = _dispatch_pc_builder(
            feature, level, ability_scores, proficiency_bonus, class_id)
        if builder_action is not None:
            if builder_action.get("id") not in existing_ids:
                actions.append(builder_action)
                existing_ids.add(builder_action.get("id"))
            continue
        action_template = feature.get("action_template")
        if not action_template:
            continue
        if action_template.get("id") in existing_ids:
            continue
        actions.append(dict(action_template))
        existing_ids.add(action_template.get("id"))

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
            "speed": (pc_spec.get("speed")
                          or (race_def.get("speed") if race_def else None)
                          or {"walk": 30}),
            "initiative": {
                "modifier": ability_modifier(ability_scores["dex"]["score"]),
            },
        },
        "actions": actions,
        # PR #75: race-derived top-level fields. cli._build_actor reads
        # these onto the Actor (size, darkvision, racial_traits) so the
        # existing per-Actor pipelines (Push gate, vision queries,
        # racial_save_advantage_for, lucky_d20) consume them
        # uniformly.
        "size": (race_def.get("size") if race_def else "medium"),
        "creature_type": (race_def.get("creature_type")
                              if race_def else "humanoid"),
        "darkvision_range_ft": (
            int(race_def.get("darkvision_range_ft", 0))
            if race_def else 0),
        "racial_traits": list(race_def.get("racial_traits") or [])
            if race_def else [],
        "damage_resistances": list(race_def.get("damage_resistances") or [])
            if race_def else [],
        "race": race_id,    # telemetry only — runtime code uses
                              # template.racial_traits, not the id
        # Chosen subclass id (or None). Telemetry + reception-join key;
        # the subclass's features are already merged into features_known
        # below, so runtime code reads those, not this id.
        "subclass": (subclass_def.get("id") if subclass_def else None),
        # Bardic Inspiration die size at this level (d6→d12), read by the
        # grant + Cutting Words primitives. Only present for Bards.
        "bardic_die": (
            _class_resources_at_level(class_def, level).get("bardic_die")
            if "f_bardic_inspiration" in features_known else None),
        # Metamagic options this Sorcerer knows (chosen at build time via
        # pc_spec.metamagic). engine.core.metamagic.knows() reads this.
        "metamagic_known": (list(pc_spec.get("metamagic") or [])
                              if "f_metamagic" in features_known else []),
        # Per-class level table (read by primitives via
        # `template.levels.<class_short_name>`). Single-class PCs from
        # pc_schema get exactly one entry; multiclass support will
        # extend this dict. PR #71's Rage reader keys off
        # `levels.barbarian`; PR #72's SA reads `levels.rogue`;
        # PR #73's Divine Smite reads `levels.paladin`. Same
        # convention everywhere.
        "levels": {_short_class_name(class_id): level},
        # PR #85: features the PC has at this level — passive +
        # active feature ids accumulated from class.level_table.features
        # entries up to and including `level`. Read by runtime gates
        # like engine.core.reckless_attack.is_eligible that check
        # whether a marker-style feature is present without firing a
        # pipeline. Mirrors the same `features_known` set used by
        # the pc_schema builders above to decide which feature
        # actions to auto-generate; just exposed onto the template
        # for runtime consumers.
        "features_known": sorted(features_known),
        # Per-class spell slot derivation (PR #73). For classes
        # whose level_table declares `spell_slots` in class_resources
        # (Paladin's half-caster progression today; Wizard / Cleric /
        # full casters in future PRs), stamp the level-appropriate
        # slot dict onto the template. cli._build_actor reads this
        # as a fallback when the actor_spec doesn't declare its own
        # `spell_slots:`. Empty dict for non-casters or for classes
        # whose table doesn't declare the field.
        "spell_slots": _derive_class_spell_slots(class_def, level),
        # PR #104: spellcasting ability (from the class's spellcasting
        # block — 'charisma' for Paladin/Warlock, 'intelligence' for
        # Wizard, etc.). Read by _resolve_dc to compute the correct
        # spell save DC (8 + spellcasting_mod + PB). None for
        # non-casters; _resolve_dc falls back to INT.
        "spellcasting_ability": (
            (class_def.get("spellcasting") or {}).get("ability")),
        # Tag for telemetry / debugging
        "derived_from_pc_schema": {
            "class": class_id,
            "level": level,
            "fighting_style": fighting_style,    # None if not chosen
            "skill_proficiencies": list(skill_proficiencies),
            "skill_expertise": list(skill_expertise),
            "skill_bonuses": dict(skill_bonuses),
            "weapon_masteries": list(weapon_masteries),
        },
        # Top-level skill_proficiencies for the runtime skill_modifier
        # helper to read (engine/core/skills.py). Mirrors the monster-
        # template `skills:` dict shape, except PCs store the list of
        # proficient skills (bonus computed on demand from ability + PB).
        "skill_proficiencies": list(skill_proficiencies),
        # PR #62: Expertise list + magic-item bonuses. Both consumed
        # by skill_modifier at runtime via has_skill_expertise and
        # _skill_magic_bonus helpers. Monster templates use the
        # `skills:` dict (which has the bonus already baked); these
        # PC-side fields complement the proficiency list.
        "skill_expertise": list(skill_expertise),
        "skill_bonuses": dict(skill_bonuses),
        # Top-level weapon_masteries (PR #54) — read by cli._build_actor
        # onto Actor.weapon_masteries. Empty list = actor knows no
        # masteries (i.e., doesn't have the class feature OR didn't
        # declare any choices).
        "weapon_masteries": list(weapon_masteries),
        # Passive Perception (PR #51): 10 + WIS_mod + PB if proficient.
        # Mirrors the monster-template `senses.passive_perception` shape.
        # Loaded by cli._build_actor onto Actor.passive_perception.
        "senses": _build_pc_senses_block(
            ability_scores, skill_proficiencies, proficiency_bonus,
            skill_expertise=skill_expertise,
            skill_bonuses=skill_bonuses,
            fighting_style=fighting_style),
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
    # Subclass features may drive resources too (e.g. a subclass that
    # grants a use-limited feature). Merge them in the same way
    # build_pc_template does, so resource derivation sees the full set.
    subclass_def = _resolve_subclass(
        pc_spec, class_def, class_id, level, content_registry)
    if subclass_def:
        features_known = set(features_known) | _subclass_features_at_level(
            subclass_def, level)
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

    # ---- Rage (Barbarian L1+) — PR #71 ----
    # rage_uses scales with Barbarian level via the class table; we
    # also stamp `rage_uses_max` so apply_long_rest can restore the
    # ceiling without rescanning the class def. The bonus-action
    # `a_rage` (auto-generated in _build_feature_actions) consumes
    # `rage_uses_remaining` via its feature_use gate.
    if "f_rage" in features_known and class_id == "c_barbarian":
        uses = int(class_resources_at_level.get("rage_uses", 0))
        if uses > 0:
            resources["rage_uses_remaining"] = uses
            resources["rage_uses_max"] = uses

    # ---- Bardic Inspiration (Bard L1+) ----
    # Uses = Charisma modifier (minimum 1) — the first CHA-mod-derived
    # resource (others read fixed values off the class table). Regained
    # on a long rest (short+long at L5 via Font of Inspiration, deferred).
    # Consumed by the f_bardic_inspiration grant action AND by Cutting
    # Words (College of Lore) via their feature_use gates.
    if "f_bardic_inspiration" in features_known:
        cha_score = _resolve_ability_scores(
            pc_spec.get("ability_scores") or {})["cha"]["score"]
        uses = max(1, ability_modifier(cha_score))
        resources["bardic_inspiration_uses_remaining"] = uses
        resources["bardic_inspiration_uses_max"] = uses

    # ---- Sorcery Points (Sorcerer, Font of Magic L2+) ----
    # Pool = the Sorcerer level (capped at 20), read off the per-row
    # class_resources.sorcery_points. Fuels Metamagic + slot conversion.
    if "f_font_of_magic" in features_known:
        sp = int(class_resources_at_level.get("sorcery_points", 0))
        if sp > 0:
            resources["sorcery_points_remaining"] = sp
            resources["sorcery_points_max"] = sp

    # ---- Innate Sorcery (Sorcerer L1+) — 2 uses/long rest ----
    if "f_innate_sorcery" in features_known:
        resources["innate_sorcery_uses_remaining"] = 2
        resources["innate_sorcery_uses_max"] = 2

    # ---- Lay on Hands (Paladin L1+) — PR #83 ----
    # Pool = 5 × paladin_level HP. Refreshes on long rest. The
    # lay_on_hands primitive reads `lay_on_hands_pool_remaining` to
    # gate / debit; apply_long_rest restores to
    # `lay_on_hands_pool_max`.
    if "f_lay_on_hands" in features_known and class_id == "c_paladin":
        pool = 5 * level
        resources["lay_on_hands_pool_remaining"] = pool
        resources["lay_on_hands_pool_max"] = pool

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
    "two_weapon_fighting",     # PR #53: lets off-hand attack add the
                                # ability modifier to its damage (RAW
                                # default is no ability mod on off-
                                # hand). Off-hand action is generated
                                # by pc_schema when off_hand_weapon: is
                                # specified.
    "blind_fighting",          # PR #63: grants blindsight 10 ft. Baked
                                # onto template.senses.special.blindsight
                                # at build time; cli._build_actor loads
                                # it onto Actor.blindsight_range_ft via
                                # the same pathway as monster-template
                                # blindsight (PR #52).
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


def _validate_off_hand_weapon(off_hand: dict, weapons: list) -> None:
    """Enforce RAW 2024 Two-Weapon Fighting gates on the off-hand
    weapon spec (PR #53).

    Requirements:
      1. off_hand must be a melee weapon (no `range_ft`) — RAW restricts
         the off-hand attack to melee.
      2. off_hand must have `light: true` — RAW: "Light melee weapon"
         is the explicit gate on the off-hand attack.
      3. At least one of `weapons` must also be Light melee. RAW: the
         primary attack must use a Light weapon for the off-hand bonus
         to trigger (technically RAW says "a Light melee weapon," meaning
         the primary-Attack-action weapon).
      4. off_hand must NOT have `two_handed: true` (two-handed weapons
         are mutually exclusive with off-hand wielding).

    Raises ValueError on any failure. Stays silent on success.
    """
    if not isinstance(off_hand, dict):
        raise ValueError(
            f"off_hand_weapon must be a weapon-spec dict, got "
            f"{type(off_hand).__name__}"
        )
    if "range_ft" in off_hand:
        raise ValueError(
            f"off_hand_weapon must be melee (has reach_ft, not range_ft). "
            f"Got range_ft={off_hand.get('range_ft')}."
        )
    if off_hand.get("two_handed"):
        raise ValueError(
            "off_hand_weapon cannot be two_handed: true — two-handed "
            "weapons can't be wielded in the off hand."
        )
    if not off_hand.get("light"):
        raise ValueError(
            f"off_hand_weapon must have `light: true` (RAW 2024: only "
            f"Light melee weapons qualify for the off-hand attack). "
            f"Got weapon id={off_hand.get('id')!r}."
        )
    # Primary-hand check: at least one declared `weapons:` entry must
    # be a Light melee weapon. (The runtime AI picks whichever primary
    # attack to use; we just enforce that *some* primary qualifies.)
    has_light_primary = any(
        (w.get("light") and "range_ft" not in w)
        for w in (weapons or [])
    )
    if not has_light_primary:
        raise ValueError(
            "off_hand_weapon requires at least one primary `weapons:` "
            "entry that is also Light melee (RAW: primary attack must "
            "be a Light weapon for the off-hand bonus to trigger)."
        )


def _nick_active(off_hand_spec: dict, weapons: list,
                    weapon_masteries: list[str]) -> bool:
    """Determine if Nick mastery is active for the off-hand attack
    (PR #57).

    Returns True iff BOTH:
      1. The actor knows the Nick mastery (it's in their declared
         `weapon_masteries` list).
      2. At least one wielded Light melee weapon (off-hand OR any
         primary) has `mastery: nick` set on its spec.

    When active, the caller (`build_pc_template`) overrides the
    off-hand action's slot from `bonus_action` to `free`, and the
    runner's free-phase auto-fires it after the main action — RAW:
    "you can make that extra attack as part of the same action."

    Returns False if either condition fails. Designed to fail-closed
    on missing data so we never apply Nick to a weapon spec that
    doesn't claim it.
    """
    if "nick" not in (weapon_masteries or []):
        return False
    # Check off-hand first (most common case: dual-wielding daggers,
    # both of which have Nick).
    if off_hand_spec and off_hand_spec.get("mastery") == "nick":
        return True
    # Otherwise check primary weapons for any Light melee with Nick.
    for w in (weapons or []):
        if "range_ft" in w:    # ranged disqualifies
            continue
        if not w.get("light"):    # Nick gate also requires Light
            continue
        if w.get("mastery") == "nick":
            return True
    return False


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


def _validate_skill_expertise(value,
                                  proficiencies: list[str]) -> list[str]:
    """Return a normalized list of skills the PC has Expertise in
    (PR #62), or [] when None / empty.

    Raises ValueError if:
      - value is not a list
      - any entry is not a known skill name
      - any entry is not ALSO in `proficiencies` (RAW: Expertise
        requires Proficiency — you can't double a PB you don't have)

    The proficiency-required gate is enforced here rather than at
    runtime so authors catch typos / missing proficiencies at
    build time.
    """
    if value is None or value == "":
        return []
    from engine.core.skills import validate_skill_name
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            f"skill_expertise must be a list, got {type(value).__name__}"
        )
    profs_normalized = {s.lower() for s in proficiencies}
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        n = validate_skill_name(str(raw))
        if n not in profs_normalized:
            raise ValueError(
                f"Expertise in {n!r} requires also being proficient. "
                f"Add {n!r} to skill_proficiencies, OR remove it from "
                f"skill_expertise. Current proficiencies: "
                f"{sorted(profs_normalized)}."
            )
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out


def _validate_skill_bonuses(value) -> dict:
    """Return a normalized dict of skill_name → int bonus, or {} when
    None / empty (PR #62).

    Raises ValueError if:
      - value is not a dict
      - any key is not a known skill name
      - any value is not int-coercible

    Used for magic-item bonuses (Cloak of Elvenkind +5 Stealth, etc.).
    Different skills can independently get bonuses; the dict shape
    is more authoring-friendly than a list-of-objects.
    """
    if value is None or value == "":
        return {}
    from engine.core.skills import validate_skill_name
    if not isinstance(value, dict):
        raise ValueError(
            f"skill_bonuses must be a dict, got {type(value).__name__}"
        )
    out: dict = {}
    for raw_key, raw_value in value.items():
        n = validate_skill_name(str(raw_key))
        try:
            bonus = int(raw_value)
        except (TypeError, ValueError):
            raise ValueError(
                f"skill_bonuses[{raw_key!r}] must be an int, got "
                f"{type(raw_value).__name__}: {raw_value!r}"
            )
        out[n] = bonus
    return out


def _validate_weapon_masteries_cap(weapon_masteries: list,
                                        class_def: dict,
                                        level: int,
                                        class_id: str) -> None:
    """Raise ValueError if the PC declares more weapon masteries
    than their class permits at the given level (PR #64).

    Closes the v1 TODO from PR #54 ("trusts the spec"). Reads the
    `weapon_mastery_count` from the highest-applicable level_table
    row (≤ `level`); raises if `len(weapon_masteries)` exceeds it.

    Classes that don't grant Weapon Mastery (Wizard, etc.) have
    `weapon_mastery_count` absent from their level_table —
    declaring any weapon_masteries on such a PC raises (cap = 0).

    Silent (no-op) when `weapon_masteries` is empty: declaring zero
    masteries is always legal, even for non-mastery-having classes.
    """
    if not weapon_masteries:
        return
    # Find the highest applicable level_table row
    cap = 0
    cap_level = 0
    for row in (class_def.get("level_table") or []):
        if int(row.get("level", 0)) > level:
            continue
        row_cap = ((row.get("class_resources") or {})
                       .get("weapon_mastery_count"))
        if row_cap is not None:
            cap = int(row_cap)
            cap_level = int(row.get("level", 0))
    if len(weapon_masteries) > cap:
        if cap == 0:
            raise ValueError(
                f"Class {class_id!r} at level {level} grants no "
                f"weapon masteries (cap=0), but PC declares "
                f"{len(weapon_masteries)}: {weapon_masteries}. "
                f"Remove the weapon_masteries field, OR pick a "
                f"class that grants Weapon Mastery (Fighter, "
                f"Barbarian, Paladin, Ranger, Rogue)."
            )
        raise ValueError(
            f"Class {class_id!r} at level {level} grants "
            f"{cap} weapon masteries (set at level {cap_level}), "
            f"but PC declares {len(weapon_masteries)}: "
            f"{weapon_masteries}. Reduce the list to {cap} entries."
        )


def _compute_passive_perception(ability_scores: dict,
                                    skill_proficiencies: list[str],
                                    proficiency_bonus: int,
                                    skill_expertise: list[str] | None = None,
                                    skill_bonuses: dict | None = None) -> int:
    """10 + WIS_mod + (PB×expertise_mult if proficient) + magic bonus.

    PR #51: PCs derive passive Perception so vision checks against
    hidden creatures (PR #48's Hide) have a number to compare
    against. Monster templates declare this directly under
    `senses.passive_perception`; we mirror that shape for PCs.

    PR #62: factor skill expertise (2×PB) and magic-item bonuses
    (Cloak of Elvenkind / Eyes of the Eagle / etc.) into the
    passive value. Same shape as active `skill_modifier`.
    """
    wis_score = int((ability_scores.get("wis") or {}).get("score", 10))
    mod = ability_modifier(wis_score)
    base = 10 + mod
    profs_lower = {s.lower() for s in skill_proficiencies}
    if "perception" in profs_lower:
        pb = int(proficiency_bonus)
        expertise_lower = {s.lower() for s in (skill_expertise or [])}
        if "perception" in expertise_lower:
            base += 2 * pb
        else:
            base += pb
    # Magic-item bonus: flat add (case-insensitive match)
    for name, value in (skill_bonuses or {}).items():
        if str(name).lower() == "perception":
            base += int(value)
            break
    return base


def _build_pc_senses_block(ability_scores: dict,
                                skill_proficiencies: list[str],
                                proficiency_bonus: int,
                                skill_expertise: list[str] | None = None,
                                skill_bonuses: dict | None = None,
                                fighting_style: str | None = None
                                ) -> dict:
    """Assemble the PC template's `senses:` block (PR #63).

    Always includes `passive_perception`. Optionally includes
    `special.<sense>: <range_ft>` for senses granted by class
    features:
      - Blind Fighting (PR #63): blindsight 10 ft

    Mirrors the monster-template `senses:` schema so
    `cli._build_actor` can read both via the same code path.
    """
    block: dict = {
        "passive_perception": _compute_passive_perception(
            ability_scores, skill_proficiencies, proficiency_bonus,
            skill_expertise=skill_expertise,
            skill_bonuses=skill_bonuses),
    }
    special: dict = {}
    if fighting_style == "blind_fighting":
        special["blindsight"] = 10
    if special:
        block["special"] = special
    return block


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


def _subclass_features_at_level(subclass_def: dict, level: int) -> set[str]:
    """Set of feature IDs granted by a subclass at or before `level`,
    read from its `features_by_level` rows (each {level, feature_ids}).

    Mirror of `_features_known_at_level` but for the subclass schema's
    `features_by_level` / `feature_ids` shape (vs the class table's
    `level_table` / `features`)."""
    features: set[str] = set()
    if not subclass_def:
        return features
    for row in (subclass_def.get("features_by_level") or []):
        if int(row.get("level", 0)) > level:
            continue
        for fid in (row.get("feature_ids") or []):
            features.add(fid)
    return features


def _resolve_subclass(pc_spec: dict, class_def: dict, class_id: str,
                       level: int, content_registry: Any) -> dict | None:
    """Validate + return the PC's chosen subclass definition, or None.

    `pc_spec.subclass` (e.g. "sc_champion") is optional. When set it must:
      - resolve to a subclass in the content registry,
      - have `parent_class` equal to the PC's class, and
      - be allowed at the PC's level (>= the class's subclass_grant_level,
        default 3 per PHB 2024).

    Raises ValueError on any violation (unknown id, wrong parent class,
    or chosen below the grant level). Returns None when no subclass is
    specified — backward-compatible with every existing subclass-less PC.
    """
    sub_id = pc_spec.get("subclass")
    if not sub_id:
        return None
    try:
        subclass_def = content_registry.get("subclass", sub_id)
    except (KeyError, AttributeError):
        raise ValueError(
            f"pc_spec.subclass={sub_id!r} not found in content registry."
        )
    if subclass_def is None:
        raise ValueError(
            f"pc_spec.subclass={sub_id!r} not found in content registry."
        )
    parent = subclass_def.get("parent_class")
    if parent != class_id:
        raise ValueError(
            f"subclass {sub_id!r} belongs to class {parent!r}, not the "
            f"PC's class {class_id!r}."
        )
    grant_level = int(class_def.get("subclass_grant_level", 3))
    if level < grant_level:
        raise ValueError(
            f"subclass {sub_id!r} requires level >= {grant_level} "
            f"(PC is level {level})."
        )
    return subclass_def


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
                             weapon_actions: list[dict] | None = None,
                             ability_scores: dict | None = None,
                             proficiency_bonus: int = 2
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
    # PR #71: Barbarian Rage — bonus-action signature action that
    # consumes `rage_uses_remaining` and flips Actor.rage_active.
    if "f_rage" in features_known and class_id == "c_barbarian":
        actions.append(_build_rage_action())
    # PR #74: Rogue Cunning Action — three bonus-action variants
    # (Dash / Disengage / Hide). Adds to the action list alongside
    # the standard main-action versions (those come from the
    # built-in action set; they aren't generated here). RAW: CA
    # ADDS the BA usage; it doesn't replace the main-Action versions.
    if "f_cunning_action" in features_known and class_id == "c_rogue":
        actions.extend(_build_cunning_action_actions())
    # PR #80: Rogue Steady Aim — Bonus Action that grants advantage
    # on the next attack roll this turn AND sets speed to 0. Gated
    # at candidate-emission time on `actor.moved_this_turn == False`
    # (the pipeline filter skips Steady Aim when movement has been
    # spent).
    if "f_steady_aim" in features_known and class_id == "c_rogue":
        actions.append(_build_steady_aim_action())
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
    # PR #102: Warlock Eldritch Blast — iconic at-will cantrip. Ranged
    # spell attack, 1d10 force, beams scale with CHARACTER level
    # (1/2/3/4 at L1/L5/L11/L17). Mirrors the Extra Attack pattern: a
    # single-beam action always present, plus a multiattack wrapper
    # at L5+ referencing the beam N times.
    if "f_eldritch_blast" in features_known and ability_scores is not None:
        actions.extend(_build_eldritch_blast_actions(
            level, ability_scores, proficiency_bonus,
            agonizing="f_agonizing_blast" in features_known,
            repelling="f_repelling_blast" in features_known))
    # PR #115: Cleric save-for-damage cantrips. Single-target, no attack
    # roll — target saves vs the caster's spell save DC or takes Nd8
    # damage, where N scales with CHARACTER level (1/2/3/4 at
    # L1/5/11/17). Built as `save_attack` actions whose forced_save
    # pipeline runs via _execute_single.
    if "f_sacred_flame" in features_known:
        actions.append(_build_sacred_flame_action(level))
    if "f_toll_the_dead" in features_known:
        actions.append(_build_toll_the_dead_action(level))
    # Fire Bolt — the arcane ranged-spell-attack cantrip. Mirrors the
    # Eldritch Blast single-beam path (attack bonus = spell ability mod
    # + PB, damage gated on hit), but the cantrip upgrade scales the
    # DIE count (Nd10 fire) rather than the beam count, so there is no
    # multiattack wrapper. Built here because both the attack bonus and
    # the die count depend on the PC's ability + character level.
    if "f_fire_bolt" in features_known and ability_scores is not None:
        actions.append(_build_fire_bolt_action(
            level, ability_scores, proficiency_bonus, class_id))
    # batch-2 attack/save cantrips + leveled spell-attacks. All bake the
    # spell attack bonus (spell mod + PB) at PC-build time because the
    # attack_roll primitive takes a fixed bonus; cantrips also bake the
    # character-level die count. Gated on the feature id, so only the
    # granting class builds each.
    # NOTE: Ray of Frost, Vicious Mockery, Guiding Bolt, Chromatic Orb,
    # Scorching Ray, and the mass heals are now built data-driven from
    # their YAML `pc_builder` blocks (see _dispatch_pc_builder, invoked
    # in build_pc_template). New attack/heal spells add a pc_builder
    # block and need NO edit here.
    # PR #116: Cure Wounds — direct heal (2d8 + spellcasting-ability
    # mod). Built here (not auto-attached) because the +mod depends on
    # the caster's ability, like Eldritch Blast / the cantrips.
    if "f_cure_wounds" in features_known and ability_scores is not None:
        actions.append(_build_cure_wounds_action(
            level, ability_scores, class_id))
    # PR #118: Healing Word — bonus-action ranged heal (1d4 + mod).
    # Same builder pattern as Cure Wounds; the BA slot + 60-ft range
    # make it the "pick an ally up from across the field" heal.
    if "f_healing_word" in features_known and ability_scores is not None:
        actions.append(_build_healing_word_action(
            level, ability_scores, class_id))
    return actions


# Spellcasting ability per class — the heal/save bonus on ability-
# dependent built actions reads this. Mirrors each class YAML's
# spellcasting.ability (duplicated here because _build_feature_actions
# doesn't carry the class_def; kept small + covering only spell classes).
_SPELL_ABILITY_BY_CLASS = {
    "c_cleric": "wis", "c_paladin": "cha", "c_ranger": "wis",
    "c_wizard": "int", "c_warlock": "cha",
    # Spellcasting abilities for SRD caster classes not yet shipped as
    # class YAMLs (Bard/Sorcerer/Druid). Listed so attack/save cantrip
    # builders compute the right modifier when those classes land + so
    # batch-2 spell tests can exercise the builders directly. The
    # dispatch only fires once the class exists to grant the feature.
    "c_bard": "cha", "c_sorcerer": "cha", "c_druid": "wis",
}


def _build_cure_wounds_action(level: int, ability_scores: dict,
                                 class_id: str) -> dict:
    """Cure Wounds (PR #116): a 1st-level touch heal, 2d8 + the
    caster's spellcasting-ability modifier (WIS for Cleric). type
    `heal` → the candidate generator enumerates it per ally and
    defensive_ehp_healing scores it (capped at missing HP ×
    desperation, so the AI heals whoever's most hurt).

    Deferred: upcast (+2d8 per slot above 1st) — base cast only in v1,
    same simplification as other non-damage spells; touch-range gating
    (heal candidates use generous ally range today).
    """
    abbr = _SPELL_ABILITY_BY_CLASS.get(class_id, "wis")
    score = (ability_scores.get(abbr) or {}).get("score", 10)
    mod = max(0, ability_modifier(score))
    return {
        "id": "a_cure_wounds",
        "name": "Cure Wounds",
        "type": "heal",
        "slot": "action",
        "spell_slot_level": 1,
        "range_ft": 5,               # touch (range gating deferred)
        "pipeline": [
            {"primitive": "heal",
              "params": {"target": "current_target",
                          "dice": "2d8", "modifier": mod}},
        ],
    }


def _build_healing_word_action(level: int, ability_scores: dict,
                                  class_id: str) -> dict:
    """Healing Word (PR #118): a 1st-level BONUS-action ranged heal,
    2d4 + the caster's spellcasting-ability modifier, 60 ft (RAW 2024).
    Same `heal`-type shape as Cure Wounds (enumerated per ally, scored
    by defensive_ehp_healing) — the differences are the bonus-action
    slot and the 60-ft range, which make it the emergency "heal an ally
    across the field without spending your action" option.

    Deferred: upcast (+2d4 per slot above 1st) — base cast only in v1,
    matching Cure Wounds.
    """
    abbr = _SPELL_ABILITY_BY_CLASS.get(class_id, "wis")
    score = (ability_scores.get(abbr) or {}).get("score", 10)
    mod = max(0, ability_modifier(score))
    return {
        "id": "a_healing_word",
        "name": "Healing Word",
        "type": "heal",
        "slot": "bonus_action",
        "spell_slot_level": 1,
        "range_ft": 60,
        "pipeline": [
            {"primitive": "heal",
              "params": {"target": "current_target",
                          "dice": "2d4", "modifier": mod}},
        ],
    }


# Mass heals now build from their YAML pc_builder blocks via
# _dispatch_pc_builder → _build_heal_action. These thin wrappers are kept
# so direct-call tests + any external callers resolve to the same generic
# builder (identical output).
def _build_mass_healing_word_action(level: int, ability_scores: dict,
                                       class_id: str) -> dict:
    return _build_heal_action(
        "a_mass_healing_word", "Mass Healing Word", level, ability_scores,
        class_id, slot="bonus_action", slot_level=3, range_ft=60,
        dice="2d4", max_targets=6)


def _build_mass_cure_wounds_action(level: int, ability_scores: dict,
                                      class_id: str) -> dict:
    return _build_heal_action(
        "a_mass_cure_wounds", "Mass Cure Wounds", level, ability_scores,
        class_id, slot="action", slot_level=5, range_ft=60,
        dice="5d8", max_targets=6)


def _cantrip_dice_count(character_level: int) -> int:
    """Cantrip damage-die count by CHARACTER level (RAW PHB 2024):
    1 at L1-4, 2 at L5-10, 3 at L11-16, 4 at L17+. Shared by all
    level-scaling damage cantrips."""
    if character_level >= 17:
        return 4
    if character_level >= 11:
        return 3
    if character_level >= 5:
        return 2
    return 1


def _build_save_cantrip_action(action_id: str, name: str, level: int, *,
                                  save_ability: str, damage_type: str,
                                  die: int, range_ft: int) -> dict:
    """Build a single-target save-for-damage cantrip action (PR #115).

    Shape: type `save_attack`, spell_slot_level 0 (cantrip, no slot),
    pipeline = one forced_save (save_ability vs caster_spell_save_dc)
    whose on_fail deals `<N>d<die>` of `damage_type`, N from
    `_cantrip_dice_count`. No half-on-success (these cantrips deal
    nothing on a successful save). save_ability is mirrored onto the
    top-level action so the scorer (offensive_ehp_save_attack) can read
    it without walking the pipeline.
    """
    n = _cantrip_dice_count(level)
    dice = f"{n}d{die}"
    return {
        "id": action_id,
        "name": name,
        "type": "save_attack",
        "slot": "action",
        "spell_slot_level": 0,            # cantrip — consumes no slot
        "save_ability": save_ability,
        "save_dc_source": "caster_spell_save_dc",
        "half_on_success": False,
        "range_ft": range_ft,
        "pipeline": [
            {"primitive": "forced_save",
              "params": {
                  "ability": save_ability,
                  "dc_source": "caster_spell_save_dc",
                  "affected": "current_target",
                  "on_fail": [
                      {"primitive": "damage",
                        "params": {"dice": dice, "modifier": 0,
                                     "type": damage_type}},
                  ],
                  "on_success": [],
              }},
        ],
    }


def _build_sacred_flame_action(level: int) -> dict:
    """Sacred Flame (PR #115): 60 ft, DEX save or Nd8 radiant. Ignores
    cover RAW — cover modeling on save_attack is deferred (v1 treats it
    as a normal targeted save)."""
    return _build_save_cantrip_action(
        "a_sacred_flame", "Sacred Flame", level,
        save_ability="dexterity", damage_type="radiant", die=8,
        range_ft=60)


def _build_fire_bolt_action(level: int, ability_scores: dict,
                              proficiency_bonus: int,
                              class_id: str) -> dict:
    """Fire Bolt: 120-ft ranged spell attack, Nd10 fire on a hit.

    Attack bonus = the caster's spellcasting-ability modifier (INT for
    Wizard, per _SPELL_ABILITY_BY_CLASS) + proficiency bonus, exactly
    like the Eldritch Blast beam. Damage = Nd10 fire with N from
    _cantrip_dice_count (1/2/3/4 at character level 1/5/11/17) and NO
    ability modifier (cantrips add none RAW). spell_slot_level 0 →
    consumes no slot. Single beam — the cantrip upgrade scales the die
    count, not the attack count, so there is no multiattack wrapper.
    """
    abbr = _SPELL_ABILITY_BY_CLASS.get(class_id, "int")
    score = (ability_scores.get(abbr) or {}).get("score", 10)
    attack_bonus = ability_modifier(score) + proficiency_bonus
    n = _cantrip_dice_count(level)
    return {
        "id": "a_fire_bolt",
        "name": "Fire Bolt",
        "type": "weapon_attack",
        "slot": "action",
        "spell_slot_level": 0,            # cantrip — consumes no slot
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "ranged", "ability": abbr,
                          "bonus": attack_bonus, "range_ft": 120}},
            {"primitive": "damage",
              "params": {"dice": f"{n}d10", "modifier": 0, "type": "fire"},
              "when": {"condition": "combat.attack_state == hit"}},
        ],
    }


def _spell_attack_bonus(ability_scores: dict, proficiency_bonus: int,
                          class_id: str) -> tuple[int, str]:
    """(attack_bonus, ability_abbr) for a spell attack: the caster's
    spellcasting-ability modifier + proficiency bonus. Shared by every
    attack-roll spell builder (Fire Bolt has its own copy for history)."""
    abbr = _SPELL_ABILITY_BY_CLASS.get(class_id, "int")
    score = (ability_scores.get(abbr) or {}).get("score", 10)
    return ability_modifier(score) + proficiency_bonus, abbr


def _build_attack_cantrip_action(action_id: str, name: str, level: int,
                                    ability_scores: dict, proficiency_bonus: int,
                                    class_id: str, *, damage_type: str,
                                    die: int, range_ft: int,
                                    attack_kind: str = "ranged") -> dict:
    """Generic spell-attack cantrip (Ray of Frost shape; Fire Bolt
    predates this helper). Attack bonus = spell mod + PB; damage = Nd<die>
    of `damage_type` with N from _cantrip_dice_count, gated on hit. No
    ability modifier on the damage (cantrip RAW). spell_slot_level 0.

    attack_kind: "ranged" (default) → `range_ft`; "melee" (touch cantrips
    like Chill Touch / Shocking Grasp) → `reach_ft` instead, with
    range_ft taken as the reach (5 for touch)."""
    attack_bonus, abbr = _spell_attack_bonus(
        ability_scores, proficiency_bonus, class_id)
    n = _cantrip_dice_count(level)
    if attack_kind == "melee":
        attack_params = {"kind": "melee", "ability": abbr,
                          "bonus": attack_bonus, "reach_ft": range_ft}
    else:
        attack_params = {"kind": "ranged", "ability": abbr,
                          "bonus": attack_bonus, "range_ft": range_ft}
    return {
        "id": action_id,
        "name": name,
        "type": "weapon_attack",
        "slot": "action",
        "spell_slot_level": 0,
        "pipeline": [
            {"primitive": "attack_roll", "params": attack_params},
            {"primitive": "damage",
              "params": {"dice": f"{n}d{die}", "modifier": 0,
                          "type": damage_type},
              "when": {"condition": "combat.attack_state == hit"}},
        ],
    }


def _build_leveled_spell_attack_action(action_id: str, name: str, *,
                                          slot_level: int, range_ft: int,
                                          ability_scores: dict,
                                          proficiency_bonus: int, class_id: str,
                                          damage_dice: str, damage_type: str,
                                          ray_count: int = 1,
                                          upcast_dice: str | None = None) -> dict:
    """Generic leveled ranged-spell-attack action (Guiding Bolt,
    Chromatic Orb, Scorching Ray). Attack bonus = spell mod + PB, baked
    at PC-build time because the attack_roll primitive takes a fixed
    bonus. `ray_count` > 1 emits that many (attack_roll, damage-on-hit)
    pairs in one action (Scorching Ray's three rays focus-fired in v1).
    `upcast_dice` (single-ray only) attaches a per-slot-level scaling
    block; multi-ray upcast adds RAYS not dice (RAW), so it's left off."""
    attack_bonus, abbr = _spell_attack_bonus(
        ability_scores, proficiency_bonus, class_id)
    pipeline: list[dict] = []
    for _ in range(max(1, ray_count)):
        pipeline.append(
            {"primitive": "attack_roll",
              "params": {"kind": "ranged", "ability": abbr,
                          "bonus": attack_bonus, "range_ft": range_ft}})
        pipeline.append(
            {"primitive": "damage",
              "params": {"dice": damage_dice, "modifier": 0,
                          "type": damage_type},
              "when": {"condition": "combat.attack_state == hit"}})
    action = {
        "id": action_id,
        "name": name,
        "type": "weapon_attack",
        "slot": "action",
        "spell_slot_level": slot_level,
        "pipeline": pipeline,
    }
    if upcast_dice and ray_count == 1:
        action["upcast_scaling"] = {"extra_dice_per_level": upcast_dice,
                                      "damage_type": damage_type}
    return action


def _build_heal_action(action_id: str, name: str, level: int,
                         ability_scores: dict, class_id: str, *,
                         slot: str, slot_level: int, range_ft: int,
                         dice: str, max_targets: int = 1) -> dict:
    """Generic heal action: `<dice>` + the caster's spellcasting-ability
    modifier (floored at 0). Subsumes Cure Wounds / Healing Word / the
    mass heals — they differ only in id/name/slot/slot_level/range/dice/
    max_targets, all of which are parameters here. max_targets > 1 routes
    through the candidate generator's multi-target (Aid-shape) grouping.

    Deferred (matching the per-spell builders it replaces): upcast
    scaling on the healing dice — base cast only in v1."""
    abbr = _SPELL_ABILITY_BY_CLASS.get(class_id, "wis")
    score = (ability_scores.get(abbr) or {}).get("score", 10)
    mod = max(0, ability_modifier(score))
    action = {
        "id": action_id,
        "name": name,
        "type": "heal",
        "slot": slot,
        "spell_slot_level": slot_level,
        "range_ft": range_ft,
        "pipeline": [
            {"primitive": "heal",
              "params": {"target": "current_target",
                          "dice": dice, "modifier": mod}},
        ],
    }
    if max_targets and int(max_targets) > 1:
        action["max_targets"] = int(max_targets)
    return action


def _dispatch_pc_builder(feature_def: dict, level: int,
                           ability_scores: dict, proficiency_bonus: int,
                           class_id: str) -> dict | None:
    """Data-driven spell-action builder. A feature YAML can declare a
    `pc_builder` block instead of an `action_template` when its action
    must be computed at PC-build time (spell-attack bonus from the
    caster's ability + PB; cantrip die count from character level; heal
    +mod from ability). This lets new attack/heal spells be added by YAML
    ALONE — no per-feature dispatch edit in this module.

    pc_builder shape:
        pc_builder:
          kind: attack_cantrip | save_cantrip | spell_attack | heal
          action_id: a_<spell>
          name: <Spell Name>
          params: { ...kind-specific... }

    Kind-specific params:
      attack_cantrip: damage_type, die, range_ft
      save_cantrip:   save_ability, damage_type, die, range_ft
      spell_attack:   slot_level, range_ft, damage_dice, damage_type,
                      [ray_count], [upcast_dice]
      heal:           slot, slot_level, range_ft, dice, [max_targets]

    Returns the built action dict, or None if the feature has no
    pc_builder block. Raises ValueError on an unknown kind."""
    spec = feature_def.get("pc_builder")
    if not spec:
        return None
    kind = spec.get("kind")
    aid = spec.get("action_id")
    name = spec.get("name")
    p = spec.get("params") or {}
    if not (kind and aid and name):
        raise ValueError(
            f"pc_builder requires kind + action_id + name (got {spec!r})")
    if kind == "attack_cantrip":
        return _build_attack_cantrip_action(
            aid, name, level, ability_scores, proficiency_bonus, class_id,
            damage_type=p["damage_type"], die=int(p["die"]),
            range_ft=int(p["range_ft"]),
            attack_kind=p.get("attack_kind", "ranged"))
    if kind == "save_cantrip":
        return _build_save_cantrip_action(
            aid, name, level, save_ability=p["save_ability"],
            damage_type=p["damage_type"], die=int(p["die"]),
            range_ft=int(p["range_ft"]))
    if kind == "spell_attack":
        return _build_leveled_spell_attack_action(
            aid, name, slot_level=int(p["slot_level"]),
            range_ft=int(p["range_ft"]), ability_scores=ability_scores,
            proficiency_bonus=proficiency_bonus, class_id=class_id,
            damage_dice=p["damage_dice"], damage_type=p["damage_type"],
            ray_count=int(p.get("ray_count", 1)),
            upcast_dice=p.get("upcast_dice"))
    if kind == "heal":
        return _build_heal_action(
            aid, name, level, ability_scores, class_id,
            slot=p.get("slot", "action"), slot_level=int(p["slot_level"]),
            range_ft=int(p["range_ft"]), dice=p["dice"],
            max_targets=int(p.get("max_targets", 1)))
    raise ValueError(f"unknown pc_builder kind: {kind!r}")


def _build_toll_the_dead_action(level: int) -> dict:
    """Toll the Dead (PR #115): 60 ft, WIS save or Nd8 necrotic.
    Proves the save_attack infra generalizes across save ability +
    damage type. RAW the die is d12 if the target is missing HP — the
    conditional upgrade is deferred (v1 always d8), a documented
    simplification alongside the other v1 flat-die choices."""
    return _build_save_cantrip_action(
        "a_toll_the_dead", "Toll the Dead", level,
        save_ability="wisdom", damage_type="necrotic", die=8,
        range_ft=60)


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


# PR #103: Eldritch Invocation registry. Each entry: the prerequisite
# check (returns None if OK, else an error string). Minimal v1 ships
# Agonizing Blast only; future invocations add entries here.
_KNOWN_INVOCATIONS: frozenset[str] = frozenset({
    "f_agonizing_blast",
    "f_repelling_blast",
})


def _validate_invocations(raw, features_known: set[str],
                             class_id: str, level: int) -> list[str]:
    """Validate a pc_spec `invocations` list (PR #103).

    Rules:
      - Only c_warlock may take invocations (RAW: Warlock-only).
      - Each id must be in _KNOWN_INVOCATIONS.
      - Prerequisite check: both f_agonizing_blast and
        f_repelling_blast require the Warlock to know Eldritch Blast
        (f_eldritch_blast in features_known).
      - Duplicates are de-duped.

    Returns the validated list (possibly empty). Raises ValueError on
    a non-Warlock taking invocations, an unknown id, or a failed
    prerequisite — these are authoring errors, surfaced loudly.
    """
    if not raw:
        return []
    if class_id != "c_warlock":
        raise ValueError(
            f"invocations are Warlock-only; {class_id!r} can't take them")
    if not isinstance(raw, list):
        raise ValueError("pc_spec.invocations must be a list of ids")
    validated: list[str] = []
    for inv in raw:
        if inv in validated:
            continue
        if inv not in _KNOWN_INVOCATIONS:
            raise ValueError(f"unknown invocation: {inv!r}")
        if inv in ("f_agonizing_blast", "f_repelling_blast") \
                and "f_eldritch_blast" not in features_known:
            raise ValueError(
                f"{inv} requires knowing Eldritch Blast")
        validated.append(inv)
    return validated


def _eldritch_blast_beams_at_level(level: int) -> int:
    """Eldritch Blast beam count by CHARACTER level (RAW PHB 2024):
    1 at L1-4, 2 at L5-10, 3 at L11-16, 4 at L17+. For single-class
    Warlocks character level == warlock level."""
    if level >= 17:
        return 4
    if level >= 11:
        return 3
    if level >= 5:
        return 2
    return 1


def _build_eldritch_blast_actions(level: int, ability_scores: dict,
                                     proficiency_bonus: int,
                                     agonizing: bool = False,
                                     repelling: bool = False) -> list[dict]:
    """Build the Eldritch Blast action(s) (PR #102, Agonizing Blast
    PR #103, Repelling Blast PR #106).

    Always returns the single-beam `a_eldritch_blast` (ranged spell
    attack, 1d10 force, spell_slot_level 0 = cantrip, attack bonus =
    CHA mod + PB). At character level 5+, ALSO returns a multiattack
    wrapper `a_eldritch_blast_beams` firing N beams — mirroring the
    Fighter Extra Attack pattern (both the single + the multi are
    candidates; the AI picks the higher-scoring multi).

    The spell attack bonus is computed here from the Warlock's CHA
    (the spellcasting ability per c_warlock.yaml's spellcasting
    block) + proficiency bonus.

    Damage: base 1d10 force, no ability mod. When `agonizing=True`
    (the Warlock has the Agonizing Blast invocation, PR #103), each
    beam adds the CHA modifier to its damage — RAW the single biggest
    EB damage boost. Applied per-beam (it rides the single-beam
    action, so the multiattack's N beams each get it).

    When `repelling=True` (the Repelling Blast invocation, PR #106),
    each beam that hits pushes the target up to 10 ft straight away
    via the forced_movement primitive, gated on hit. Like Agonizing,
    it rides the single-beam action so every beam of the multiattack
    wrapper gets it. Both invocations compose: a Warlock with both
    deals CHA-boosted damage AND knockback per beam.
    """
    cha_mod = ability_modifier(ability_scores["cha"]["score"])
    attack_bonus = cha_mod + proficiency_bonus
    # PR #103: Agonizing Blast adds CHA mod to EACH beam's damage.
    damage_mod = cha_mod if agonizing else 0
    suffixes = []
    if agonizing:
        suffixes.append("Agonizing")
    if repelling:
        suffixes.append("Repelling")
    name = ("Eldritch Blast ({})".format(", ".join(suffixes))
              if suffixes else "Eldritch Blast")
    pipeline_steps = [
        {"primitive": "attack_roll",
          "params": {"kind": "ranged", "ability": "cha",
                      "bonus": attack_bonus, "range_ft": 120}},
        {"primitive": "damage",
          "params": {"dice": "1d10", "modifier": damage_mod,
                      "type": "force"},
          "when": {"condition": "combat.attack_state == hit"}},
    ]
    if repelling:
        # PR #106: push the target 10 ft away on a hit. Each beam can
        # push independently (RAW per-beam interpretation).
        pipeline_steps.append(
            {"primitive": "forced_movement",
              "params": {"distance_ft": 10},
              "when": {"condition": "combat.attack_state == hit"}})
    beam = {
        "id": "a_eldritch_blast",
        "name": name,
        "type": "weapon_attack",
        "slot": "action",
        "spell_slot_level": 0,        # cantrip — consumes no slot
        "pipeline": pipeline_steps,
    }
    out = [beam]
    beams = _eldritch_blast_beams_at_level(level)
    if beams > 1:
        out.append({
            "id": "a_eldritch_blast_beams",
            "name": f"Eldritch Blast ({beams} beams)",
            "type": "multiattack",
            "spell_slot_level": 0,
            "count": beams,
            "sub_actions": ["a_eldritch_blast"] * beams,
        })
    return out


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


def _derive_class_spell_slots(class_def: dict, level: int) -> dict:
    """Return the per-level spell slot dict declared by the class table
    at this level, or {} if no `spell_slots` field is present (PR #73).

    Walks `_class_resources_at_level` and pulls the `spell_slots`
    sub-dict (already a `{level: count}` shape per the c_paladin YAML
    convention). Caller (cli._build_actor) reads this as a fallback
    when actor_spec doesn't declare its own slots — fixtures may
    still override for "wounded Paladin with no slots left" scenarios.
    """
    resources = _class_resources_at_level(class_def, level)
    raw = resources.get("spell_slots") or {}
    # Normalize keys to int (YAML loaders may surface them as strings)
    return {int(k): int(v) for k, v in raw.items()}


def _short_class_name(class_id: str) -> str:
    """Strip the `c_` prefix from a class id (e.g. `c_barbarian` →
    `barbarian`). Used by the template.levels stamp so primitives that
    look up class level via the `actor.<class>_level` convention can
    find it."""
    if class_id and class_id.startswith("c_"):
        return class_id[len("c_"):]
    return class_id


def _build_rage_action() -> dict:
    """RAW (PHB 2024): Bonus Action, expend one rage charge to enter
    Rage. Pipeline calls the `rage_start` primitive, which flips the
    actor's rage state + stamps the level-appropriate damage bonus.

    Marked signature so the bonus-slot gate fires it eagerly when
    charges are available — Barbarians want to rage as early as
    possible in a fight (rage is the class's identity ability).
    """
    return {
        "id": "a_rage",
        "name": "Rage",
        # Type=defensive_buff routes through the candidate generator's
        # self-targeted-defensive-buff path (extended in PR #71's
        # `is_self_targeted_defensive_buff` to detect rage_start), and
        # through `defensive_ehp_defensive_buff` scoring (which has a
        # rage-specific branch via `_score_rage_entry`).
        "type": "defensive_buff",
        "slot": "bonus_action",
        "feature_use": "rage_uses_remaining",
        "is_signature": True,
        "pipeline": [
            {"primitive": "rage_start", "params": {}},
        ],
    }


def _build_cunning_action_actions() -> list[dict]:
    """Generate the three Cunning Action BA variants (PR #74).

    All three are slot=bonus_action. The mode-specific runtime
    behavior is dispatched in pipeline.execute via the action type:
      - dash: pipeline-only, the `dash` primitive sets
        `actor.dashed_this_turn` + clears `moved_this_turn`. The
        runner schedules a post-BA second-move pass when this
        flag is set.
      - disengage: type=disengage, pipeline.execute sets
        `actor.disengaging=True` (PR #26).
      - hide: type=hide, _execute_hide runs the DEX (Stealth) check
        and applies co_invisible on success (PR #48).

    `is_signature: false` — the bonus-slot gate's lower
    `tactical_bonus` threshold applies (vs. the higher
    `signature_bonus` for must-fire actions). CA modes are
    situational: Hide only when obscurement allows, Disengage only
    when adjacent enemies threaten OAs, Dash only when distance
    matters. The AI's existing scoring for hide/disengage/dash
    candidate kinds handles "when is this worth doing."
    """
    return [
        {
            "id": "a_cunning_action_dash",
            "name": "Cunning Action: Dash",
            # type=defensive_buff is intentional — Dash is a self-
            # targeted utility action. The pipeline routes
            # defensive_buff candidates through is_self_targeted_*
            # dedup (PR #71 added rage_start; we add dash here in
            # `is_self_targeted_defensive_buff`).
            "type": "defensive_buff",
            "slot": "bonus_action",
            "is_signature": False,
            "pipeline": [
                {"primitive": "dash", "params": {}},
            ],
        },
        {
            "id": "a_cunning_action_disengage",
            "name": "Cunning Action: Disengage",
            "type": "disengage",
            "slot": "bonus_action",
            "is_signature": False,
            # Disengage has no pipeline — pipeline.execute handles
            # the type=disengage branch by setting actor.disengaging.
            "pipeline": [],
        },
        {
            "id": "a_cunning_action_hide",
            "name": "Cunning Action: Hide",
            "type": "hide",
            "slot": "bonus_action",
            "is_signature": False,
            # Hide has no pipeline either — _execute_hide is the
            # entry point invoked by pipeline.execute on type=hide.
            "pipeline": [],
        },
    ]


def _build_steady_aim_action() -> dict:
    """RAW (PHB 2024) Rogue Steady Aim (PR #80): Bonus Action that
    grants advantage on the actor's next attack roll this turn and
    sets speed to 0 for the rest of the turn. Requires that the
    actor has NOT moved this turn (gated at candidate-emission
    time via `requires_no_movement` — checked by the pipeline's
    candidate generator).

    Marked `is_signature: False` — Steady Aim is highly tactical
    (only valuable when the Rogue has SA dice ready AND no allies
    adjacent to enable the SA condition naturally). The
    bonus-slot gate's `tactical_bonus` threshold gates how often
    the AI takes it.
    """
    return {
        "id": "a_steady_aim",
        "name": "Steady Aim",
        # type=defensive_buff routes through the candidate
        # generator's self-targeted dedup (extended in PR #80's
        # is_self_targeted_defensive_buff to recognize steady_aim).
        "type": "defensive_buff",
        "slot": "bonus_action",
        "is_signature": False,
        # PR #80: requires-no-movement gate. The pipeline filter
        # skips candidates with this flag when the actor has
        # already moved this turn (actor.moved_this_turn == True).
        "requires_no_movement": True,
        "pipeline": [
            {"primitive": "steady_aim", "params": {}},
        ],
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
                          fighting_style: str | None = None,
                          off_hand: bool = False) -> dict:
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
      light: bool — if True, weapon qualifies for off-hand attacks
        (PR #53, RAW 2024 Light weapon property)

    Fighting Style application:
      - Dueling: +2 damage on one-handed melee weapons
      - Archery: +2 attack on ranged weapons
      - Great Weapon Fighting (PR #49): damage_die_floor=3 on two-handed
        melee weapons. RAW 2024: any 1 or 2 rolled on a weapon's damage
        die is treated as a 3. Implemented via the `damage_die_floor`
        param on the damage primitive (clamps each individual die roll).
        Versatile weapons wielded two-handed are deferred until weapon-
        grip state is modeled — for now `two_handed: true` is the gate.
      - Two-Weapon Fighting (PR #53): when off_hand=True, the off-hand
        attack adds the ability modifier to damage (RAW default is no
        ability mod on off-hand). Without TWF, off-hand damage_mod = 0
        unless ability mod is negative (RAW: negative mods still apply).

    off_hand=True changes the returned action:
      - slot: bonus_action (vs. default action)
      - damage modifier: 0 (or negative ability mod), unless TWF style
      - Dueling's +2 damage does NOT apply (Dueling requires "no other
        weapons" per RAW, which dual-wielding violates)
      - id is suffixed `_offhand` to differentiate from a main-hand
        action that might use the same weapon spec
    """
    attack_ability = weapon.get("attack_ability", "str")
    ability_mod = ability_modifier(
        ability_scores[attack_ability]["score"]
    )
    attack_bonus = ability_mod + proficiency_bonus

    is_ranged = "range_ft" in weapon
    is_two_handed = bool(weapon.get("two_handed", False))
    is_light = bool(weapon.get("light", False))

    # PR #53: off-hand damage modifier (RAW default = 0 unless negative).
    if off_hand:
        # Apply ability mod only if Two-Weapon Fighting style is taken,
        # OR if the mod is negative (RAW: negative mods always apply).
        if fighting_style == "two_weapon_fighting" or ability_mod < 0:
            damage_mod = ability_mod + int(weapon.get("damage_modifier", 0))
        else:
            damage_mod = int(weapon.get("damage_modifier", 0))
    else:
        damage_mod = ability_mod + int(weapon.get("damage_modifier", 0))

    # PR #38: Fighting Style passive bonuses baked in at build time
    if fighting_style == "archery" and is_ranged:
        attack_bonus += 2
    if (fighting_style == "dueling"
            and not is_ranged and not is_two_handed
            and not off_hand):
        # RAW Dueling: "no other weapons" — dual-wielders don't qualify
        # for the +2. Pinned in tests/test_two_weapon_fighting.py.
        damage_mod += 2

    # PR #49: Great Weapon Fighting — damage die floor on 2H melee.
    damage_die_floor = 0
    if (fighting_style == "great_weapon_fighting"
            and not is_ranged and is_two_handed):
        damage_die_floor = 3

    attack_params: dict = {
        "kind": "ranged" if is_ranged else "melee",
        "bonus": attack_bonus,
        # PR #71: ability_used drives Rage's STR-melee damage-bonus
        # gate; PR #72 also reads it for telemetry.
        "ability": attack_ability,
    }
    if is_ranged:
        attack_params["range_ft"] = int(weapon["range_ft"])
    else:
        attack_params["reach_ft"] = int(weapon.get("reach_ft", 5))
    # PR #72: stamp the Finesse property so the Sneak Attack
    # qualification gate can recognize finesse-melee weapons. RAW:
    # Sneak Attack triggers on Finesse OR Ranged weapons. Ranged is
    # already encoded via `kind == "ranged"`; finesse needs an
    # explicit bool because melee + STR-ability + finesse weapons
    # (rapier wielded by a STR build) still qualify per RAW.
    if weapon.get("finesse"):
        attack_params["finesse"] = True

    # PR #54: Weapon Mastery — if the weapon spec declares `mastery:
    # <id>`, bake a self-contained mastery sub-dict into the
    # attack_roll params. The runtime _attack_roll calls
    # weapon_masteries.apply_mastery_effects which dispatches based
    # on the id. ability_mod / damage_type / save_dc are computed
    # here so the runtime helper doesn't need to re-read the actor
    # template.
    raw_mastery = weapon.get("mastery")
    if raw_mastery:
        from engine.core.weapon_masteries import validate_mastery
        mastery_id = validate_mastery(raw_mastery)
        # PR #65: Heavy gate on Cleave + Graze. RAW restricts both
        # to Heavy melee weapons. Validate at build time so authors
        # catch the mismatch when loading the fixture; runtime
        # dispatch trusts the gate.
        if mastery_id in ("cleave", "graze"):
            if not weapon.get("heavy"):
                raise ValueError(
                    f"Weapon mastery {mastery_id!r} requires a Heavy "
                    f"melee weapon (RAW 2024). Weapon "
                    f"{weapon.get('id', '<unnamed>')!r} is not "
                    f"declared `heavy: true`. Add `heavy: true` to "
                    f"the weapon spec, OR remove the mastery."
                )
            if "range_ft" in weapon:
                raise ValueError(
                    f"Weapon mastery {mastery_id!r} requires a Heavy "
                    f"MELEE weapon (not ranged). Weapon "
                    f"{weapon.get('id', '<unnamed>')!r} has range_ft "
                    f"and so is ranged."
                )
        # Topple save DC = 8 + ability_mod + PB (RAW). For non-Topple
        # masteries this value is unused, but we always bake it for
        # uniformity.
        save_dc = 8 + ability_mod + int(proficiency_bonus)
        # PR #66: bake the weapon's reach for masteries that need it
        # (Cleave's "within your reach" check on the second target).
        # Melee weapons use reach_ft (default 5); ranged weapons don't
        # use this — Cleave + Graze are gated to melee at build time.
        reach_for_mastery = int(weapon.get("reach_ft", 5))
        attack_params["mastery"] = {
            "id": mastery_id,
            "ability_mod": ability_mod,
            "damage_type": weapon.get("damage_type", "untyped"),
            "save_dc": save_dc,
            "reach_ft": reach_for_mastery,
        }

    damage_params: dict = {
        "dice": weapon.get("damage_dice", "1d4"),
        "modifier": damage_mod,
        "type": weapon.get("damage_type", "bludgeoning"),
    }
    if damage_die_floor > 0:
        damage_params["damage_die_floor"] = damage_die_floor

    base_id = (weapon.get("id")
                  or f"a_{weapon.get('name', 'weapon').lower().replace(' ', '_')}")
    action_id = f"{base_id}_offhand" if off_hand else base_id
    action_name = weapon.get("name", "Weapon")
    if off_hand:
        action_name = f"{action_name} (Off-Hand)"

    action: dict = {
        "id": action_id,
        "name": action_name,
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll", "params": attack_params},
            {"primitive": "damage",
              "params": damage_params,
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }
    if off_hand:
        # RAW: off-hand attack is a Bonus Action.
        action["slot"] = "bonus_action"
    return action
