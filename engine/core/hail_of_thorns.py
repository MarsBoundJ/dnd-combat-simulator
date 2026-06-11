"""Hail of Thorns — Ranger 1st-level ranged-smite spell.

Rides engine.core.smite_rider's marker infrastructure (register /
find / clear) but owns a custom trigger: unlike the melee smites'
"bonus damage + save-for-condition" shape, Hail of Thorns is a
RANGED-only rider whose payload is a save-for-half damage BURST
around the struck target (the target itself included).

RAW (PHB 2024, verified against the owned book 2026-06-10):
  Bonus Action cast immediately after hitting a creature with a
  Ranged weapon; V, Self, Instantaneous. Thorns sprout from the
  weapon or ammunition: the target of the attack and each creature
  within 5 feet of it make a Dexterity saving throw, taking 1d10
  piercing damage on a failed save or half as much on a success.
  At Higher Levels: +1d10 per slot above 1st.

source: user_authored

Approximation notes:
  - Arm-before-hit vs RAW cast-after-hit (shared smite_rider model).
  - Damage dice are rolled per creature instead of RAW's single
    shared roll (same expected value; slightly different variance).
  - The burst is save-based spell damage, separate from the attack —
    it does NOT double on a crit and is not folded into the hit.
  - Friendly fire is RAW: "each creature within 5 feet of it"
    includes allies (and the Ranger, if point-blank).
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

HAIL_OF_THORNS_ARMED_PRIMITIVE = "hail_of_thorns_armed"

# Only the marker fields (key / marker_primitive / named_effect /
# default_action_id) are consumed — the trigger below replaces
# smite_rider.try_apply_followup, so the save/condition fields are
# placeholders.
HAIL_OF_THORNS_SPEC = SmiteRiderSpec(
    key="hail_of_thorns",
    marker_primitive=HAIL_OF_THORNS_ARMED_PRIMITIVE,
    named_effect="hail_of_thorns",
    default_action_id="a_hail_of_thorns",
    save_ability="dexterity",
    on_fail_condition="",           # unused — custom trigger
    melee_only=False,
    bonus_damage_die=None,
    bonus_scales_with_upcast=False,
)


def register_armed(caster: Actor, slot_level: int, spell_save_dc: int,
                     action_id: str, state: CombatState) -> None:
    smite_rider.register_armed(
        caster, HAIL_OF_THORNS_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state, slot_level=slot_level)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, HAIL_OF_THORNS_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, HAIL_OF_THORNS_SPEC)


def try_apply_hail_of_thorns_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire the thorn burst on a qualifying RANGED weapon hit: the
    struck target and every living creature within 5 ft of it make a
    DEX save — Nd10 piercing on a fail, half on a success
    (N = 1 + slot levels above 1st). One-shot; returns 0 (the burst
    is separate save-based damage, never folded into the attack)."""
    armed = find_armed_entry(attacker)
    if armed is None:
        return 0
    if (attack_params or {}).get("kind", "melee") != "ranged":
        return 0

    armed_params = armed.get("params") or {}
    dc = int(armed_params.get("dc", 10))
    slot_level = int(armed_params.get("slot_level", 1))
    dice = f"{1 + max(0, slot_level - 1)}d10"

    from engine.core.geometry import actors_in_radius
    living = [a for a in state.encounter.actors if a.is_alive()]
    burst = actors_in_radius(tuple(target.position), 5, living)
    if target not in burst:
        burst.insert(0, target)

    state.event_log.append({
        "event": "hail_of_thorns_triggered",
        "attacker": attacker.id, "target": target.id,
        "dc": dc, "slot_level": slot_level, "dice": dice,
        "burst": [a.id for a in burst],
    })

    spell_action_id = (armed.get("source") or {}).get(
        "action_id", HAIL_OF_THORNS_SPEC.default_action_id)
    saved_action = state.current_attack.get("action")
    saved_target = state.current_attack.get("target")
    state.current_attack["action"] = {
        "id": spell_action_id,
        "spell_slot_level": slot_level,
    }
    try:
        from engine.primitives import _forced_save
        for creature in burst:
            state.current_attack["target"] = creature
            _forced_save({
                "ability": "dexterity",
                "dc": dc,
                "affected": "current_target",
                "on_fail": [
                    {"primitive": "damage",
                      "params": {"dice": dice, "modifier": 0,
                                  "type": "piercing"}},
                ],
                "on_success": [
                    {"primitive": "damage",
                      "params": {"dice": dice, "modifier": 0,
                                  "type": "piercing", "multiplier": 0.5}},
                ],
            }, state, smite_rider._NoOpBus())
    finally:
        state.current_attack["action"] = saved_action
        state.current_attack["target"] = saved_target

    clear_armed(attacker)
    return 0
