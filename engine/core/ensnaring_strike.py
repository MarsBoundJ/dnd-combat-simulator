"""Ensnaring Strike — Ranger 1st-level smite-shape spell (PR #110).

RAW (PHB 2024):

  *Bonus Action, V, Self, Concentration up to 1 minute. The next time
  you hit a creature with a weapon attack before this spell ends, a
  writhing mass of thorny vines appears at the point of impact, and the
  target must succeed on a Strength saving throw or be Restrained by
  the magical vines until the spell ends. A Large or larger creature
  has advantage on this saving throw. While Restrained, the creature
  takes 1d6 Piercing damage at the start of each of its turns. A
  creature Restrained by the vines can use an action to make a Strength
  check against your spell save DC; on a success, it frees itself.*

  *Higher Levels: damage increases by 1d6 per slot above 1st.*

**Engine model.** Structural twin of Searing Smite (engine.core.
searing_smite) — the "next weapon hit arms a one-shot rider" pattern,
kept as a parallel module (rather than merged) so each spell has its
own marker primitive, named_effect, and event log, and so a future
generalization of the smite-rider family can refactor both at once.

Differences from Searing Smite:
  - Triggers on ANY weapon hit (melee OR ranged), not melee-only.
  - NO bonus damage on the empowering attack (the spell deals no
    direct hit damage; the per-turn piercing is the only damage).
  - STR save (not CON); on fail applies co_ensnared (Restrained via
    inheritance + 1d6 piercing per turn).

Phases:
  1. **Arm** — the cast registers a marker modifier on the caster
     (primitive: `ensnaring_strike_armed`, lifetime until short rest,
     source tagged with caster_id + action_id for concentration
     scrub). Pipeline step: `ensnaring_strike_arm` primitive.
  2. **Trigger** — on the caster's next weapon hit,
     `try_apply_ensnaring_strike_followup` (called from `_damage`):
       - Fires a STR forced_save against the target (cached spell DC)
       - On fail: applies co_ensnared
       - Clears the marker (one-shot per cast)
  3. **Ensnare** — runner._resolve_recurring_damage fires the 1d6
     piercing tick at each ensnared creature's turn-start; co_restrained
     effects (speed 0, etc.) apply via inheritance. Ends when the
     caster's concentration drops.

**v1 deferred:**
  - STR-check-to-break-free as the target's own action (RAW target-side
    concentration break). v1 ends the ensnare only when concentration
    drops. Shared deferral with co_ignited's save-to-end.
  - Large-or-bigger creatures' advantage on the initial STR save. The
    forced_save path doesn't yet thread size-based save advantage;
    tracked here rather than silently dropped. (Most ensnare targets
    are Medium, so v1 impact is small.)
  - Upcast +1d6 per slot above 1st on the per-turn piercing. v1 ticks
    a flat 1d6 (co_ensnared's recurring_damage); upcast scaling of the
    tick mirrors the same gap Searing Smite documents on its burn.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState


# Marker modifier primitive name (distinct from the spell-action id and
# from Searing Smite's marker).
ENSNARING_STRIKE_ARMED_PRIMITIVE = "ensnaring_strike_armed"


def register_armed(caster: Actor, spell_save_dc: int, action_id: str,
                     state: CombatState) -> None:
    """Register the one-shot armed marker on the caster's
    active_modifiers. Called from the cast pipeline (via the
    `_ensnaring_strike_arm` primitive).

    `spell_save_dc`: the Ranger's spell save DC (8 + PB + WIS mod).
    """
    entry = {
        "primitive": ENSNARING_STRIKE_ARMED_PRIMITIVE,
        "params": {"dc": int(spell_save_dc)},
        "lifetime": "until_short_rest",
        "source": {
            "type": "spell",
            "id": action_id,
            "action_id": action_id,
            "caster_id": caster.id,
            "named_effect": "ensnaring_strike",
        },
        "applied_at_round": state.round,
        "owner_id": caster.id,
    }
    caster.active_modifiers.append(entry)
    state.event_log.append({
        "event": "ensnaring_strike_armed",
        "caster": caster.id,
        "dc": int(spell_save_dc),
    })


def find_armed_entry(caster: Actor) -> dict | None:
    """Return the caster's active ensnaring_strike_armed modifier, or
    None if not armed."""
    for mod in caster.active_modifiers:
        if mod.get("primitive") == ENSNARING_STRIKE_ARMED_PRIMITIVE:
            return mod
    return None


def clear_armed(caster: Actor) -> None:
    """Remove the ensnaring_strike_armed marker after the rider fires
    (one-shot per cast; concentration continues for the ensnare)."""
    caster.active_modifiers = [
        m for m in caster.active_modifiers
        if m.get("primitive") != ENSNARING_STRIKE_ARMED_PRIMITIVE
    ]


def try_apply_ensnaring_strike_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """If the attacker is armed with Ensnaring Strike AND this is a
    qualifying weapon hit (melee OR ranged), fire the rider:
      - Fire a STR forced_save on the target (cached spell save DC)
      - On fail: apply co_ensnared (Restrained + 1d6 piercing/turn)
      - Clear the armed marker (one-shot)

    Returns 0 always — Ensnaring Strike adds NO direct damage to the
    empowering attack (unlike Searing Smite). The int return keeps the
    _damage call site uniform with the searing rider.
    """
    armed = find_armed_entry(attacker)
    if armed is None:
        return 0
    params = attack_params or {}
    # Any weapon attack qualifies (melee or ranged) — RAW.
    if params.get("kind", "melee") not in ("melee", "ranged"):
        return 0

    dc = int((armed.get("params") or {}).get("dc", 10))
    state.event_log.append({
        "event": "ensnaring_strike_triggered",
        "attacker": attacker.id, "target": target.id, "dc": dc,
    })

    # Fire the STR save. On fail, apply co_ensnared. Stamp the spell's
    # action id onto current_attack so co_ensnared's recurring_damage
    # entry records source_action_id (used by end_concentration scrub).
    from engine.primitives import _forced_save
    saved_action = state.current_attack.get("action")
    spell_action_id = (armed.get("source") or {}).get(
        "action_id", "a_ensnaring_strike")
    state.current_attack["action"] = {
        "id": spell_action_id,
        "spell_slot_level": 1,
    }
    try:
        _forced_save({
            "ability": "strength",
            "dc": dc,
            "affected": "current_target",
            "on_fail": [
                {"primitive": "apply_condition",
                  "params": {"condition_id": "co_ensnared",
                              "duration": "until_spell_ends"}},
            ],
            "on_success": [],
        }, state, _NoOpBus())
    finally:
        state.current_attack["action"] = saved_action

    clear_armed(attacker)
    return 0


class _NoOpBus:
    """Minimal event-bus stand-in for the forced_save invocation from
    within try_apply_ensnaring_strike_followup (mirrors
    searing_smite._NoOpBus)."""

    def emit(self, *args, **kwargs) -> None:
        return None
