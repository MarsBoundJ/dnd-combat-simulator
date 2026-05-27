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

**Shipped:**
  - Invisible / Blinded gating (PR #47)
  - Heavy-obscurement zones (PR #48)
  - Cover (PR #48)
  - Hide action (PR #48)
  - Stealth check vs static DC 15 (PR #48 — passive Perception
    comparison still deferred)
  - Dark zones + Darkvision range (PR #50)
  - Dim light zones (PR #50 — declarable but doesn't block sight;
    Perception-disadvantage modeling deferred)

**v1 deferred (still):**
  - Truesight — bypasses Invisible + magical darkness
  - Blindsight — sees within a range regardless of vision conditions
  - Per-tile light levels (vs zone-based)
  - Active Perception check vs Hide DC (replaces static DC 15)
  - Stealth proficiency (PB addition to Hide check)
  - Magical darkness (a higher tier than ordinary dark zones —
    Devil's Sight / Truesight bypass; ordinary darkvision does NOT)

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


def _position_in_any_zone(position: tuple[int, int] | None,
                             zones: list[dict] | None) -> bool:
    """True if `position` is inside any declared axis-aligned rect zone.

    Shared helper for the three environment zone-types (heavy
    obscurement, dim light, dark). Each zone is `{x_min, x_max, y_min,
    y_max}` with inclusive boundaries. None inputs => False.
    """
    if position is None or not zones:
        return False
    x, y = position
    for z in zones:
        if (z.get("x_min", 0) <= x <= z.get("x_max", 0)
                and z.get("y_min", 0) <= y <= z.get("y_max", 0)):
            return True
    return False


def _env_zones(state: CombatState, key: str) -> list[dict]:
    """Pull `env[key]` (list of zone rects) from the encounter, or []."""
    if state is None or state.encounter is None:
        return []
    env = state.encounter.environment or {}
    return env.get(key) or []


def is_in_obscured_zone(position: tuple[int, int],
                           state: CombatState) -> bool:
    """True if `position` is inside any declared heavy-obscurement
    zone in the encounter environment (PR #48).

    Zones are axis-aligned rectangles declared as
    `encounter.environment.heavily_obscured_zones`:
      [{"x_min": int, "x_max": int, "y_min": int, "y_max": int}, ...]

    A position (x, y) is in a zone iff
    `x_min <= x <= x_max AND y_min <= y <= y_max`.

    Returns False if no zones declared / position is None.
    """
    return _position_in_any_zone(position,
                                    _env_zones(state, "heavily_obscured_zones"))


def is_in_dim_light_zone(position: tuple[int, int],
                            state: CombatState) -> bool:
    """True if `position` is inside any declared dim-light zone (PR #50).

    Zones declared as `encounter.environment.dim_light_zones` (same
    axis-aligned-rect shape as heavy obscurement / dark zones).

    Per RAW 2024: dim light is lightly obscured — disadvantage on
    Perception checks that rely on sight, but vision itself is NOT
    blocked. v1 honors that: this helper exists for completeness +
    future perception modeling, but `can_actor_see` does NOT return
    False on dim light alone.
    """
    return _position_in_any_zone(position,
                                    _env_zones(state, "dim_light_zones"))


def is_in_dark_zone(position: tuple[int, int],
                       state: CombatState) -> bool:
    """True if `position` is inside any declared dark (no-light) zone
    (PR #50). Shape matches `heavily_obscured_zones` /
    `dim_light_zones`.

    Per RAW 2024: a creature effectively suffers the Blinded condition
    when trying to see something in darkness. Darkvision treats
    darkness within range as dim light — so darkvision lets you SEE
    into a dark zone (we model this in `can_actor_see`); the
    "disadvantage on Perception" part of darkvision-into-darkness is
    deferred to a perception-check PR.
    """
    return _position_in_any_zone(position,
                                    _env_zones(state, "dark_zones"))


def can_actor_see(observer: Actor, target: Actor,
                    state: CombatState) -> bool:
    """Does `observer` have line of sight on `target`?

    v1 model (precedence order — first match wins):
      - False if `observer` is Blinded
      - False if `target` is Invisible
      - False if either is in a heavy-obscurement zone (PR #48)
        — same-zone approximated as still-blocked per RAW.
      - PR #50: dark zones (no light + no darkvision = blind):
          - If target is in a dark zone: observer sees only if their
            darkvision range covers the (observer → target) distance
            (RAW: darkvision treats darkness as dim light within
            range). Without darkvision, or beyond range, sight fails.
          - If observer is in a dark zone: observer can't see ANYTHING
            outside their darkvision range (they're in the dark
            themselves). Within darkvision range, they see fine.
        Dim light (PR #50) does NOT block sight — it imposes
        Perception disadvantage, modeled in a future perception PR.
      - True otherwise

    Truesight / Blindsight / per-tile light levels (vs zones) all
    deferred. When they land, this is the place to extend.
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
    # PR #48: heavy obscurement zones block sight. Either-side-in-zone
    # blocks per RAW (heavily obscured creatures are effectively
    # Blinded toward whatever's in the obscurement).
    if is_in_obscured_zone(target.position, state):
        return False
    if is_in_obscured_zone(observer.position, state):
        return False
    # PR #50: dark zones + darkvision. Late import to avoid a circular
    # dependency between vision.py and geometry.py (geometry imports
    # Actor from state; vision imports Actor too; both are foundational
    # — keeping geometry out of the module-level import list keeps the
    # import graph clean).
    from engine.core.geometry import distance_ft
    dv_range = int(getattr(observer, "darkvision_range_ft", 0) or 0)
    target_in_dark = is_in_dark_zone(target.position, state)
    observer_in_dark = is_in_dark_zone(observer.position, state)
    if target_in_dark or observer_in_dark:
        # Both-in-dark and one-in-dark resolve the same way: observer
        # needs darkvision that reaches the target. RAW: darkvision
        # treats darkness within range as dim light (still sees;
        # Perception disadvantage is a separate, deferred concern).
        if dv_range <= 0:
            return False
        if distance_ft(observer, target) > dv_range:
            return False
    return True
