"""Skill checks (PR #51).

Centralizes the 5e 2024 skill list, the skill→ability mapping, and the
helpers that compute a skill modifier for a given Actor. Two sources of
truth, queried in order:

  1. **Template-listed skill bonus** (`template.skills.<name>: int`).
     This is the SRD-monsters shape — the modifier is already computed
     (ability + proficiency + any racial bonuses). Just return it.
  2. **Computed from ability + PB** if the actor is proficient in the
     skill. PC schemas declare `skill_proficiencies: [stealth, ...]`,
     which is baked onto the template as
     `template.skill_proficiencies` for retrieval here.

If neither source claims the skill, the actor is not proficient: return
just the ability modifier.

The helpers intentionally take `Actor` rather than a raw template dict
because runtime conditions (e.g., a Bardic Inspiration die granting
expertise temporarily) will eventually need to layer on top. v1 is
ability+proficiency only.
"""
from __future__ import annotations

from engine.core.state import Actor, ability_modifier


# ============================================================================
# Skill → ability map (5e 2024 PHB)
# ============================================================================

SKILL_TO_ABILITY: dict[str, str] = {
    # Strength
    "athletics": "str",
    # Dexterity
    "acrobatics": "dex",
    "sleight_of_hand": "dex",
    "stealth": "dex",
    # Intelligence
    "arcana": "int",
    "history": "int",
    "investigation": "int",
    "nature": "int",
    "religion": "int",
    # Wisdom
    "animal_handling": "wis",
    "insight": "wis",
    "medicine": "wis",
    "perception": "wis",
    "survival": "wis",
    # Charisma
    "deception": "cha",
    "intimidation": "cha",
    "performance": "cha",
    "persuasion": "cha",
}

KNOWN_SKILLS: frozenset[str] = frozenset(SKILL_TO_ABILITY.keys())


def normalize_skill_name(name: str) -> str:
    """Lowercase + underscore form. Accepts 'Stealth' / 'stealth' /
    'sleight of hand' / 'sleight_of_hand' uniformly.
    """
    return name.strip().lower().replace(" ", "_")


def validate_skill_name(name: str) -> str:
    """Return the normalized form if it's a known skill; raise otherwise."""
    n = normalize_skill_name(name)
    if n not in KNOWN_SKILLS:
        raise ValueError(
            f"Unknown skill {name!r}. Known: {sorted(KNOWN_SKILLS)}."
        )
    return n


# ============================================================================
# Modifier computation
# ============================================================================

def has_skill_proficiency(actor: Actor, skill: str) -> bool:
    """True if the actor is proficient in `skill`. Reads
    `template.skill_proficiencies` (PC schema baked it there) OR
    treats `template.skills.<skill>` as implicit proficiency for
    monsters that list the skill directly.
    """
    n = normalize_skill_name(skill)
    template = actor.template or {}
    listed = template.get("skill_proficiencies") or []
    if n in {normalize_skill_name(s) for s in listed}:
        return True
    skills_dict = template.get("skills") or {}
    if n in {normalize_skill_name(s) for s in skills_dict.keys()}:
        return True
    return False


def has_skill_expertise(actor: Actor, skill: str) -> bool:
    """True if the actor has Expertise in `skill` (PR #62).

    Reads `template.skill_expertise` (PC schema bakes it there from
    the pc_spec's `skill_expertise:` field). Expertise stacks ON
    TOP of proficiency — both are required for the 2×PB bonus
    (Expertise without proficiency is impossible per RAW; validation
    in pc_schema enforces this).

    For monsters with the `skills:` dict, Expertise is already baked
    into the listed bonus (the monster's stat block authors handled
    the doubling). Monster expertise isn't separately tracked here.
    """
    n = normalize_skill_name(skill)
    template = actor.template or {}
    listed = template.get("skill_expertise") or []
    return n in {normalize_skill_name(s) for s in listed}


def _skill_magic_bonus(actor: Actor, skill: str) -> int:
    """Flat magic-item bonus to `skill` (PR #62).

    Reads `template.skill_bonuses` — a dict like
    `{stealth: 5, perception: 2}` where each value is an integer
    flat bonus added to skill checks. Magic items that affect
    specific skills (Cloak of Elvenkind, Gloves of Thievery, Boots
    of Elvenkind, Eyes of the Eagle, etc.) populate this dict.

    Returns 0 if no bonus declared for this skill. For monsters
    using `template.skills.<name>`, magic item bonuses are
    typically already baked into the listed total — this helper
    doesn't apply on top of monster-listed bonuses.
    """
    n = normalize_skill_name(skill)
    template = actor.template or {}
    bonuses = template.get("skill_bonuses") or {}
    for raw_name, value in bonuses.items():
        if normalize_skill_name(raw_name) == n:
            return int(value)
    return 0


def skill_modifier(actor: Actor, skill: str) -> int:
    """Total modifier for `skill` on `actor`.

    Resolution order:
      1. If `template.skills.<skill>` is an explicit number, use it
         as the base. Magic item bonus (`template.skill_bonuses`)
         is added on top — RAW item bonuses stack with the monster
         stat block's listed total.
      2. Otherwise compute ability_mod + (PB×expertise_multiplier
         if proficient) + magic item bonus.

    Expertise multiplier (PR #62):
      - Proficient AND not in skill_expertise → 1× PB
      - Proficient AND in skill_expertise → 2× PB
      - Not proficient → no PB added (Expertise without proficiency
        is impossible per RAW; pc_schema validates this gate)

    Unknown skills raise — keeps typos from silently returning 0.
    """
    n = validate_skill_name(skill)
    template = actor.template or {}

    # 1. Explicit listed bonus (case-insensitive name match)
    skills_dict = template.get("skills") or {}
    for raw_name, bonus in skills_dict.items():
        if normalize_skill_name(raw_name) == n:
            # Add any magic-item bonus on top (rare for monsters but
            # supported for completeness).
            return int(bonus) + _skill_magic_bonus(actor, n)

    # 2. Compute from ability + (PB × expertise multiplier)
    ability = SKILL_TO_ABILITY[n]
    ability_block = (actor.abilities or {}).get(ability) or {}
    ability_score = int(ability_block.get("score", 10))
    mod = ability_modifier(ability_score)

    if has_skill_proficiency(actor, n):
        # Pull proficiency bonus from the template's cr block (same
        # field _execute_hide and other systems consult).
        pb = int((template.get("cr") or {}).get("proficiency_bonus", 2))
        if has_skill_expertise(actor, n):
            # PR #62: Expertise doubles PB. RAW: "your Proficiency
            # Bonus is doubled if it isn't already." We don't currently
            # track "already doubled" sources (Jack of All Trades,
            # Reliable Talent variants); v1 always doubles when
            # expertise is set.
            mod += 2 * pb
        else:
            mod += pb

    # Magic item bonus (always added, regardless of proficiency)
    mod += _skill_magic_bonus(actor, n)

    return mod
