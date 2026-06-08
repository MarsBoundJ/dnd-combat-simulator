"""Divine Fury — Path of the Zealot, Barbarian L3 (PHB 2024 / SRD CC v5.2.1).

RAW (PHB 2024):

  On each of your turns while your Rage is active, the first creature you
  hit with a weapon or an Unarmed Strike takes extra damage equal to 1d6
  plus half your Barbarian level (round down). The extra damage is
  Necrotic or Radiant; you choose the type each time you deal the damage.

A once-per-turn damage rider, the same shape as Frenzy / Sneak Attack /
Divine Smite: the qualification + roll live here and the integration is a
single call from `engine.primitives._damage` on a qualifying hit/crit.

Unlike Frenzy, Divine Fury needs no Reckless Attack and isn't limited to
Strength attacks — ANY weapon or Unarmed Strike hit qualifies while
raging.

Qualification (all must hold):
  1. Attacker has `f_divine_fury` (Zealot L3+) in features_known.
  2. Rage is active.
  3. The attack is a weapon or Unarmed Strike (kind melee or ranged).
  4. First qualifying hit this turn — per-turn dedup via
     `_divine_fury_used_this_turn` (cleared by Actor.reset_turn).

Damage: 1d6 + floor(Barbarian level / 2). Crit doubles the die (RAW:
extra dice from class features double on a crit) but NOT the flat bonus.

The extra damage is Necrotic/Radiant — a different type from the weapon —
but, like Divine Smite's Radiant, it folds into the consolidated hit
(returned as an int), so it takes the weapon's resistance treatment. A
type-aware resistance pass for folded riders is a shared follow-on (it
would refine Divine Smite the same way).
"""
from __future__ import annotations

import random

from engine.core import rage as _rage
from engine.core.state import Actor, CombatState


def has_divine_fury(actor: Actor) -> bool:
    """True if the actor knows Divine Fury (Zealot L3+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_divine_fury" in features


def _barbarian_level(actor: Actor) -> int:
    levels = (actor.template or {}).get("levels") or {}
    return int(levels.get("barbarian", 0))


def qualifies_for_divine_fury(attacker: Actor, attack_params: dict) -> bool:
    """RAW gate for the Divine Fury rider on a damage roll."""
    if not has_divine_fury(attacker):
        return False
    if getattr(attacker, "_divine_fury_used_this_turn", False):
        return False
    if not _rage.is_raging(attacker):
        return False
    # Any weapon or Unarmed Strike hit (melee or ranged weapon). No
    # Strength / Reckless gate — Divine Fury is broader than Frenzy.
    kind = (attack_params or {}).get("kind", "melee")
    return kind in ("melee", "ranged")


def try_apply_divine_fury(attacker: Actor, target: Actor,
                            state: CombatState,
                            attack_params: dict,
                            rng: random.Random,
                            is_crit: bool) -> int:
    """If the attack qualifies for Divine Fury, roll the extra damage and
    return it to add. Sets the per-turn dedup flag.

    Returns 0 when the attack doesn't qualify (no roll, no flag set).
    """
    if not qualifies_for_divine_fury(attacker, attack_params):
        return 0
    flat_bonus = _barbarian_level(attacker) // 2
    # 1d6 (2d6 on crit) + the flat bonus (the flat half-level is NOT
    # doubled on a crit — only the die is).
    die_rolls = 2 if is_crit else 1
    rolled = sum(rng.randint(1, 6) for _ in range(die_rolls))
    total = rolled + flat_bonus

    attacker._divine_fury_used_this_turn = True

    state.event_log.append({
        "event": "divine_fury_applied",
        "attacker": attacker.id,
        "target": target.id,
        "die": rolled,
        "flat_bonus": flat_bonus,
        "damage": total,
        "is_crit": is_crit,
    })
    return total
