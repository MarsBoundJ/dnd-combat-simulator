"""Vision queries (PR #47).

A single `can_actor_see(observer, target, state)` predicate that other
systems consult when asking "does X have line of sight on Y?" v1 is
deliberately minimal:

  - Returns False if `target` has the Invisible condition (no
    truesight model yet — when truesight lands, it bypasses Invisible).
  - Returns False if `observer` has the Blinded condition.
  - Returns True otherwise.

Used by:
  - `_eval_when` in modifiers.py — for `attacker_can_see(self)` /
    `target_can_see(self)` atoms. Pre-PR #47 these were unknown
    atoms returning False, which happened to give the right answer
    for the Invisible condition's specific when-clauses (`NOT
    attacker_can_see(self)` = `NOT False = True`). The new
    implementation actually computes the result, so behavior is
    correct for ALL cases (not just by coincidence).
  - `reactions.py` condition predicates — Counterspell ("you see a
    creature casting"), Hellish Rebuke ("creature you can see"),
    Protection ("creature you can see"). All three now respect RAW
    vision gates.

**v1 deferred:**
  - Truesight — bypasses Invisible
  - Blindsight — sees within a range regardless of vision conditions
  - Darkvision — needs a light-level tile system
  - Light levels (bright/dim/dark tiles) — environment-level
  - Heavily Obscured zones — needed for the Hide action
  - Stealth checks vs passive Perception — needed for active hiding
  - Cover (half / three-quarters / total) — needed for Hide too +
    ranged attack penalties

When those land, `can_actor_see` is the right place to extend.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# Conditions that, when present on the target, make them not visible
# to ordinary sight. v1 = just Invisible; future = also include any
# condition that grants concealment (e.g., a "Heavily Obscured" status).
_INVISIBILITY_CONDITIONS = frozenset({"co_invisible"})

# Conditions that, when present on the observer, prevent them from
# seeing anything. Blinded is the obvious one; future = also Unconscious
# (sleep), some petrification states, etc.
_BLINDNESS_CONDITIONS = frozenset({"co_blinded"})


def has_condition(actor: Actor, condition_id: str) -> bool:
    """True if `actor` has the named condition currently applied."""
    for c in (actor.applied_conditions or []):
        if c.get("condition_id") == condition_id:
            return True
    return False


def is_invisible(actor: Actor) -> bool:
    """True if any of the invisibility-granting conditions are active."""
    for cid in _INVISIBILITY_CONDITIONS:
        if has_condition(actor, cid):
            return True
    return False


def is_blinded(actor: Actor) -> bool:
    """True if any of the blindness-causing conditions are active."""
    for cid in _BLINDNESS_CONDITIONS:
        if has_condition(actor, cid):
            return True
    return False


def can_actor_see(observer: Actor, target: Actor,
                    state: CombatState) -> bool:
    """Does `observer` have line of sight on `target`?

    v1 model:
      - False if `observer` is Blinded
      - False if `target` is Invisible
      - True otherwise

    Truesight / Blindsight / Darkvision / light levels / Heavily
    Obscured zones all deferred. When they land, this is the place
    to extend.

    `state` is accepted for forward compatibility (light levels will
    need it) but unused in v1.
    """
    if observer is None or target is None:
        return False
    if observer.id == target.id:
        # An actor always "sees" themselves for query purposes (used
        # by self-targeted modifier when-clauses; the Invisible
        # condition's own primitives shouldn't gate on whether the
        # invisible creature can see themselves).
        return True
    if is_blinded(observer):
        return False
    if is_invisible(target):
        return False
    return True
