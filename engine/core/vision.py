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
  - Truesight (PR #52) — bypasses Invisible (both Hide-source and
    spell-source) + magical darkness + ordinary darkness within
    range. Does NOT bypass heavy obscurement (fog).
  - Blindsight (PR #52) — dominant override; bypasses everything
    visual (Invisible / fog / darkness / magical darkness / Blinded
    self) within range.
  - Magical-darkness zones (PR #52) — only Truesight pierces; ordinary
    darkvision does NOT.

**v1 deferred (still):**
  - Devil's Sight (Warlock invocation) — bypasses magical darkness
    without truesight; needs a new flag distinct from truesight
  - Per-tile light levels (vs zone-based)
  - Active Perception search-as-action (vs passive PP, which is
    automatic)
  - Skill expertise (double PB on Stealth / Perception)
  - Illusion auto-detection + shapechanger original-form (parts of
    truesight RAW we can't model until illusions / shapechangers
    are in the engine)

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
    """True if `position` is inside any declared environment zone.

    Shared helper for the environment zone-types (heavy obscurement,
    dim light, dark, magical dark). Two zone shapes supported:

      - **Axis-aligned rect** (default; legacy shape from PR #48 / #50 /
        #52). Schema: `{x_min, x_max, y_min, y_max}` with inclusive
        boundaries. Used when fixture authors declare zones explicitly.
      - **Sphere** (PR #60). Schema: `{shape: "sphere", center: [x, y],
        radius_ft: int}`. Used when persistent_aura-creating spells
        (Darkness, future Hunger of Hadar) auto-declare a zone at
        cast time. Chebyshev distance vs `radius_ft // 5` matches
        the engine's grid distance convention (diagonals count as
        5 ft per 5e 2024).

    None inputs (position or zones) => False.
    """
    if position is None or not zones:
        return False
    x, y = position
    for z in zones:
        # PR #60: sphere shape for spell-created zones
        if z.get("shape") == "sphere":
            center = z.get("center") or (0, 0)
            cx, cy = int(center[0]), int(center[1])
            radius_squares = int(z.get("radius_ft", 0)) // 5
            if max(abs(x - cx), abs(y - cy)) <= radius_squares:
                return True
            continue
        # Legacy axis-aligned rect
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


def is_in_magical_dark_zone(position: tuple[int, int],
                               state: CombatState) -> bool:
    """True if `position` is inside any declared magical-darkness zone
    (PR #52). Shape matches `dark_zones`; same axis-aligned rects.

    Magical darkness is a stricter form of darkness — RAW: ordinary
    darkvision does NOT pierce it. Only Truesight (and future Devil's
    Sight, the Warlock invocation) can see through. Created by the
    Darkness spell + Hunger of Hadar etc.; fixture authors declare
    the zone directly until those spells land as persistent_aura
    feature-files.
    """
    return _position_in_any_zone(position,
                                    _env_zones(state, "magical_dark_zones"))


def can_actor_see(observer: Actor, target: Actor,
                    state: CombatState) -> bool:
    """Does `observer` have line of sight on `target`?

    v1 model (precedence order — first match wins):
      0. **Self-sees-self short-circuit** (modifier when-clauses).
      1. **Blindsight bypass (PR #52)** — if `observer.blindsight_range_ft
         > 0` AND target is within that range, return True. Blindsight
         doesn't rely on sight at all, so it pierces every visual
         obstruction (Invisible, fog, darkness, magical darkness,
         Blinded condition on self, etc.). This is the dominant
         override.
      2. False if `observer` is Blinded (and didn't have blindsight to
         override above).
      3. If `target` has Invisible:
           - **PR #52: Truesight in range** bypasses Invisible
             entirely (both Hide-source and spell-source).
           - PR #51: Hide-source Invisible (source_action_id=a_hide)
             can be bypassed by `observer.passive_perception` >=
             target's recorded `stealth_total`. Spell-source Invisible
             (Invisibility / Greater Invisibility) is NOT
             passive-Perception bypassable.
           - If bypassed (either way), fall through to the remaining
             gates (fog / darkness still block sight even after a
             successful spot).
      4. False if either is in a heavy-obscurement zone (PR #48) —
         same-zone approximated as still-blocked per RAW. **Truesight
         does NOT bypass heavy obscurement** (fog is physical, not
         magical) — only Blindsight does, handled at step 1.
      5. **PR #52: magical_dark_zones** (Darkness spell etc.):
           - Ordinary darkvision does NOT pierce magical darkness.
           - Only Truesight in range (or Blindsight, handled above)
             bypasses.
      6. PR #50: ordinary dark zones (no light):
           - Truesight in range OR Darkvision in range bypasses.
           - Without either, return False.
        Dim light (PR #50) does NOT block sight — it imposes
        Perception disadvantage, modeled in a future perception PR.
      7. True otherwise.

    Devil's Sight (Warlock invocation — magical-darkness-bypass without
    truesight) / illusion bypass / shapechanger original-form / per-tile
    light levels / active-Perception-search-as-action all deferred.
    """
    if observer is None or target is None:
        return False
    if observer.id == target.id:
        # An actor always "sees" themselves for query purposes (used
        # by self-targeted modifier when-clauses; the Invisible
        # condition's own primitives shouldn't gate on whether the
        # invisible creature can see themselves).
        return True
    # Late import to avoid a circular dependency between vision.py
    # and geometry.py (geometry imports Actor from state; vision
    # imports Actor too; both are foundational — keeping geometry
    # out of the module-level import list keeps the import graph
    # clean).
    from engine.core.geometry import distance_ft

    # 1. Blindsight bypass (dominant override). Blindsight perceives
    # surroundings without sight, so Invisible / fog / darkness / etc.
    # all yield to it within range.
    bs_range = int(getattr(observer, "blindsight_range_ft", 0) or 0)
    if bs_range > 0 and distance_ft(observer, target) <= bs_range:
        return True

    if is_blinded(observer):
        return False

    # Truesight range used by multiple gates below — compute once.
    ts_range = int(getattr(observer, "truesight_range_ft", 0) or 0)
    has_truesight_to_target = (
        ts_range > 0 and distance_ft(observer, target) <= ts_range
    )

    if is_invisible(target):
        if not has_truesight_to_target:
            # PR #51: Hide-source Invisible can be auto-spotted via
            # passive Perception. Spell-source Invisible has no roll
            # to beat; only Truesight pierces it.
            hide_conditions = _hide_source_invisibilities(target)
            if not hide_conditions:
                return False
            observer_pp = int(getattr(observer, "passive_perception", 10) or 10)
            all_spotted = all(
                observer_pp >= int(c.get("stealth_total", 9999))
                for c in hide_conditions
            )
            if not all_spotted:
                return False
        # Else (truesight or passive-Perception spot): fall through —
        # the remaining vision checks (obscurement / darkness) still
        # apply.

    # PR #48: heavy obscurement zones block sight regardless of
    # Truesight. RAW: truesight sees through magical darkness +
    # invisibility, NOT through physical obscuring substances. Only
    # Blindsight pierces fog, and that's handled above.
    if is_in_obscured_zone(target.position, state):
        return False
    if is_in_obscured_zone(observer.position, state):
        return False

    # PR #52: magical darkness zones — only Truesight bypasses.
    # Ordinary darkvision is explicitly NOT sufficient.
    target_in_mdark = is_in_magical_dark_zone(target.position, state)
    observer_in_mdark = is_in_magical_dark_zone(observer.position, state)
    if target_in_mdark or observer_in_mdark:
        if not has_truesight_to_target:
            return False

    # PR #50: ordinary dark zones — Truesight OR Darkvision bypasses.
    dv_range = int(getattr(observer, "darkvision_range_ft", 0) or 0)
    target_in_dark = is_in_dark_zone(target.position, state)
    observer_in_dark = is_in_dark_zone(observer.position, state)
    if target_in_dark or observer_in_dark:
        if has_truesight_to_target:
            pass    # truesight covers it
        elif dv_range > 0 and distance_ft(observer, target) <= dv_range:
            pass    # darkvision covers it
        else:
            return False
    return True
