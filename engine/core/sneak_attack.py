"""Sneak Attack state + qualification (PR #72).

Rogue's class-defining feature. RAW (PHB 2024):

  Once per turn, you can deal an extra 1d6 damage to one creature you
  hit with an attack roll that uses a Finesse or a Ranged weapon, if
  one of the following applies:
    - You have Advantage on the attack roll, OR
    - Another enemy of the target is within 5 feet of it, that enemy
      isn't Incapacitated, and you don't have Disadvantage on the
      attack roll

  Extra dice scale with Rogue level (see SNEAK_ATTACK_DICE_BY_LEVEL).

This module owns the qualification logic + per-turn dedup. The damage
rider integration lives in `engine.primitives._damage`, which calls
`try_apply_sneak_attack` on hit/crit attacks to add the extra dice.

**v1 scope:**
  - Full RAW qualification (finesse/ranged + advantage OR ally-adjacent
    + no-disadvantage)
  - Per-turn dedup via `_sneak_attack_used_this_turn` Actor attr
    (cleared by `reset_turn`)
  - Level-scaled dice (1d6 at L1 → 10d6 at L19)
  - Critical hit doubles the SA dice (RAW: extra dice from class
    features double on a crit)
  - Telemetry: `sneak_attack_applied` event with dice count + total
  - Fires on OAs too (RAW: "once per turn" — not "once per round")

**Deferred:**
  - Cunning Strike (2024 PHB; trade SA dice for effects like Poison,
    Trip, Withdraw) — separate PR
  - Steady Aim (bonus action: advantage on next attack; doesn't move
    this turn) — separate PR
  - Sneak Attack on natural 1 vs Invisible attacker quirks — current
    advantage detection trusts the `had_advantage` flag set by
    _attack_roll
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState
from engine.core.geometry import distance_ft
from engine.core.concentration import has_incapacitating_condition


# ============================================================================
# Level table — PHB 2024
# ============================================================================

# Sneak Attack dice (d6) by Rogue level. RAW: +1d6 at every odd level
# from L1 through L19, capping at 10d6 at L19+.
SNEAK_ATTACK_DICE_BY_LEVEL: dict[int, int] = {
    lv: (lv + 1) // 2
    for lv in range(1, 21)
}


def sneak_attack_dice_at_level(level: int) -> int:
    """Return the SA d6 count for a Rogue at this level. 0 for
    level <= 0 (non-Rogue sentinel)."""
    if level < 1:
        return 0
    if level > 20:
        level = 20
    return SNEAK_ATTACK_DICE_BY_LEVEL[level]


# ============================================================================
# Qualification + application
# ============================================================================

def qualifies_for_sneak_attack(attacker: Actor, target: Actor,
                                  state: CombatState,
                                  attack_params: dict) -> bool:
    """RAW gate for Sneak Attack on an in-flight attack.

    Returns False (no SA) if any of these fail:
      - Attacker has no Rogue level (template.levels.rogue == 0)
      - Already used SA this turn (per-turn dedup)
      - Weapon isn't Finesse or Ranged
      - Neither RAW trigger applies:
          (a) Advantage on the attack, OR
          (b) Ally-adjacent-to-target AND attack didn't have
              disadvantage AND the adjacent ally isn't Incapacitated

    The `attack_params` dict comes from the in-flight attack_roll
    step (typically `state.current_attack.action.pipeline[0].params`).
    Reads `kind` (ranged/melee) and `finesse` (bool); melee weapons
    without `finesse: true` set on their spec do NOT qualify.

    Reads `had_advantage` / `had_disadvantage` from
    `state.current_attack` — those flags are set by `_attack_roll`
    during attack resolution.
    """
    # Level gate
    if _rogue_level(attacker) <= 0:
        return False
    # Per-turn dedup
    if getattr(attacker, "_sneak_attack_used_this_turn", False):
        return False
    # Weapon gate: ranged OR finesse-melee
    kind = (attack_params or {}).get("kind", "melee")
    is_finesse = bool((attack_params or {}).get("finesse"))
    if kind != "ranged" and not is_finesse:
        return False
    # Roll-state gate
    had_advantage = bool(state.current_attack.get("had_advantage", False))
    had_disadvantage = bool(state.current_attack.get(
        "had_disadvantage", False))
    if had_advantage:
        return True
    if had_disadvantage:
        return False
    # Fallback: ally-adjacent-to-target check
    return _has_ally_adjacent_to_target(attacker, target, state)


def try_apply_sneak_attack(attacker: Actor, target: Actor,
                              state: CombatState,
                              attack_params: dict,
                              rng: random.Random,
                              is_crit: bool) -> int:
    """If the attack qualifies for Sneak Attack, roll the extra dice
    and return the damage to add. Sets the per-turn dedup flag.

    Returns 0 when the attack doesn't qualify (no roll, no flag set).
    Crits double the dice count per RAW (extra dice from class
    features double on crit, same as the weapon's base dice).

    Logs `sneak_attack_applied` event with the dice count, total,
    crit flag, and trigger reason (advantage vs ally_adjacent).
    """
    if not qualifies_for_sneak_attack(attacker, target, state,
                                          attack_params):
        return 0
    dice_count = sneak_attack_dice_at_level(_rogue_level(attacker))
    if dice_count <= 0:
        return 0
    # Roll N d6 (2N on crit)
    rolls_to_make = dice_count * (2 if is_crit else 1)
    total = sum(rng.randint(1, 6) for _ in range(rolls_to_make))
    # Mark used this turn (the only correct moment — fires once per
    # turn even across multi-attack / OA paths)
    attacker._sneak_attack_used_this_turn = True
    # Telemetry
    trigger = "advantage" if state.current_attack.get(
        "had_advantage") else "ally_adjacent"
    state.event_log.append({
        "event": "sneak_attack_applied",
        "attacker": attacker.id,
        "target": target.id,
        "dice_count": dice_count,
        "damage": total,
        "is_crit": is_crit,
        "trigger": trigger,
    })
    return total


# ============================================================================
# Helpers
# ============================================================================

def _rogue_level(actor: Actor) -> int:
    """Resolve the actor's Rogue level from template.levels.rogue.
    Returns 0 if not a Rogue (or no level recorded)."""
    levels = (actor.template or {}).get("levels") or {}
    return int(levels.get("rogue", 0))


def _has_ally_adjacent_to_target(attacker: Actor, target: Actor,
                                     state: CombatState) -> bool:
    """RAW: 'Another enemy of the target is within 5 feet of it, that
    enemy isn't Incapacitated.'

    "Another enemy of the target" = a creature on a different side
    from `target`, alive, NOT the attacker themselves (RAW says
    "another"), within 5 ft of `target`, not Incapacitated.
    """
    for ally in state.encounter.actors:
        if ally.id == attacker.id:
            continue
        if ally.id == target.id:
            continue
        if not ally.is_alive():
            continue
        if ally.side == target.side:
            continue
        if has_incapacitating_condition(ally):
            continue
        if distance_ft(ally.position, target.position) <= 5:
            return True
    return False
