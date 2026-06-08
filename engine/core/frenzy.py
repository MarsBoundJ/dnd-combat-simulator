"""Frenzy — Path of the Berserker, Barbarian L3 (PHB 2024 / SRD CC v5.2.1).

RAW (PHB 2024):

  If you use Reckless Attack while your Rage is active, you deal extra
  damage to the first target you hit on your turn with a Strength-based
  attack. To determine the extra damage, roll a number of d6s equal to
  your Rage Damage bonus, and add them together. The damage has the same
  type as the weapon or Unarmed Strike used for the attack.

Mechanically this is a once-per-turn damage rider, the same shape as
Sneak Attack (engine/core/sneak_attack.py) and Divine Smite
(engine/core/divine_smite.py): the qualification + dice roll live here,
and the integration is a single call from `engine.primitives._damage`
that adds the extra dice on a qualifying hit/crit.

Qualification (all must hold):
  1. Attacker has `f_frenzy` (Berserker L3+) in template.features_known.
  2. Rage is active (engine.core.rage.is_raging).
  3. Reckless Attack was used this turn (actor.reckless_active — set by
     the runner's reckless pre-action hook).
  4. The attack is a Strength-based attack — reuses the same RAW gate as
     the rage damage bonus (melee, ability == 'str'), which also covers
     Unarmed Strikes resolved as STR melee.
  5. First qualifying hit this turn — per-turn dedup via
     `_frenzy_used_this_turn` (cleared by Actor.reset_turn).

Dice: `rage_damage_bonus` d6 (the +2/+3/+4 that scales with Barbarian
level). Crit doubles the dice per RAW (extra dice from class features
double on a crit, same as the weapon's base dice + Sneak Attack / Smite).

The damage is "the same type as the weapon," so — like Sneak Attack — it
folds into the same damage instance and is returned as an int to add to
the running total; no separate damage type bookkeeping is needed because
the weapon's type already governs the consolidated hit.

**Deferred:**
  - Versatile/Unarmed edge detection mirrors the rage-bonus gate; a
    finesse weapon swung with DEX won't frenzy (RAW: "Strength-based
    attack"), which matches Rage's own STR gate.
"""
from __future__ import annotations

import random

from engine.core import rage as _rage
from engine.core.state import Actor, CombatState


def has_frenzy(actor: Actor) -> bool:
    """True if the actor knows Frenzy (Berserker L3+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_frenzy" in features


def qualifies_for_frenzy(attacker: Actor, attack_params: dict) -> bool:
    """RAW gate for the Frenzy rider on a damage roll."""
    if not has_frenzy(attacker):
        return False
    if getattr(attacker, "_frenzy_used_this_turn", False):
        return False
    if not _rage.is_raging(attacker):
        return False
    if not getattr(attacker, "reckless_active", False):
        return False
    # Strength-based attack — same RAW gate as the rage damage bonus
    # (melee + STR ability), which also admits STR Unarmed Strikes.
    return _rage.applies_rage_damage_bonus(attacker, attack_params)


def try_apply_frenzy(attacker: Actor, target: Actor,
                        state: CombatState,
                        attack_params: dict,
                        rng: random.Random,
                        is_crit: bool) -> int:
    """If the attack qualifies for Frenzy, roll the extra dice and
    return the damage to add. Sets the per-turn dedup flag.

    Returns 0 when the attack doesn't qualify (no roll, no flag set).
    """
    if not qualifies_for_frenzy(attacker, attack_params):
        return 0
    dice_count = int(getattr(attacker, "rage_damage_bonus", 0) or 0)
    if dice_count <= 0:
        return 0

    rolls_to_make = dice_count * (2 if is_crit else 1)
    total = sum(rng.randint(1, 6) for _ in range(rolls_to_make))

    # Mark used this turn — fires once per turn on the FIRST qualifying
    # hit, even across multi-attack paths.
    attacker._frenzy_used_this_turn = True

    state.event_log.append({
        "event": "frenzy_applied",
        "attacker": attacker.id,
        "target": target.id,
        "dice_count": dice_count,
        "damage": total,
        "is_crit": is_crit,
    })
    return total
