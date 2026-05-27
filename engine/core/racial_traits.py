"""Racial trait registry + integration helpers (PR #75).

This module owns the mapping from "trait id" to "what does it do" for
the SRD CC v5.2.1 racial traits the engine wires today. Traits are
declared on race YAMLs (`schema/content/races/*.yaml`) as a flat list
of trait ids; pc_schema stamps them onto `template.racial_traits`,
and cli loads that onto `Actor.racial_traits`. The integration sites
(`_attack_roll`, `_forced_save`, `query_save_modifiers`) consult this
list at runtime to decide whether a trait fires.

**v1 traits (SRD CC v5.2.1 — Dwarf / Elf / Halfling / Human only):**

  - `t_lucky` (Halfling): reroll natural 1 on d20 attack rolls,
    ability checks, and saving throws (RAW PHB 2024). Wired at
    _attack_roll + _forced_save sites; ability check sites
    (_execute_hide / _execute_search / etc.) are listed as deferred
    follow-ups.

  - `t_brave` (Halfling): advantage on saving throws to avoid or end
    the Frightened condition. Wired via `racial_save_advantage_for`
    which inspects the in-flight `state.current_save_context` for
    `co_frightened` in the on_fail apply_condition list.

  - `t_fey_ancestry` (Elf): advantage on saving throws to avoid or
    end the Charmed condition. Same shape as Brave but keyed off
    `co_charmed`.

  - `t_dwarven_resilience` (Dwarf): advantage on saves vs Poisoned
    AND resistance to poison damage. The damage resistance half is
    baked onto the template's `damage_resistances` list at PC-build
    time (cli + _damage handle it via the existing template-side
    resistance path). The save-advantage half is wired via
    `racial_save_advantage_for` keyed off `co_poisoned`.

  - `t_skillful` (Human): one extra skill proficiency from any list.
    The fixture / pc_spec picks the specific skill via `extra_skill:`;
    pc_schema appends it to `skill_proficiencies` at build time.
    Purely build-time; no runtime trait check needed.

**Deferred traits** (registered as flags but mechanical effect not
yet wired):
  - Elf Trance: 4-hour long rest (deferred — minimal combat impact)
  - Halfling Nimbleness: move through larger creatures' spaces
    (deferred — needs movement-aware engine support)
  - Dwarf Stonecunning / Toolkit Proficiency (lore/utility)
  - Elf Keen Senses / Halfling Lucky (general-d20 sites beyond
    attack/save)

**Save-source context infrastructure:**

When a `forced_save` (or recurring save) fires, the engine stashes
the save's `on_fail` block into `state.current_save_context` BEFORE
calling `query_save_modifiers`. The query inspects the context for
condition-applying primitives that match racial trait flags. This
keeps trait knowledge out of the primitives themselves — they just
publish "what happens on fail," and the query side decides whether
any of the target's traits care.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState


# ============================================================================
# Trait → triggering condition map
# ============================================================================

# For each "save advantage" racial trait, the condition id whose
# application on-fail triggers the advantage. New traits go here.
SAVE_CONDITION_TRIGGERS: dict[str, str] = {
    "t_brave":             "co_frightened",
    "t_fey_ancestry":      "co_charmed",
    "t_dwarven_resilience": "co_poisoned",
}


# ============================================================================
# Predicates
# ============================================================================

def has_racial_trait(actor: Actor, trait_id: str) -> bool:
    """True iff `actor` has the given trait. Accepts Actor objects
    with a `racial_traits` list field; returns False for actors
    without the field (e.g., monsters not built from a PC race).

    Trait ids are normalized to lowercase for comparison.
    """
    traits = getattr(actor, "racial_traits", None) or []
    target = trait_id.lower()
    return target in {t.lower() for t in traits}


def racial_save_advantage_for(actor: Actor,
                                 state: CombatState) -> str | None:
    """Return the racial trait id granting advantage on the current
    in-flight save, or None if no trait fires.

    Reads `state.current_save_context` — a dict set by `_forced_save`
    (and recurring-save resolution) BEFORE calling
    `query_save_modifiers`. The context advertises which conditions
    the save would apply on failure.

    Expected context shape:
      {
        "applied_conditions_on_fail": ["co_frightened", "co_poisoned", ...]
      }

    For each trait in `SAVE_CONDITION_TRIGGERS`, checks whether the
    target has the trait AND whether the triggering condition appears
    in the on_fail set. Returns the FIRST matching trait id (multiple
    matches are vanishingly rare; the first one's source is added to
    the SaveModifierResult.sources for telemetry — having all of them
    isn't necessary for the advantage outcome).
    """
    ctx = getattr(state, "current_save_context", None)
    if not ctx:
        return None
    on_fail_conditions = set(ctx.get("applied_conditions_on_fail") or [])
    for trait_id, triggering_condition in SAVE_CONDITION_TRIGGERS.items():
        if triggering_condition in on_fail_conditions \
                and has_racial_trait(actor, trait_id):
            return trait_id
    return None


# ============================================================================
# Lucky reroll helper
# ============================================================================

def lucky_d20(rng: random.Random, raw_d20: int,
                actor: Actor) -> tuple[int, bool]:
    """Apply Halfling Lucky to a d20 roll.

    RAW PHB 2024: "When you roll a 1 on the d20 for an attack roll,
    an ability check, or a saving throw, you can reroll the die and
    must use the new roll."

    Returns (final_d20, was_rerolled). When the actor doesn't have
    Lucky OR the original roll wasn't 1, returns (raw_d20, False).

    Callers pass the d20 they would use (the post-advantage /
    post-disadvantage chosen die — only one is rerolled per the RAW
    intent that Lucky fires on the die that "counts," not all dice
    rolled).
    """
    if raw_d20 != 1:
        return raw_d20, False
    if not has_racial_trait(actor, "t_lucky"):
        return raw_d20, False
    return rng.randint(1, 20), True


# ============================================================================
# Context helpers (for _forced_save / recurring_save callers)
# ============================================================================

def extract_apply_condition_ids(sub_primitives: list) -> list[str]:
    """Walk a list of sub-primitives (typically `on_fail` from a
    forced_save) and return all `apply_condition.condition_id` values.

    Used by `_forced_save` to build the
    `applied_conditions_on_fail` portion of
    `state.current_save_context`. Recursive into nested forced_save
    paths is not yet needed — RAW save chains for v1 don't nest.
    """
    out: list[str] = []
    for sub in sub_primitives or []:
        if not isinstance(sub, dict):
            continue
        if sub.get("primitive") != "apply_condition":
            continue
        params = sub.get("params") or {}
        cond_id = params.get("condition_id") or params.get("condition")
        if cond_id:
            out.append(str(cond_id))
    return out


def build_save_context(forced_save_params: dict) -> dict:
    """Convert a forced_save params dict into the save-context dict
    stashed onto state.current_save_context. The shape is intentionally
    flat so query_save_modifiers can read it cheaply.

    Recognized keys produced:
      - `applied_conditions_on_fail`: list of condition ids the save
        would apply on failure (drives Brave / Fey Ancestry /
        Dwarven Resilience save advantage).

    Future keys (placeholders, deferred):
      - `damage_types_on_fail`: list of damage types the save would
        deal on failure (could drive other resistance-on-save traits)
      - `damage_types_on_success`: same, half-damage branch
    """
    on_fail = forced_save_params.get("on_fail") or []
    return {
        "applied_conditions_on_fail": extract_apply_condition_ids(on_fail),
    }


def build_save_context_for_condition(condition_id: str) -> dict:
    """Same shape as `build_save_context` but for recurring-save
    resolution, where the save isn't "would apply X on fail" but
    rather "would END the existing X condition on success." For racial
    trait purposes the polarity is the same — the condition is the
    one being interacted with — so we treat both shapes identically:
    the actor with Brave gets advantage on saves against co_frightened
    whether the save is initial (avoid) or recurring (end)."""
    return {
        "applied_conditions_on_fail": [condition_id],
    }
