"""Banishing Smite — Paladin 5th-level smite spell.

Rides engine.core.smite_rider's marker infrastructure (register /
find / clear) with a custom trigger, like Lightning Arrow: the banish
save only fires when the empowered hit leaves the target at 50 HP or
fewer — an HP-conditional the shared SmiteRiderSpec save path doesn't
model.

RAW (PHB 2024, verified against the owned book 2026-06-10):
  Bonus Action cast immediately after hitting with a Melee weapon or
  Unarmed Strike; V, Self, Concentration up to 1 minute. The target
  takes an extra 5d10 Force damage from the attack. If the attack
  reduces the target to 50 Hit Points or fewer, it must succeed on a
  Charisma saving throw or be transported to a harmless demiplane for
  the duration, where it has the Incapacitated condition. When the
  spell ends, the target reappears.
  No upcast scaling.

source: user_authored

Approximation notes (v1):
  - Arm-before-hit vs RAW cast-after-attack (shared smite model).
  - "Reduces to 50 HP or fewer" is evaluated as (target HP before
    this damage instance - the 5d10 bonus) <= 50. The weapon's own
    damage in the same hit isn't visible to the rider hook, so a
    target at e.g. 53 HP whose weapon damage would carry it below 50
    is missed — a slight undervalue, never an overvalue.
  - The demiplane is modeled as co_incapacitated (the Banishment
    precedent: "gone from the fight" = can't act). The untargetable
    facet is not modeled.
  - Escape: a turn-end CHA re-save (same v1 proxy as Banishment;
    RAW the banishment simply lasts while the caster concentrates).
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

BANISHING_SMITE_ARMED_PRIMITIVE = "banishing_smite_armed"

# Marker fields only — the trigger below replaces
# smite_rider.try_apply_followup.
BANISHING_SMITE_SPEC = SmiteRiderSpec(
    key="banishing_smite",
    marker_primitive=BANISHING_SMITE_ARMED_PRIMITIVE,
    named_effect="banishing_smite",
    default_action_id="a_banishing_smite",
    save_ability="charisma",
    on_fail_condition="co_incapacitated",
    melee_only=True,
    bonus_damage_die=None,          # unused — custom trigger
    bonus_scales_with_upcast=False,
)

BANISH_HP_THRESHOLD = 50


def register_armed(caster: Actor, *, spell_save_dc: int, action_id: str,
                     state: CombatState, slot_level: int = 5) -> None:
    smite_rider.register_armed(
        caster, BANISHING_SMITE_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state, slot_level=slot_level)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, BANISHING_SMITE_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, BANISHING_SMITE_SPEC)


def try_apply_banishing_smite_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire Banishing Smite on a qualifying MELEE weapon hit: the
    target takes 5d10 force directly (returned as bonus damage folded
    into the hit). If that leaves the target's projected HP at 50 or
    fewer, it makes a CHA save — on a fail it is banished
    (co_incapacitated + turn-end CHA escape re-save). One-shot."""
    armed = find_armed_entry(attacker)
    if armed is None:
        return 0
    if (attack_params or {}).get("kind", "melee") != "melee":
        return 0

    armed_params = armed.get("params") or {}
    dc = int(armed_params.get("dc", 10))
    slot_level = int(armed_params.get("slot_level", 5))

    rolls = 5 * (2 if is_crit else 1)
    bonus_damage = sum(rng.randint(1, 10) for _ in range(rolls))

    projected_hp = target.hp_current - bonus_damage
    banish_attempt = projected_hp <= BANISH_HP_THRESHOLD

    state.event_log.append({
        "event": "banishing_smite_triggered",
        "attacker": attacker.id, "target": target.id,
        "dc": dc, "slot_level": slot_level,
        "bonus_damage": bonus_damage, "is_crit": is_crit,
        "banish_attempt": banish_attempt,
        "projected_hp": projected_hp,
    })

    if banish_attempt:
        spell_action_id = (armed.get("source") or {}).get(
            "action_id", BANISHING_SMITE_SPEC.default_action_id)
        saved_action = state.current_attack.get("action")
        state.current_attack["action"] = {
            "id": spell_action_id,
            "spell_slot_level": slot_level,
        }
        try:
            from engine.primitives import _forced_save
            _forced_save({
                "ability": "charisma",
                "dc": dc,
                "affected": "current_target",
                "on_fail": [
                    {"primitive": "apply_condition",
                      "params": {"condition_id": "co_incapacitated",
                                  "duration": "until_spell_ends"}},
                    {"primitive": "recurring_save",
                      "params": {"ability": "charisma", "dc": dc,
                                  "trigger_event": "target_turn_end",
                                  "on_success": "end_spell_on_target",
                                  "condition_id": "co_incapacitated"}},
                ],
                "on_success": [],
            }, state, smite_rider._NoOpBus())
        finally:
            state.current_attack["action"] = saved_action

    clear_armed(attacker)
    return bonus_damage
