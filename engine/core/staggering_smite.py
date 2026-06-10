"""Staggering Smite — Paladin 4th-level smite spell.

Thin adapter over engine.core.smite_rider (shared smite core),
exercising the 4d6 psychic bonus damage + WIS save → co_stunned
pattern.

RAW (PHB 2024, verified against the owned book 2026-06-10):
  Bonus Action cast immediately after hitting with a melee weapon or
  Unarmed Strike; V, Self, Instantaneous. The target takes an extra
  4d6 Psychic damage from the attack, and the target must succeed on a
  Wisdom saving throw or have the Stunned condition until the end of
  your next turn.
  At Higher Levels: +1d6 per slot above 4th.

Spec specifics: melee-only; 4d6 psychic bonus damage base (scales with
upcast); WIS save → co_stunned (until end of caster's next turn — the
duration is tracked as condition persistence, expiry deferred).

source: user_authored

Approximation note: the condition persists until end_concentration or
short rest in the engine v1 rather than expiring at the caster's next
turn-end; duration-scrub logic is a deferred engine item.
"""
from __future__ import annotations

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

STAGGERING_SMITE_ARMED_PRIMITIVE = "staggering_smite_armed"

STAGGERING_SMITE_SPEC = SmiteRiderSpec(
    key="staggering_smite",
    marker_primitive=STAGGERING_SMITE_ARMED_PRIMITIVE,
    named_effect="staggering_smite",
    default_action_id="a_staggering_smite",
    save_ability="wisdom",
    on_fail_condition="co_stunned",
    melee_only=True,
    bonus_damage_die=6,
    bonus_damage_dice_base=4,       # 4d6 psychic on the empowering hit
    bonus_scales_with_upcast=True,  # +1d6 per slot above 4th
    has_initial_save=True,
)


def register_armed(caster: Actor, *, spell_save_dc: int, action_id: str,
                    state: CombatState, slot_level: int = 4) -> None:
    smite_rider.register_armed(
        caster, STAGGERING_SMITE_SPEC,
        spell_save_dc=spell_save_dc, action_id=action_id,
        state=state, slot_level=slot_level,
    )


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, STAGGERING_SMITE_SPEC)


def try_apply_staggering_smite_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng, is_crit: bool) -> int:
    return smite_rider.try_apply_followup(
        attacker, target, state, attack_params, rng, is_crit,
        STAGGERING_SMITE_SPEC,
    )
