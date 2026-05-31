"""Blinding Smite — Paladin 3rd-level smite spell.

Thin adapter over engine.core.smite_rider (PR #112 shared core).
Owns the SmiteRiderSpec and re-exports public functions with
per-spell signatures so callers (arm primitive, _damage hook,
tests) resolve here.

RAW (PHB 2024):
  Bonus Action, V, Self, Concentration up to 1 minute. The next
  time you hit a creature with a melee weapon attack, the attack
  deals an extra 3d8 radiant damage. The target must succeed on a
  Constitution saving throw or be Blinded until the spell ends.
  At Higher Levels: +1d8 per slot above 3rd.

Spec specifics: melee-only; 3d8 radiant bonus damage at base slot 3
(SmiteRiderSpec formula: dice_count = 1 + (slot_level - 1) = 3 at
slot 3, scaling +1 per upcast); CON save -> co_blinded.

source: user_authored

Deferred: target's action to repeat the CON save to end the spell
(same pattern as Searing Smite's deferred action-to-save).
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

BLINDING_SMITE_ARMED_PRIMITIVE = "blinding_smite_armed"

BLINDING_SMITE_SPEC = SmiteRiderSpec(
    key="blinding_smite",
    marker_primitive=BLINDING_SMITE_ARMED_PRIMITIVE,
    named_effect="blinding_smite",
    default_action_id="a_blinding_smite",
    save_ability="constitution",
    on_fail_condition="co_blinded",
    melee_only=True,
    bonus_damage_die=8,             # d8 radiant per die
    bonus_scales_with_upcast=True,  # +1d8 per slot above 1st
)


def register_armed(caster: Actor, slot_level: int, spell_save_dc: int,
                     action_id: str, state: CombatState) -> None:
    smite_rider.register_armed(
        caster, BLINDING_SMITE_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state, slot_level=slot_level)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, BLINDING_SMITE_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, BLINDING_SMITE_SPEC)


def try_apply_blinding_smite_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire Blinding Smite's rider on a qualifying melee hit: 3d8
    radiant (+1d8/upcast, doubled on crit), CON save -> co_blinded.
    Returns the bonus damage to add to the attack total."""
    return smite_rider.try_apply_followup(
        attacker, target, state, attack_params, rng, is_crit,
        BLINDING_SMITE_SPEC)


_NoOpBus = smite_rider._NoOpBus
