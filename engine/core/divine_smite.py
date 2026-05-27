"""Divine Smite state + qualification (PR #73).

Paladin's signature damage rider. **PHB 2024 changed the mechanic:**
Divine Smite is now a 1st-level Paladin SPELL (not a class feature)
with a Bonus Action casting time taken "immediately after hitting a
target with a Melee weapon attack." From the player's perspective this
plays the same as the 2014 ability — see a hit land, choose to spend
a slot, add radiant damage to the hit — but it now competes with the
Bonus Action slot AND consumes from the Paladin spell-slot pool.

  - **Trigger:** Melee weapon attack hits a creature
  - **Cost:** One 1st-level (or higher) Paladin spell slot +
              Bonus Action
  - **Damage:** 2d8 radiant at 1st-level slot, +1d8 per slot
                level above 1st, **capped at 4th-level slot (5d8)**
  - **Bonus damage:** +1d8 if target is a Fiend or Undead
  - **Requires:** Paladin class level >= 2 (RAW: gained at L2)

This module owns qualification + AI heuristic + application. The
damage rider integration lives in `engine.primitives._damage`,
which calls `try_apply_divine_smite` on melee weapon hit/crit
attacks. Decision is automatic per the heuristic — v1 doesn't emit
a separate "smite candidate" for the AI to score; the choice is
made inside the damage path.

**v1 scope:**
  - Pace-aware AI heuristic: always smite on crit; otherwise smite
    only if expected damage gain exceeds slot opportunity cost
    (uses the existing `slot_cost_ehp` framework from PR #22)
  - Fiend/Undead bonus dice (+1d8)
  - Crits double the smite dice (RAW: class-feature extra dice
    double on crit; smite damage is part of the hit)
  - Consumes one Paladin spell slot 1-4 + marks bonus_action used
  - Always picks LOWEST available slot (RAW: extra dice from higher
    slots are rarely a better trade than saving the slot for a
    different spell)
  - Per-turn dedup via `_divine_smite_used_this_turn` Actor attr
    (defensive — the BA-consumption gate also prevents double-fire)

**Deferred:**
  - Higher-slot smite when player wants the burst (current v1
    always picks the lowest; future PR could detect "this is a
    boss kill" and dump the highest slot)
  - Smite as a separate AI-scored candidate (would let the AI
    explicitly hold off on a small attack and smite a bigger one)
  - The 2014 "smite as bonus action AFTER the attack roll lands
    but BEFORE damage is dealt" timing — v1 folds smite into the
    same damage instance as the attack, which is mechanically
    indistinguishable for HP-tracking but loses the
    "see the result, then decide" narrative beat
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState
from engine.core.spell_slots import slot_cost_ehp


# ============================================================================
# Constants
# ============================================================================

# RAW PHB 2024: Divine Smite caps at a 4th-level spell slot (5d8
# base; 6d8 vs Fiend/Undead). Higher slot levels can hold non-smite
# Paladin spells but smite itself doesn't scale past 5d8.
MAX_SMITE_SLOT_LEVEL = 4

# Base dice at 1st-level slot. Scales: 2 + (slot - 1) = 2/3/4/5 at
# slots 1/2/3/4.
BASE_DICE_AT_SLOT_1 = 2

# Bonus dice vs Fiend or Undead.
FIEND_UNDEAD_BONUS_DICE = 1

# Smite expected damage per die (d8 avg).
D8_AVERAGE = 4.5

# Paladin level at which Divine Smite first becomes available (RAW
# PHB 2024: Paladins get 1st-level slots + Divine Smite at L2).
MIN_PALADIN_LEVEL = 2


# ============================================================================
# Dice math
# ============================================================================

def smite_dice_at_slot_level(slot_level: int) -> int:
    """Return the d8 count for a smite cast at this slot level. Caps at
    MAX_SMITE_SLOT_LEVEL (5d8 at 4th)."""
    if slot_level < 1:
        return 0
    capped = min(int(slot_level), MAX_SMITE_SLOT_LEVEL)
    return BASE_DICE_AT_SLOT_1 + (capped - 1)


def is_fiend_or_undead(target: Actor) -> bool:
    """RAW gate for the +1d8 bonus. Reads `template.creature_type`
    (case-insensitive). Returns False if the field is missing."""
    if target is None or target.template is None:
        return False
    creature_type = (target.template.get("creature_type") or "").lower()
    return creature_type in ("fiend", "undead")


# ============================================================================
# Qualification + AI
# ============================================================================

def qualifies_for_divine_smite(attacker: Actor, target: Actor,
                                  state: CombatState,
                                  attack_params: dict) -> bool:
    """RAW gate for whether the smite COULD be applied to the in-flight
    attack. The AI heuristic in `pick_smite_slot` then decides whether
    it SHOULD.

    Returns False if any of:
      - Attacker has no Paladin level OR level < 2
      - Target is invalid / dead
      - Attack isn't melee weapon (kind != "melee")
      - Bonus action already spent this turn
      - Already smote this turn (defensive — BA gate should prevent
        but the explicit flag survives if BA is reset mid-turn)
      - No usable spell slot (1st through MAX_SMITE_SLOT_LEVEL)
    """
    if _paladin_level(attacker) < MIN_PALADIN_LEVEL:
        return False
    if target is None or not target.is_alive():
        return False
    kind = (attack_params or {}).get("kind", "melee")
    if kind != "melee":
        return False
    if attacker.actions_used_this_turn.get("bonus_action", False):
        return False
    if getattr(attacker, "_divine_smite_used_this_turn", False):
        return False
    if _lowest_available_smite_slot(attacker) is None:
        return False
    return True


def pick_smite_slot(attacker: Actor, target: Actor, state: CombatState,
                       is_crit: bool, base_attack_damage: int) -> int | None:
    """AI heuristic: decide whether to smite and at what slot level.

    Returns the slot level to consume, or None to skip smiting.

    v1 always picks the LOWEST available smite slot (1-4). Higher
    slot levels are reserved for the player's other Paladin spells
    (Bless, Shield of Faith, future expansions). The bonus dice from
    going from a 1st-slot smite (2d8 = 9 avg) to a 4th-slot smite
    (5d8 = 22.5 avg) rarely beat the opportunity cost of the higher
    slot — RAW Paladins overwhelmingly use 1st-level slots for smite.

    Decision tree:
      - Crit → always smite (extra dice double; usually well worth
        the slot)
      - Lethal — target's current HP <= projected smite damage →
        smite to ensure the kill (kill-steal value > slot cost)
      - Fiend/Undead target → smite if slot abundance is reasonable
        (encounters_remaining_today <= 4, biased favorable since the
        +1d8 bonus is a guaranteed extra ~4.5)
      - Otherwise → smite only when expected gain exceeds slot cost
        (via `slot_cost_ehp` from PR #22)

    `base_attack_damage` is the damage the underlying attack is
    already dealing (so the kill-steal check knows the floor).
    """
    slot = _lowest_available_smite_slot(attacker)
    if slot is None:
        return None
    # Always smite on a crit
    if is_crit:
        return slot
    # Expected smite damage (avg, no crit)
    dice_count = smite_dice_at_slot_level(slot)
    if is_fiend_or_undead(target):
        dice_count += FIEND_UNDEAD_BONUS_DICE
    expected = dice_count * D8_AVERAGE
    # Kill-steal: would the smite drop the target?
    if target.hp_current <= int(base_attack_damage) + int(expected):
        return slot
    # Fiend/Undead always-smite bias when slots aren't critical
    if is_fiend_or_undead(target) \
            and state.encounters_remaining_today <= 4:
        return slot
    # Otherwise: pace-aware gate via the standard slot-cost formula
    cost = slot_cost_ehp(
        slot_level=slot,
        slots_remaining=int(attacker.spell_slots.get(slot, 0)),
        encounters_remaining=state.encounters_remaining_today,
    )
    if expected >= cost + 0.5:    # small bias to break ties
        return slot
    return None


def try_apply_divine_smite(attacker: Actor, target: Actor,
                              state: CombatState,
                              attack_params: dict,
                              rng: random.Random,
                              is_crit: bool,
                              base_attack_damage: int) -> int:
    """If the attack qualifies AND the AI elects to smite, roll the
    extra dice and return the damage to add. Consumes the spell slot
    + marks bonus_action used + sets the per-turn dedup flag.

    Returns 0 when the attack doesn't qualify or the heuristic
    declines to smite.

    Crits double the dice count per RAW (extra dice from class
    features double on crit, same as the weapon's base dice and the
    Sneak Attack rider in PR #72).

    Logs `divine_smite_applied` event with the slot level, dice
    count, total damage, crit flag, fiend/undead bonus flag, and
    trigger reason.
    """
    if not qualifies_for_divine_smite(attacker, target, state,
                                          attack_params):
        return 0
    slot = pick_smite_slot(attacker, target, state, is_crit,
                              base_attack_damage)
    if slot is None:
        return 0

    # Roll dice
    dice_count = smite_dice_at_slot_level(slot)
    fiend_bonus = is_fiend_or_undead(target)
    if fiend_bonus:
        dice_count += FIEND_UNDEAD_BONUS_DICE
    rolls_to_make = dice_count * (2 if is_crit else 1)
    total = sum(rng.randint(1, 8) for _ in range(rolls_to_make))

    # Consume slot + BA + dedup
    from engine.core.spell_slots import consume_slot
    consume_slot(attacker, slot, state, action_id="a_divine_smite")
    attacker.actions_used_this_turn["bonus_action"] = True
    attacker._divine_smite_used_this_turn = True

    # Telemetry
    if is_crit:
        trigger = "crit"
    elif target.hp_current <= base_attack_damage + (dice_count * D8_AVERAGE):
        trigger = "lethal"
    elif fiend_bonus:
        trigger = "fiend_undead"
    else:
        trigger = "pace_gate"
    state.event_log.append({
        "event": "divine_smite_applied",
        "attacker": attacker.id,
        "target": target.id,
        "slot_level": slot,
        "dice_count": dice_count,
        "damage": total,
        "is_crit": is_crit,
        "fiend_or_undead": fiend_bonus,
        "trigger": trigger,
    })
    return total


# ============================================================================
# Helpers
# ============================================================================

def _paladin_level(actor: Actor) -> int:
    """Resolve the actor's Paladin level. 0 if not a Paladin."""
    levels = (actor.template or {}).get("levels") or {}
    return int(levels.get("paladin", 0))


def _lowest_available_smite_slot(actor: Actor) -> int | None:
    """Return the lowest spell slot level (1 through
    MAX_SMITE_SLOT_LEVEL) where the actor has at least one slot
    available. None if no smite-usable slots remain.

    Why lowest-first: RAW Paladins almost always smite at 1st-level
    for damage efficiency. Higher-level slots are worth more saved
    for non-smite spells (Bless, Shield of Faith, Aura of Vitality,
    upcast healing).
    """
    for level in range(1, MAX_SMITE_SLOT_LEVEL + 1):
        if int(actor.spell_slots.get(level, 0)) > 0:
            return level
    return None
