"""Behavior profile resolution — reads dial presets + archetype from
the actor's template.

Per pillars-reconciliation.md §4 the full resolution chain is:

  archetype defaults → faction profile → instance override
        ↓ (static layers above)
  current_form replacement (if active)
        ↓
  runtime_overrides (Frightened / Dominate / Confusion)
        ↓
  effective profile

**v1 simplification:** this module reads directly from
`actor.template.behavior_profile`. Faction profiles, instance overrides,
form transitions, and runtime overrides are NOT yet resolved here
(deferred to follow-on PRs). Defaults are sensible fallbacks per dial
when the template doesn't specify.
"""
from __future__ import annotations

from engine.core.state import Actor


# Default preset per dial when not specified on the actor template.
# These default to the most conservative / mechanically-skeleton behavior.
_DEFAULT_TARGETING = "closest_enemy"
_DEFAULT_ABILITY_SELECTION = "default"
_DEFAULT_ACTION_ECONOMY = "average"
_DEFAULT_RETREAT = "default"

# Archetype → default presets per dial. Read when actor specifies an
# archetype but not individual dial presets. Sourced from
# `pillars-reconciliation.md` §3 + §5 archetype tables.
_ARCHETYPE_DEFAULTS: dict[str, dict[str, str]] = {
    "mindless_aggressor": {
        "targeting": "closest_enemy",
        "ability_selection": "mindless",
        "retreat": "ftd",
        "action_economy": "reactive_only",
    },
    "cowardly_skirmisher": {
        "targeting": "weakest_target",
        "ability_selection": "default",
        "retreat": "cowardly",
        "action_economy": "casual",
    },
    "pack_hunter": {
        "targeting": "most_dangerous",
        "ability_selection": "default",
        "retreat": "default",
        "action_economy": "average",
    },
    "apex_predator": {
        "targeting": "caster_first",
        "ability_selection": "tactical",
        "retreat": "resolute",
        "action_economy": "skilled",
    },
    "territorial_beast": {
        "targeting": "closest_enemy",
        "ability_selection": "instinctive",
        "retreat": "default",
        "action_economy": "average",
    },
    "berserker_fanatic": {
        "targeting": "most_dangerous",
        "ability_selection": "default",
        "retreat": "ftd",
        "action_economy": "skilled",
    },
}


def resolve_archetype(actor: Actor) -> str | None:
    """Return the actor's archetype label, or None if unspecified."""
    bp = (actor.template.get("behavior_profile") or {})
    return bp.get("archetype")


def resolve_targeting_preset(actor: Actor) -> str:
    """Resolve the actor's targeting preset.

    Order:
      1. explicit `behavior_profile.presets.targeting`
      2. archetype default (from _ARCHETYPE_DEFAULTS)
      3. _DEFAULT_TARGETING (closest_enemy)
    """
    return _resolve_dial(actor, "targeting", _DEFAULT_TARGETING)


def resolve_ability_selection_preset(actor: Actor) -> str:
    return _resolve_dial(actor, "ability_selection", _DEFAULT_ABILITY_SELECTION)


def resolve_action_economy_preset(actor: Actor) -> str:
    return _resolve_dial(actor, "action_economy", _DEFAULT_ACTION_ECONOMY)


def resolve_retreat_preset(actor: Actor) -> str:
    return _resolve_dial(actor, "retreat", _DEFAULT_RETREAT)


def _resolve_dial(actor: Actor, dial_name: str, fallback: str) -> str:
    """Walk the resolution chain for a single dial."""
    bp = (actor.template.get("behavior_profile") or {})

    # 1. Explicit preset on the actor template
    presets = bp.get("presets") or {}
    if dial_name in presets and presets[dial_name]:
        return presets[dial_name]

    # 2. Archetype default
    archetype = bp.get("archetype")
    if archetype and archetype in _ARCHETYPE_DEFAULTS:
        archetype_defaults = _ARCHETYPE_DEFAULTS[archetype]
        if dial_name in archetype_defaults:
            return archetype_defaults[dial_name]

    # 3. Hard-coded fallback
    return fallback
