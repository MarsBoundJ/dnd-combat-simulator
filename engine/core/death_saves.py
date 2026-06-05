"""PC downed / death-saving-throw / revival lifecycle (2024 RAW).

When a death-save creature (a PC) drops to 0 HP it does NOT die — it falls
UNCONSCIOUS and is DYING. At the start of each of its turns it rolls a death
saving throw (DC 10): >= 10 is a success, < 10 a failure; a natural 20 revives
it at 1 HP, a natural 1 counts as two failures. Three successes => STABLE
(still at 0 HP, unconscious, no longer rolling). Three failures => DEAD.
Taking damage while dying is a failure (two on a critical hit). Massive damage
— the leftover after dropping to 0 is >= the creature's HP maximum — is
instant death even for a PC.

Monsters die outright at 0 HP (DM discretion, RAW), so `uses_death_saves`
gates the whole system to `side == "pc"`. Revival-on-heal lives in the heal
primitive (Stage 2); this module owns the dying lifecycle + the turn-start
save roll. The unconscious *condition* effects (attackers have advantage,
auto-fail STR/DEX saves) are a documented follow-up — Stage 1 models the
death-save lifecycle itself.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState

DEATH_SAVE_DC = 10
SUCCESSES_TO_STABILIZE = 3
FAILURES_TO_DIE = 3


def uses_death_saves(actor: Actor) -> bool:
    """True for creatures that fall unconscious and roll death saves at 0 HP
    (PCs). Monsters die outright. Gated on side == "pc"; a template may also
    opt in via `uses_death_saves: true` (e.g. a named NPC ally)."""
    if getattr(actor, "side", None) == "pc":
        return True
    return bool((actor.template or {}).get("uses_death_saves"))


def _end_concentration_if_any(actor: Actor, state: CombatState) -> None:
    if actor.concentration_on is not None:
        from engine.core.concentration import end_concentration
        end_concentration(actor, state, reason="downed")


def enter_dying(actor: Actor, state: CombatState) -> None:
    """Drop `actor` to 0 HP, unconscious and dying, with a fresh death-save
    tally. Ends any concentration (unconscious can't maintain it)."""
    actor.hp_current = 0
    actor.is_dying = True
    actor.is_stable = False
    actor.death_save_successes = 0
    actor.death_save_failures = 0
    _end_concentration_if_any(actor, state)
    state.event_log.append({"event": "downed_dying", "actor": actor.id})


def revive(actor: Actor, hp: int, state: CombatState, *, reason: str) -> None:
    """Bring a dying/stable creature back to consciousness at `hp` (>= 1),
    clearing the dying state and the death-save tally."""
    actor.is_dying = False
    actor.is_stable = False
    actor.death_save_successes = 0
    actor.death_save_failures = 0
    actor.is_dead = False
    actor.hp_current = max(1, min(hp, actor.hp_max))
    state.event_log.append({"event": "revived", "actor": actor.id,
                            "hp": actor.hp_current, "reason": reason})


def die(actor: Actor, state: CombatState, *, reason: str) -> None:
    """Finalize death — the dying creature has failed out (or taken massive
    damage). Clears the dying flag and ends concentration."""
    actor.is_dying = False
    actor.is_stable = False
    actor.is_dead = True
    _end_concentration_if_any(actor, state)
    state.event_log.append({"event": "death_saves_failed", "actor": actor.id,
                            "reason": reason})


def stabilize(actor: Actor, state: CombatState) -> None:
    """Mark a dying creature STABLE — still at 0 HP and unconscious, but no
    longer rolling death saves (3 successes, or an ally's Medicine/Spare the
    Dying). Stays out of the fight until healed."""
    if not actor.is_dying:
        return
    actor.is_stable = True
    state.event_log.append({"event": "stabilized", "actor": actor.id})


def is_massive_damage(overflow: int, hp_max: int) -> bool:
    """RAW instant-death: the leftover damage after dropping to 0 is >= the
    creature's HP maximum."""
    return hp_max > 0 and overflow >= hp_max


def damage_while_dying(actor: Actor, state: CombatState, *,
                       is_crit: bool = False) -> None:
    """A hit on an already-dying creature is an automatic death-save failure
    (two on a critical hit). Three failures => death."""
    if not actor.is_dying or actor.is_dead:
        return
    actor.death_save_failures += 2 if is_crit else 1
    state.event_log.append({
        "event": "death_save", "actor": actor.id, "trigger": "damage",
        "is_crit": is_crit, "successes": actor.death_save_successes,
        "failures": actor.death_save_failures,
    })
    if actor.death_save_failures >= FAILURES_TO_DIE:
        die(actor, state, reason="damage_while_dying")


def resolve_turn_start(actor: Actor, state: CombatState,
                       rng: random.Random) -> None:
    """At the start of a dying creature's turn, roll a death saving throw.
    No-op if the creature isn't dying, is already stable, or is dead.

    DC 10: >= 10 success, < 10 failure. Nat 20 -> revive at 1 HP. Nat 1 ->
    two failures. 3 successes -> stable; 3 failures -> dead.
    """
    if (not actor.is_dying) or actor.is_stable or actor.is_dead:
        return
    d20 = rng.randint(1, 20)
    if d20 == 20:
        revive(actor, 1, state, reason="death_save_nat20")
        return
    if d20 == 1:
        actor.death_save_failures += 2
        outcome = "fail_nat1"
    elif d20 >= DEATH_SAVE_DC:
        actor.death_save_successes += 1
        outcome = "success"
    else:
        actor.death_save_failures += 1
        outcome = "fail"
    state.event_log.append({
        "event": "death_save", "actor": actor.id, "trigger": "turn_start",
        "d20": d20, "outcome": outcome,
        "successes": actor.death_save_successes,
        "failures": actor.death_save_failures,
    })
    if actor.death_save_failures >= FAILURES_TO_DIE:
        die(actor, state, reason="three_failures")
    elif actor.death_save_successes >= SUCCESSES_TO_STABILIZE:
        stabilize(actor, state)
