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
  - Stealth check (PR #48; PR #51 added proficiency PB + recorded
    stealth_total on the resulting Invisible condition)
  - Dark zones + Darkvision range (PR #50)
  - Dim light zones (PR #50 — declarable but doesn't block sight;
    Perception-disadvantage modeling deferred)
  - Passive Perception auto-spot for Hide-source Invisible (PR #51):
    `observer.passive_perception` >= hider's stealth_total ⇒ visible
    (spell-source Invisible still bypasses Perception per RAW)

**v1 deferred (still):**
  - Truesight — bypasses Invisible + magical darkness
  - Blindsight — sees within a range regardless of vision conditions
  - Per-tile light levels (vs zone-based)
  - Active Perception search-as-action (vs passive PP, which is now
    automatic)
  - Magical darkness (a higher tier than ordinary dark zones —
    Devil's Sight / Truesight bypass; ordinary darkvision does NOT)
  - Skill expertise (double PB on Stealth / Perception)

When those land, `can_actor_see` is the right place to extend.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# Conditions that, when present on the target, make them not visible
# to ordinary sight. v1 = just Invisible; future = also include any
# condition that grants concealment (e.g., a "Heavily Obscured" status).
_INVISIBILITY_CONDITIONS = frozenset({"co_invisible"})

# Source-action ids whose Invisible condition CAN be bypassed by a
# sufficiently-perceptive observer (PR #51). Spell-source Invisible
# (Invisibility / Greater Invisibility) is NOT in this set — those
# bypass passive Perception per RAW. Only physical Hide can be seen
# through by a sharp-eyed observer.
_PERCEPTION_BYPASSABLE_INVISIBLE_SOURCES = frozenset({"a_hide"})

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


def _hide_source_invisibilities(actor: Actor) -> list[dict]:
    """Return co_invisible conditions on `actor` whose source action id
    is in the perception-bypassable set (PR #51 — currently just
    a_hide). Each dict carries the recorded `stealth_total` for the
    auto-spot comparison. Empty list when actor has no Hide-source
    Invisible (either not invisible at all, or invisible from a spell).
    """
    out: list[dict] = []
    for c in (actor.applied_conditions or []):
        if c.get("condition_id") != "co_invisible":
            continue
        if c.get("source_action_id") in _PERCEPTION_BYPASSABLE_INVISIBLE_SOURCES:
            out.append(c)
    return out


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
      - If `target` has Invisible:
          - PR #51: Hide-source Invisible (source_action_id=a_hide)
            can be bypassed by `observer.passive_perception` >=
            target's recorded `stealth_total`. Spell-source Invisible
            (Invisibility / Greater Invisibility) is NOT bypassable —
            those return False unconditionally.
          - If bypassed, fall through to the remaining gates (fog /
            darkness still block sight even after a successful
            passive-Perception spot).
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

    Truesight / Blindsight / per-tile light levels (vs zones) /
    active-Perception-search-as-action all deferred. When they
    land, this is the place to extend.
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
        # PR #51: Hide-source Invisible can be auto-spotted by an
        # observer whose passive Perception meets or beats the
        # hider's recorded Stealth total. Spell-source Invisible
        # (Invisibility / Greater Invisibility) bypasses Perception
        # per RAW — those go straight to False below.
        hide_conditions = _hide_source_invisibilities(target)
        if not hide_conditions:
            return False
        observer_pp = int(getattr(observer, "passive_perception", 10) or 10)
        # If ANY Hide-source instance still beats the observer, target
        # remains hidden. (v1 actors only ever carry one Hide-source
        # Invisible at a time; loop kept for robustness.)
        all_spotted = all(
            observer_pp >= int(c.get("stealth_total", 9999))
            for c in hide_conditions
        )
        if not all_spotted:
            return False
        # Else: fall through — observer beat the Stealth roll, so the
        # remaining vision checks (obscurement / darkness) still apply.
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
