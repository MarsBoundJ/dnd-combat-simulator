"""Bardic Inspiration — the Bard's signature die mechanic.

A Bard grants an ally a Bardic Inspiration die (d6 → d8 → d10 → d12 by
Bard level). The holder can add that die to a failed d20 Test to turn a
failure into a success. The die is one-shot (expended when rolled).

This module owns:
  - register_inspiration_die / find_inspiration_die / clear: the held-die
    marker lifecycle (a modifier on the recipient ally).
  - maybe_add_to_attack: the post-roll self-add hook called from
    _attack_roll, modeled on engine.core.racial_traits.lucky_d20 (a free,
    held-resource post-roll modification — not a reaction).

RAW scope: the holder's add is modeled on the two combat d20 Tests —
ATTACK ROLLS (maybe_add_to_attack, hooked in _attack_roll) and SAVING
THROWS (maybe_add_to_save, hooked in _forced_save). Ability checks (the
third d20-Test kind) are exercised outside combat and are a follow-on.

Cutting Words (College of Lore) is the inverse — the Bard spends a use
to SUBTRACT a die from an enemy's roll — and lives in the
`cutting_words_resolve` primitive (it rides the existing
attack_roll_pending reaction hook), not here.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState

INSPIRATION_DIE_PRIMITIVE = "bardic_inspiration_die"


def die_max(die: str) -> int:
    """Max face of a die string like 'd8' → 8. Defaults to 6."""
    s = str(die).lower().lstrip("d")
    return int(s) if s.isdigit() else 6


def register_inspiration_die(target: Actor, die: str, source_id: str,
                               state: CombatState) -> None:
    """Attach a held Bardic Inspiration die marker to `target` (an ally).

    A creature can hold only one Bardic Inspiration die at a time (RAW),
    so registering replaces any existing marker."""
    clear_inspiration_die(target)
    target.active_modifiers.append({
        "primitive": INSPIRATION_DIE_PRIMITIVE,
        "params": {"die": die},
        # RAW: usable within the next hour. The sim has no 1-hour timer;
        # until_short_rest is the closest existing lifetime bucket.
        "lifetime": "until_short_rest",
        "source": {
            "type": "feature",
            "id": "f_bardic_inspiration",
            "named_effect": "bardic_inspiration",
            "source_creature_id": source_id,
        },
        "applied_at_round": state.round,
        "owner_id": target.id,
    })
    state.event_log.append({
        "event": "bardic_inspiration_granted",
        "target": target.id, "source": source_id, "die": die,
    })


def find_inspiration_die(actor: Actor) -> dict | None:
    for m in actor.active_modifiers:
        if m.get("primitive") == INSPIRATION_DIE_PRIMITIVE:
            return m
    return None


def clear_inspiration_die(actor: Actor) -> None:
    actor.active_modifiers = [
        m for m in actor.active_modifiers
        if m.get("primitive") != INSPIRATION_DIE_PRIMITIVE
    ]


def _spend_die_to_beat(actor: Actor, total: int, threshold: int,
                         state: CombatState, rng: random.Random,
                         context: dict) -> int:
    """Shared core for the post-roll self-add. If `total` is below
    `threshold` but the held Bardic Inspiration die could close the gap,
    spend it (one-shot) and return the boosted total; otherwise return
    `total` unchanged (the holder adds only when it can matter and keeps
    the die otherwise — RAW optimization)."""
    if total >= threshold:
        return total
    marker = find_inspiration_die(actor)
    if marker is None:
        return total
    die = (marker.get("params") or {}).get("die", "d6")
    if total + die_max(die) < threshold:
        return total  # can't help even on a max roll — keep the die
    roll = rng.randint(1, die_max(die))
    new_total = total + roll
    clear_inspiration_die(actor)
    state.event_log.append({
        "event": "bardic_inspiration_added",
        "actor": actor.id, "die": die, "roll": roll,
        "old_total": total, "new_total": new_total,
        **context,
    })
    return new_total


def maybe_add_to_attack(actor: Actor, total: int, effective_ac: int,
                         is_crit: bool, state: CombatState,
                         rng: random.Random) -> int:
    """Post-roll self-add for an attacker holding a Bardic Inspiration die.
    If the attack would MISS but the die could turn it into a hit, spend it
    and add the roll. No-op on a crit (already the best outcome)."""
    if is_crit:
        return total
    return _spend_die_to_beat(actor, total, effective_ac, state, rng,
                                {"effective_ac": effective_ac, "kind": "attack"})


def maybe_add_to_save(actor: Actor, total: int, dc: int,
                        state: CombatState, rng: random.Random) -> int:
    """Post-roll self-add for a creature holding a Bardic Inspiration die
    making a saving throw. If the save would FAIL but the die could turn it
    into a success (total + die >= DC), spend it and add the roll. Returns
    the (possibly increased) total. The caller re-derives the outcome."""
    return _spend_die_to_beat(actor, total, dc, state, rng,
                                {"dc": dc, "kind": "save"})
