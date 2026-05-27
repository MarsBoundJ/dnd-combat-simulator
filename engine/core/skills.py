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


def skill_modifier(actor: Actor, skill: str) -> int:
    """Total modifier for `skill` on `actor`.

    Resolution order:
      1. If `template.skills.<skill>` is an explicit number, use it.
         (SRD-monster shape — the bonus already includes ability +
         proficiency + racial mods.)
      2. Otherwise compute ability_mod + (PB if proficient).

    Unknown skills raise — keeps typos from silently returning 0.
    """
    n = validate_skill_name(skill)
    template = actor.template or {}

    # 1. Explicit listed bonus (case-insensitive name match)
    skills_dict = template.get("skills") or {}
    for raw_name, bonus in skills_dict.items():
        if normalize_skill_name(raw_name) == n:
            return int(bonus)

    # 2. Compute from ability + PB
    ability = SKILL_TO_ABILITY[n]
    ability_block = (actor.abilities or {}).get(ability) or {}
    ability_score = int(ability_block.get("score", 10))
    mod = ability_modifier(ability_score)

    if has_skill_proficiency(actor, n):
        # Pull proficiency bonus from the template's cr block (same
        # field _execute_hide and other systems consult).
        pb = int((template.get("cr") or {}).get("proficiency_bonus", 2))
        mod += pb

    return mod
