"""Rage state machine for Barbarians (PR #71).

Barbarian's class-defining feature. RAW (PHB 2024):

  - **Activation:** Bonus Action; expends one `rage_uses_remaining`
    charge. While raging, the Barbarian gets:
      * Bonus damage on Strength-mod melee weapon attacks
        (+2 at L1-8, +3 at L9-15, +4 at L16+)
      * Resistance to bludgeoning / piercing / slashing damage
      * Advantage on Strength checks and Strength saving throws
      * Can't cast spells or maintain concentration

  - **Duration:** 10 minutes (effectively combat-long in any single
    encounter), with two practical end conditions:
      1. The Barbarian is knocked unconscious / dies
      2. At the end of the Barbarian's turn, they have not attacked
         a hostile creature AND have not taken damage that turn

  - **Recovery:** uses recover on a long rest (RAW 2024 also returns
    one use on a short rest at L3+ via Relentless Rage / similar —
    deferred to subclass passes).

This module owns the state transitions; the bonus-action wiring + the
on-hit damage rider + the BPS resistance + the per-turn bookkeeping
are integrated at their respective sites (pc_schema, _damage,
_attack_roll, runner turn boundary). A central module keeps the rule
in one place rather than scattering "if rage_active" checks across
the codebase.

**v1 scope:**
  - All four core RAW effects (BA action, damage rider, resistance,
    STR advantage)
  - End-of-turn auto-end check (no-attack + no-damage rule)
  - Long-rest charge reset (via engine.core.rest)
  - Level-driven uses + damage tables

**Deferred:**
  - 10-minute hard duration cap (round counter; the auto-end check
    catches the practical case)
  - Concentration / spellcasting suppression (no Barbarian in v1
    has spells; multiclass / subclass spellcasters need this)
  - Short-rest one-charge recovery (Relentless Rage L11+, etc.)
  - Bonus action to maintain rage at higher levels (subclass)
  - Persistent Rage feature (Berserker subclass)
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# ============================================================================
# Level tables — PHB 2024 Barbarian
# ============================================================================

# Number of rages per long rest, indexed by Barbarian level. RAW 2024:
# 2 / 2 / 3 / 3 / 3 / 4 / 4 / 4 / 4 / 4 / 5 / 5 / 5 / 5 / 5 / 6 / 6 / 6 / 6 / 6.
RAGE_USES_BY_LEVEL: dict[int, int] = {
    1: 2, 2: 2, 3: 3, 4: 3, 5: 3,
    6: 4, 7: 4, 8: 4, 9: 4, 10: 4,
    11: 5, 12: 5, 13: 5, 14: 5, 15: 5,
    16: 6, 17: 6, 18: 6, 19: 6, 20: 6,
}

# Bonus damage on Strength-mod melee weapon attacks while raging.
# RAW 2024: +2 at L1-8, +3 at L9-15, +4 at L16+.
RAGE_DAMAGE_BY_LEVEL: dict[int, int] = {
    **{lv: 2 for lv in range(1, 9)},
    **{lv: 3 for lv in range(9, 16)},
    **{lv: 4 for lv in range(16, 21)},
}


def rage_uses_at_level(level: int) -> int:
    """Return the long-rest rage charge count for a Barbarian at this
    level. Returns 0 for level <= 0 (non-Barbarian sentinel)."""
    if level < 1:
        return 0
    if level > 20:
        level = 20
    return RAGE_USES_BY_LEVEL[level]


def rage_damage_at_level(level: int) -> int:
    """Return the rage damage bonus for a Barbarian at this level.
    Returns 0 for level <= 0."""
    if level < 1:
        return 0
    if level > 20:
        level = 20
    return RAGE_DAMAGE_BY_LEVEL[level]


# ============================================================================
# State transitions
# ============================================================================

def is_raging(actor: Actor) -> bool:
    """True iff the actor is currently in Rage."""
    return bool(getattr(actor, "rage_active", False))


def enter_rage(actor: Actor, state: CombatState) -> None:
    """Flip the actor into Rage, stamping their level-appropriate
    damage bonus. Caller is responsible for decrementing the
    `rage_uses_remaining` resource (the action's `feature_use`
    pipeline gate does this at execution time).

    Re-entering Rage while already raging is a no-op — the bonus-
    action gate should prevent this, but the guard is defensive.
    Logs `rage_started` with the damage bonus + charges remaining.
    """
    if is_raging(actor):
        return
    level = _barbarian_level(actor)
    actor.rage_active = True
    actor.rage_damage_bonus = rage_damage_at_level(level)
    # Per-turn tracking starts fresh — the turn the actor enters rage
    # counts the entry action as satisfying "attacked a hostile" only
    # if a hostile attack actually fires later in the turn. The flag
    # below is set by _attack_roll on hostile-targeted swings.
    actor._rage_attacked_hostile_this_turn = False
    actor._rage_damaged_this_turn = False
    actor._rage_started_at_round = state.round
    state.event_log.append({
        "event": "rage_started",
        "actor": actor.id,
        "damage_bonus": actor.rage_damage_bonus,
        "charges_remaining": int(actor.resources.get(
            "rage_uses_remaining", 0)),
        "round": state.round,
    })
    # Fanatical Focus (Zealot L6): clear once-per-Rage charge on each
    # new Rage entry so the feature is available again.
    from engine.core.fanatical_focus import reset_for_new_rage
    reset_for_new_rage(actor)
    # Rage of the Gods (Zealot L14): optionally activate divine form.
    from engine.core.rage_of_the_gods import try_activate_rage_of_the_gods
    try_activate_rage_of_the_gods(actor, state)
    # Rage of the Wilds (Wild Heart L3): activate the chosen animal aspect.
    from engine.core.wild_heart import activate_rage_of_the_wilds
    activate_rage_of_the_wilds(actor, state)
    # Power of the Wilds (Wild Heart L14): activate the chosen option.
    from engine.core.wild_heart import activate_power_of_the_wilds
    activate_power_of_the_wilds(actor, state)


def end_rage(actor: Actor, state: CombatState, reason: str) -> None:
    """End the actor's Rage. Reasons: 'no_attack_no_damage' (RAW
    auto-end), 'incapacitated' (deferred), 'manual' (future). Idempotent
    when not raging."""
    if not is_raging(actor):
        return
    actor.rage_active = False
    actor.rage_damage_bonus = 0
    # Rage of the Gods (Zealot L14): divine form ends with Rage.
    from engine.core.rage_of_the_gods import deactivate_rage_of_the_gods
    deactivate_rage_of_the_gods(actor, state)
    # Rage of the Wilds (Wild Heart L3): animal aspect ends with Rage.
    from engine.core.wild_heart import deactivate_rage_of_the_wilds
    deactivate_rage_of_the_wilds(actor, state)
    # Power of the Wilds (Wild Heart L14): option ends with Rage.
    from engine.core.wild_heart import deactivate_power_of_the_wilds
    deactivate_power_of_the_wilds(actor, state)
    state.event_log.append({
        "event": "rage_ended",
        "actor": actor.id,
        "reason": reason,
        "round": state.round,
    })


def check_rage_end_of_turn(actor: Actor, state: CombatState) -> None:
    """Apply RAW's "no attack, no damage → rage ends" auto-end check
    at the end of the actor's turn.

    Skip cases:
      - Actor isn't raging (no state to end)
      - Actor entered rage THIS turn — the entry action consumed the
        bonus action, and the no-attack/no-damage rule kicks in next
        turn. We detect this via the per-turn flag pair: if BOTH are
        False AND rage started in a prior round, we end. The flags
        being False on the entry turn is normal — the actor used
        their bonus action to rage and didn't get another shot.

    To distinguish "raged this turn, didn't get to swing" from
    "raged last turn, did nothing this turn," we check
    `_rage_just_started_this_turn`: a transient attribute set by
    `enter_rage` and cleared by `reset_turn`. If it's set, skip the
    auto-end check on the entry turn — the player got robbed only
    if they don't follow up next turn.

    Actually simpler: rage_started_at_round tracks when it started.
    If state.round == that round and we're checking at end of the
    same turn, give the actor a pass.
    """
    if not is_raging(actor):
        return
    attacked = bool(getattr(actor, "_rage_attacked_hostile_this_turn",
                              False))
    damaged = bool(getattr(actor, "_rage_damaged_this_turn", False))
    if attacked or damaged:
        return
    # Grace: if rage started this turn (the bonus action consumed
    # everything but they didn't get an attack in), don't end yet.
    started_at = getattr(actor, "_rage_started_at_round", None)
    if started_at == state.round:
        return
    end_rage(actor, state, reason="no_attack_no_damage")


def _barbarian_level(actor: Actor) -> int:
    """Resolve the actor's Barbarian level from their template. Returns
    0 if no barbarian level is recorded (e.g., a non-PC creature wired
    with Rage via a custom fixture). Single-class PCs from pc_schema
    have `template.levels.barbarian` set; multiclass support comes
    later."""
    levels = (actor.template or {}).get("levels") or {}
    return int(levels.get("barbarian", 0))


# ============================================================================
# Integration helpers (called from primitives + runner)
# ============================================================================

def mark_attacked_hostile(actor: Actor, target: Actor) -> None:
    """Set the per-turn flag if `actor` is raging and `target` is on
    the opposing side. Called from _attack_roll (PR #71). Safe to call
    on any attack — no-ops when not raging."""
    if not is_raging(actor):
        return
    if target is None or target.side == actor.side:
        return
    actor._rage_attacked_hostile_this_turn = True


def mark_damaged_while_raging(actor: Actor, amount: int) -> None:
    """Set the per-turn flag if `actor` is raging and took >0 damage.
    Called from _damage on the TARGET side after damage is applied.
    Safe to call when not raging."""
    if not is_raging(actor):
        return
    if amount > 0:
        actor._rage_damaged_this_turn = True


def applies_rage_damage_bonus(actor: Actor, attack_params: dict) -> bool:
    """RAW gate for the +rage_damage_bonus on a damage roll:

      - Actor is raging
      - Attack is a melee weapon attack (params.kind == 'melee')
      - Attack uses Strength as its ability (params.ability == 'str'
        or unspecified — melee weapon attacks default to STR per RAW).
        Finesse weapons that elect DEX (rapier, scimitar in a DEX
        build) DON'T get the bonus per RAW — Rage explicitly says
        "an attack using Strength".

    Returns False when not raging, when the attack is ranged, or when
    DEX is the elected ability.
    """
    if not is_raging(actor):
        return False
    kind = (attack_params or {}).get("kind", "melee")
    if kind != "melee":
        return False
    ability = (attack_params or {}).get("ability", "str")
    return ability == "str"


def applies_rage_bps_resistance(target: Actor, damage_type: str) -> bool:
    """RAW gate for the BPS resistance: target is raging AND damage
    type is bludgeoning, piercing, or slashing."""
    if not is_raging(target):
        return False
    return damage_type in ("bludgeoning", "piercing", "slashing")
