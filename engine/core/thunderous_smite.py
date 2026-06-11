"""Thunderous Smite — Paladin 1st-level smite spell.

Thin adapter over engine.core.smite_rider (PR #112 shared core),
exercising two spec extensions added for it: a base bonus-damage die
count above 1 (2d6) and an on-fail forced push (the roadmap's
"Thunderous: prone + push" item).

RAW (PHB 2024, verified against the owned book 2026-06-10):
  Bonus Action cast immediately after hitting with a melee weapon or
  Unarmed Strike; V, Self, Instantaneous. The strike booms (audible
  300 ft): the target takes an extra 2d6 thunder damage from the
  attack, and (if a creature) makes a Strength saving throw or is
  pushed 10 feet away from you and has the Prone condition.
  At Higher Levels: +1d6 per slot above 1st.

Spec specifics: melee-only; 2d6 thunder bonus damage base (scales
with upcast); STR save -> co_prone + 10-ft push (on_fail_push_ft).
No repeat save — the effect is instantaneous, prone just costs the
stand-up movement.

source: user_authored

Approximation note: the engine arms the smite BEFORE the triggering
hit (shared smite_rider model); RAW 2024 casts it after the hit
lands. The 300-ft audibility is flavor (no sound modeling).
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

THUNDEROUS_SMITE_ARMED_PRIMITIVE = "thunderous_smite_armed"

THUNDEROUS_SMITE_SPEC = SmiteRiderSpec(
    key="thunderous_smite",
    marker_primitive=THUNDEROUS_SMITE_ARMED_PRIMITIVE,
    named_effect="thunderous_smite",
    default_action_id="a_thunderous_smite",
    save_ability="strength",
    on_fail_condition="co_prone",
    melee_only=True,
    bonus_damage_die=6,
    bonus_damage_dice_base=2,       # 2d6 thunder on the empowering hit
    bonus_scales_with_upcast=True,
    on_fail_push_ft=10,             # failed save: shoved 10 ft + Prone
)


def register_armed(caster: Actor, slot_level: int, spell_save_dc: int,
                     action_id: str, state: CombatState) -> None:
    smite_rider.register_armed(
        caster, THUNDEROUS_SMITE_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state, slot_level=slot_level)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, THUNDEROUS_SMITE_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, THUNDEROUS_SMITE_SPEC)


def try_apply_thunderous_smite_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire Thunderous Smite's rider on a qualifying melee hit: 2d6
    thunder (+1d6/upcast, doubled on crit), STR save -> pushed 10 ft
    away + co_prone. Returns the bonus damage to add to the attack."""
    return smite_rider.try_apply_followup(
        attacker, target, state, attack_params, rng, is_crit,
        THUNDEROUS_SMITE_SPEC)


_NoOpBus = smite_rider._NoOpBus
