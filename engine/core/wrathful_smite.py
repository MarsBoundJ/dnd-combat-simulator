"""Wrathful Smite — Paladin 1st-level smite spell.

Thin adapter over engine.core.smite_rider (PR #112 shared core).
Owns the SmiteRiderSpec and re-exports public functions with
per-spell signatures so callers (arm primitive, _damage hook,
tests) resolve here.

RAW (PHB 2024):
  Bonus Action, V, Self, Concentration up to 1 minute. The next
  time you hit with a melee weapon attack, the attack deals an
  extra 1d6 necrotic damage. The target must succeed on a Wisdom
  saving throw or be Frightened of you until the spell ends.
  At Higher Levels: +1d6 per slot above 1st.

Spec specifics: melee-only; 1d6 necrotic bonus damage (scales with
upcast); WIS save -> co_frightened.

source: user_authored

Deferred: target's action to repeat the WIS check to end the
effect (same pattern as Searing Smite's deferred action-to-save).
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

WRATHFUL_SMITE_ARMED_PRIMITIVE = "wrathful_smite_armed"

WRATHFUL_SMITE_SPEC = SmiteRiderSpec(
    key="wrathful_smite",
    marker_primitive=WRATHFUL_SMITE_ARMED_PRIMITIVE,
    named_effect="wrathful_smite",
    default_action_id="a_wrathful_smite",
    save_ability="wisdom",
    on_fail_condition="co_frightened",
    melee_only=True,
    bonus_damage_die=6,             # 1d6 necrotic on the empowering hit
    bonus_scales_with_upcast=True,
)


def register_armed(caster: Actor, slot_level: int, spell_save_dc: int,
                     action_id: str, state: CombatState) -> None:
    smite_rider.register_armed(
        caster, WRATHFUL_SMITE_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state, slot_level=slot_level)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, WRATHFUL_SMITE_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, WRATHFUL_SMITE_SPEC)


def try_apply_wrathful_smite_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire Wrathful Smite's rider on a qualifying melee hit: 1d6
    necrotic (+1d6/upcast, doubled on crit), WIS save -> co_frightened.
    Returns the bonus damage to add to the attack total."""
    return smite_rider.try_apply_followup(
        attacker, target, state, attack_params, rng, is_crit,
        WRATHFUL_SMITE_SPEC)


_NoOpBus = smite_rider._NoOpBus
