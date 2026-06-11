"""Fanatical Focus — Path of the Zealot, Barbarian L6 (PHB 2024 / SRD CC v5.2.1).

RAW: "Once per active Rage, if you fail a saving throw, you can reroll it
with a bonus equal to your Rage Damage bonus, and you must use the new roll."

Engine modeling: a passive save-reroll hook. When a raging Zealot fails a
saving throw, `try_fanatical_focus_reroll` may intercept the fail and
roll fresh (d20 + full save bonus + Rage Damage bonus), consuming the
once-per-Rage charge. The charge flag is cleared when Rage starts (via
`reset_for_new_rage`, called from `enter_rage`).

The reroll is NOT subject to Legendary Resistance (which is processed
after this hook), so the Zealot might reroll to success and still lose to
Legendary Resistance — that's a corner case and RAW is silent, so we take
the conservative "reroll fires first" ordering.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState

# Cover bonus lookup (duplicated from primitives._cover_ac_bonus to avoid
# circular imports; values are RAW and stable).
_COVER_BONUS = {"half": 2, "three_quarters": 5}


def has_fanatical_focus(actor: Actor) -> bool:
    """True if the actor has Fanatical Focus (Zealot L6+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_fanatical_focus" in features


def try_fanatical_focus_reroll(
    target: Actor,
    ability: str,
    dc: int,
    rng: random.Random,
    state: CombatState,
) -> tuple[int | None, int | None, str | None]:
    """Attempt a Fanatical Focus reroll on a just-failed saving throw.

    Returns (new_d20, new_total, new_outcome) if the feature fired and the
    charge was consumed, or (None, None, None) if it didn't apply (not
    raging, no feature, or already used this Rage).
    """
    if not getattr(target, "rage_active", False):
        return None, None, None
    if not has_fanatical_focus(target):
        return None, None, None
    if getattr(target, "_fanatical_focus_used_this_rage", False):
        return None, None, None

    target._fanatical_focus_used_this_rage = True

    rage_bonus = int(getattr(target, "rage_damage_bonus", 0))
    short = {"strength": "str", "dexterity": "dex", "constitution": "con",
             "intelligence": "int", "wisdom": "wis",
             "charisma": "cha"}.get(ability, ability[:3])
    save_bonus = target.abilities.get(short, {}).get("save", 0)
    cover_bonus = 0
    if ability == "dexterity":
        cover_bonus = _COVER_BONUS.get(getattr(target, "cover", "none"), 0)

    new_d20 = rng.randint(1, 20)
    new_total = new_d20 + save_bonus + rage_bonus + cover_bonus
    new_outcome = "success" if new_total >= dc else "fail"

    state.event_log.append({
        "event": "fanatical_focus_reroll",
        "actor": target.id,
        "ability": ability,
        "dc": dc,
        "d20": new_d20,
        "save_bonus": save_bonus,
        "rage_bonus": rage_bonus,
        "total": new_total,
        "outcome": new_outcome,
    })
    return new_d20, new_total, new_outcome


def reset_for_new_rage(actor: Actor) -> None:
    """Clear the once-per-Rage charge when a new Rage starts."""
    actor._fanatical_focus_used_this_rage = False
