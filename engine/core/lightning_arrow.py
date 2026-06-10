"""Lightning Arrow — Ranger 3rd-level ranged-smite spell.

Rides engine.core.smite_rider's marker infrastructure (register /
find / clear) with a custom trigger, like Hail of Thorns: a RANGED
rider whose payload is direct lightning damage to the struck target
plus a save-for-half burst around it.

RAW (PHB 2024, verified against the owned book 2026-06-10):
  Bonus Action cast immediately after hitting or missing with a
  ranged weapon attack; V/S, Self, Instantaneous. The ammunition
  becomes lightning: INSTEAD of the attack's normal damage, the
  target takes 4d8 lightning on a hit (half on a miss), and each
  creature within 10 feet of the target makes a DEX save — 2d8
  lightning on a fail, half on a success.
  At Higher Levels: +1d8 to both effects per slot above 3.

source: user_authored

Approximation notes (v1):
  - Arm-before-hit vs RAW cast-after-attack (shared smite model).
  - Fires on HIT only (the on-a-miss half-damage conversion needs a
    miss hook the rider system doesn't have).
  - RAW REPLACES the weapon's damage with the 4d8; v1 the weapon
    damage still applies and the 4d8 is added on top — overvalues
    by roughly one weapon die + mod, noted until a damage-replace
    hook exists.
  - Burst dice rolled per creature (shared-roll variance nuance,
    same as Hail of Thorns); the struck target is NOT in the burst
    (it already took the direct damage).
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

LIGHTNING_ARROW_ARMED_PRIMITIVE = "lightning_arrow_armed"

# Marker fields only — the trigger below replaces
# smite_rider.try_apply_followup.
LIGHTNING_ARROW_SPEC = SmiteRiderSpec(
    key="lightning_arrow",
    marker_primitive=LIGHTNING_ARROW_ARMED_PRIMITIVE,
    named_effect="lightning_arrow",
    default_action_id="a_lightning_arrow",
    save_ability="dexterity",
    on_fail_condition="",           # unused — custom trigger
    melee_only=False,
    bonus_damage_die=None,
    bonus_scales_with_upcast=False,
)


def register_armed(caster: Actor, slot_level: int, spell_save_dc: int,
                     action_id: str, state: CombatState) -> None:
    smite_rider.register_armed(
        caster, LIGHTNING_ARROW_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state, slot_level=slot_level)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, LIGHTNING_ARROW_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, LIGHTNING_ARROW_SPEC)


def try_apply_lightning_arrow_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire Lightning Arrow on a qualifying RANGED weapon hit: the
    target takes Nd8 lightning directly (N = 4 + slots above 3,
    returned as bonus damage folded into the hit), and every OTHER
    living creature within 10 ft of the target makes a DEX save —
    Md8 lightning on a fail, half on a success (M = 2 + slots above
    3). One-shot."""
    armed = find_armed_entry(attacker)
    if armed is None:
        return 0
    if (attack_params or {}).get("kind", "melee") != "ranged":
        return 0

    armed_params = armed.get("params") or {}
    dc = int(armed_params.get("dc", 10))
    slot_level = int(armed_params.get("slot_level", 3))
    extra = max(0, slot_level - 3)
    direct_n = 4 + extra
    burst_dice = f"{2 + extra}d8"

    rolls = direct_n * (2 if is_crit else 1)
    direct_damage = sum(rng.randint(1, 8) for _ in range(rolls))

    from engine.core.geometry import actors_in_radius
    living = [a for a in state.encounter.actors
              if a.is_alive() and a.id != target.id]
    burst = actors_in_radius(tuple(target.position), 10, living)

    state.event_log.append({
        "event": "lightning_arrow_triggered",
        "attacker": attacker.id, "target": target.id,
        "dc": dc, "slot_level": slot_level,
        "direct_damage": direct_damage, "burst_dice": burst_dice,
        "burst": [a.id for a in burst],
    })

    spell_action_id = (armed.get("source") or {}).get(
        "action_id", LIGHTNING_ARROW_SPEC.default_action_id)
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
                      "params": {"dice": burst_dice, "modifier": 0,
                                  "type": "lightning"}},
                ],
                "on_success": [
                    {"primitive": "damage",
                      "params": {"dice": burst_dice, "modifier": 0,
                                  "type": "lightning",
                                  "multiplier": 0.5}},
                ],
            }, state, smite_rider._NoOpBus())
    finally:
        state.current_attack["action"] = saved_action
        state.current_attack["target"] = saved_target

    clear_armed(attacker)
    return direct_damage
