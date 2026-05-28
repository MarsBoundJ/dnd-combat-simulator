"""Searing Smite — Paladin 1st-level smite spell (PR #89).

RAW (PHB 2024):

  *Bonus Action, V/S, Self, Concentration up to 1 minute. The next
  time you hit a creature with a Melee weapon during the spell's
  duration, your weapon flares with white-hot intensity. The attack
  deals an extra 1d6 fire damage to the target. Additionally, if the
  target is a creature, it must succeed on a Constitution saving
  throw or be Ignited.*

  *Ignited: takes 1d6 fire damage at the start of each of its turns.
  It can use an action to make another Constitution saving throw,
  ending the spell on itself on a success.*

  *Higher Levels: +1d6 fire damage on the empowering attack per slot
  above 1st (the per-turn burn does NOT scale per RAW 2024).*

**Engine model.** Two-phase spell:

  1. **Arming phase** — the cast registers a marker modifier on the
     caster (primitive: `searing_smite_armed`, lifetime until short
     rest, source tagged with caster_id + action_id for concentration
     scrub). Pipeline step: `searing_smite_arm` primitive.

  2. **Trigger phase** — on the caster's next melee weapon hit,
     `try_apply_searing_smite_followup` (called from `_damage`):
       - Adds 1d6 fire to the damage total (+1d6 per upcast slot
         level)
       - Fires a CON forced_save against the target
       - On fail: applies co_ignited (which has a recurring_damage
         effect dealing 1d6 fire at start of target's turn)
       - Clears the marker (one-shot per cast)

  3. **Burn phase** — runner._resolve_recurring_damage fires the
     1d6 fire tick at each Ignited creature's turn-start. Continues
     until the caster's concentration drops (end_concentration scrubs
     state.recurring_damage entries tied to caster + action).

**v1 deferred:**
  - Target's "use an action to save to end" (RAW Ignited save-to-end
    on the target's own turn). Needs candidate emission at the
    target's turn and AI scoring. Currently the burn ends only when
    concentration drops.
  - Typed bonus damage modeling — the +1d6 fire on the empowering
    attack is added as untyped damage on the existing damage step
    (same v1 gap as Divine Favor's +1d4 radiant). Means it doesn't
    interact with target fire resistance/vulnerability. Acceptable
    for v1; documented gap shared across Divine Favor / Searing
    Smite riders.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState


# Marker modifier primitive name. The cast registers an entry with
# this primitive on the caster's active_modifiers; the try_apply
# helper scans for it. Naming kept distinct from `searing_smite` to
# avoid collision with the spell-action-id.
SEARING_SMITE_ARMED_PRIMITIVE = "searing_smite_armed"


def register_armed(caster: Actor, slot_level: int,
                     spell_save_dc: int, action_id: str,
                     state: CombatState) -> None:
    """Register the one-shot armed marker on the caster's active_
    modifiers. Called from the cast pipeline (via the
    _searing_smite_arm primitive).

    `slot_level` (1-9): the slot the spell was cast with. Drives the
    upcast damage (1d6 base + 1d6 per level above 1st).
    `spell_save_dc`: the Paladin's spell save DC (8 + PB + CHA mod).
    """
    entry = {
        "primitive": SEARING_SMITE_ARMED_PRIMITIVE,
        "params": {
            "slot_level": int(slot_level),
            "dc": int(spell_save_dc),
        },
        "lifetime": "until_short_rest",
        "source": {
            "type": "spell",
            "id": action_id,
            "action_id": action_id,
            "caster_id": caster.id,
            "named_effect": "searing_smite",
        },
        "applied_at_round": state.round,
        "owner_id": caster.id,
    }
    caster.active_modifiers.append(entry)
    state.event_log.append({
        "event": "searing_smite_armed",
        "caster": caster.id,
        "slot_level": int(slot_level),
        "dc": int(spell_save_dc),
    })


def find_armed_entry(caster: Actor) -> dict | None:
    """Return the caster's active searing_smite_armed modifier entry,
    or None if not armed. Defensive: returns the FIRST entry if
    somehow multiple are present (shouldn't happen — cast is one-shot
    and re-cast replaces concentration → previous cleanup)."""
    for mod in caster.active_modifiers:
        if mod.get("primitive") == SEARING_SMITE_ARMED_PRIMITIVE:
            return mod
    return None


def clear_armed(caster: Actor) -> None:
    """Remove the searing_smite_armed marker after the rider fires.
    Called after try_apply_searing_smite_followup applies its damage
    + condition. Concentration on the spell continues for the burn
    duration; only the one-shot arming is consumed."""
    caster.active_modifiers = [
        m for m in caster.active_modifiers
        if m.get("primitive") != SEARING_SMITE_ARMED_PRIMITIVE
    ]


def try_apply_searing_smite_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """If the attacker is armed with Searing Smite AND this is a
    qualifying melee weapon hit, fire the rider:
      - Roll 1d6 fire (+ upcast per slot above 1st), double on crit
      - Fire CON forced_save on target (using cached spell save DC)
      - On fail: apply co_ignited condition (which registers the
        per-turn burn via recurring_damage)
      - Clear the armed marker (one-shot)

    Returns the bonus damage to add to the current attack's total.
    Returns 0 when the attacker isn't armed or the swing doesn't
    qualify (non-melee, non-weapon).
    """
    armed = find_armed_entry(attacker)
    if armed is None:
        return 0
    params = attack_params or {}
    if params.get("kind", "melee") != "melee":
        return 0

    armed_params = armed.get("params") or {}
    slot_level = int(armed_params.get("slot_level", 1))
    dc = int(armed_params.get("dc", 10))

    # Roll bonus damage: 1d6 base + 1d6 per slot above 1st
    # (RAW 2024: only the empowering attack scales with upcast;
    # the per-turn burn stays 1d6).
    dice_count = 1 + max(0, slot_level - 1)
    rolls_to_make = dice_count * (2 if is_crit else 1)
    bonus_damage = sum(rng.randint(1, 6) for _ in range(rolls_to_make))

    state.event_log.append({
        "event": "searing_smite_triggered",
        "attacker": attacker.id, "target": target.id,
        "slot_level": slot_level,
        "bonus_damage": bonus_damage,
        "is_crit": is_crit,
    })

    # Fire the CON save. On fail, apply co_ignited.
    # Done via primitives._forced_save invocation rather than direct
    # save math to keep the path uniform with other on-hit save
    # riders (Topple, Brutal Strike, etc.).
    from engine.primitives import _forced_save
    # Save target context: forced_save reads state.current_attack.target,
    # which is already correctly set by the caller (_damage).
    saved_action = state.current_attack.get("action")
    # Stamp the action's id onto current_attack so co_ignited's
    # recurring_damage entry can record source_action_id (used by
    # end_concentration scrub).
    spell_action_id = (armed.get("source") or {}).get("action_id",
                                                          "a_searing_smite")
    state.current_attack["action"] = {
        "id": spell_action_id,
        "spell_slot_level": slot_level,
    }
    try:
        _forced_save({
            "ability": "constitution",
            "dc": dc,
            "affected": "current_target",
            "on_fail": [
                {"primitive": "apply_condition",
                  "params": {"condition_id": "co_ignited",
                              "duration": "until_spell_ends"}},
            ],
            "on_success": [],
        }, state, _NoOpBus())
    finally:
        state.current_attack["action"] = saved_action

    # One-shot: clear the armed marker (concentration on the burn
    # continues; only the arming is consumed)
    clear_armed(attacker)
    return bonus_damage


class _NoOpBus:
    """Minimal event-bus stand-in for forced_save invocation from
    within try_apply_searing_smite_followup. _forced_save uses the
    bus for emit() calls (none of which are required for correctness
    here); passing a no-op bus avoids threading the real bus through
    the _damage call chain."""

    def emit(self, *args, **kwargs) -> None:
        return None
