"""Blinding Smite — Paladin 3rd-level smite spell.

Thin adapter over engine.core.smite_rider (PR #112 shared core).
Owns the SmiteRiderSpec and re-exports public functions with
per-spell signatures so callers (arm primitive, _damage hook,
tests) resolve here.

RAW (PHB 2024, verified against the owned book 2026-06-10):
  Bonus Action cast immediately after hitting with a melee weapon
  or Unarmed Strike; V, Self, 1 minute — NOT concentration (the
  2024 redesign dropped it). The hit deals an extra 3d8 radiant
  damage, and the target has the Blinded condition until the spell
  ends; at the end of each of its turns it makes a CON save, ending
  the effect on a success.
  At Higher Levels: +1d8 per slot above 3rd.

Spec specifics: melee-only; 3d8 radiant bonus damage at base slot 3
(SmiteRiderSpec formula: dice_count = 1 + (slot_level - 1) = 3 at
slot 3, scaling +1 per upcast); NO initial save — Blinded applies
automatically on hit; repeat_save_to_end (end-of-turn CON re-save,
the 2024 escape valve that replaced concentration).

source: user_authored

Approximation note: arm-before-hit vs RAW cast-after-hit (shared
smite_rider model); 1-minute cap modeled as "until the target
saves out".
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
    save_ability="constitution",      # end-of-turn save (deferred)
    on_fail_condition="co_blinded",
    melee_only=True,
    bonus_damage_die=8,               # d8 radiant per die
    bonus_scales_with_upcast=True,    # +1d8 per slot above 1st
    has_initial_save=False,           # Blinded applies automatically on hit
    repeat_save_to_end=True,          # 2024: end-of-turn CON re-save
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
    radiant (+1d8/upcast, doubled on crit), Blinded applied
    automatically (no initial save). Returns the bonus damage."""
    return smite_rider.try_apply_followup(
        attacker, target, state, attack_params, rng, is_crit,
        BLINDING_SMITE_SPEC)


_NoOpBus = smite_rider._NoOpBus
