"""Positioning & AoE-targeting AI (see docs/positioning-model.md).

Phase 1a — the **AoE coverage routine**: the shared "where do I aim this
area effect to deliver the most eHP?" function used by

  - monster offense (pick the best breath / Fireball placement), and
  - the PC AoE-exposure positioning term (run the boss's routine
    adversarially to find the worst it can do to a formation).

It enumerates a small, target-relevant candidate set of placements and
ranks them with `offensive_ehp_aoe`, which is already eHP-denominated and
already nets friendly fire + wall occlusion — so ranking by it satisfies
"rank by eHP, not raw target count" for free.

Phase-1a scope (intentionally minimal, purely additive — nothing calls
this yet):
  - cone / line: apex = the attacker's current square; orientation = the 8
    grid directions (the exact candidate set on an 8-direction grid).
  - sphere / emanation: origin candidates = living enemies within cast
    range (anchor-on-target), plus self for emanations.

Deferred (documented in the model doc): movement apexes (moving before
placing), straddled lines (needs an `actors_in_line` extension), and free
(continuous) orientation. Those are §9/§11 follow-ups.
"""
from __future__ import annotations

from engine.core.geometry import is_within_ft
from engine.core.state import Actor, CombatState

# The 8 grid directions — the exact candidate orientation set for cone/line
# AoEs on an 8-direction grid (no continuous angles yet).
_EIGHT_DIRS: tuple[tuple[int, int], ...] = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)


def max_aoe_coverage(action: dict, attacker: Actor, state: CombatState,
                      *, apex: tuple[int, int] | None = None) -> dict | None:
    """Best placement of `action`'s area effect, maximizing delivered eHP.

    Returns ``{"origin": (x, y), "direction": (dx, dy) | None, "ehp": float}``
    for the best placement, or ``None`` if the action has no usable area or
    no placement delivers positive eHP (e.g. it would only catch allies).

    Scoring is delegated to `offensive_ehp_aoe` (eHP, friendly-fire- and
    wall-occlusion-aware), so the winner is the eHP-max, not the
    most-targets-hit.
    """
    from engine.ai.ehp_scoring import offensive_ehp_aoe

    area = action.get("area") or {}
    shape = (area.get("shape") or "sphere").lower()
    origin0 = tuple(apex) if apex is not None else tuple(attacker.position)

    candidates: list[tuple[tuple[int, int], tuple[int, int] | None]] = []
    if shape in ("cone", "line"):
        # Apex fixed at the attacker's square (movement deferred); try every
        # grid orientation.
        candidates = [(origin0, d) for d in _EIGHT_DIRS]
    elif shape in ("sphere", "emanation"):
        cast_range = int(area.get("range_ft", 60))
        living_enemies = [a for a in state.encounter.actors
                          if a.is_alive() and a.side != attacker.side]
        seen: set[tuple[int, int]] = set()
        for e in living_enemies:
            o = tuple(e.position)
            if o not in seen and is_within_ft(attacker, o, cast_range):
                seen.add(o)
                candidates.append((o, None))
        if shape == "emanation" and origin0 not in seen:
            candidates.append((origin0, None))
    else:
        return None

    best: dict | None = None
    for origin, direction in candidates:
        ehp = offensive_ehp_aoe(attacker, origin, action, state,
                                 direction=direction)
        if best is None or ehp > best["ehp"]:
            best = {"origin": origin, "direction": direction, "ehp": ehp}

    if best is None or best["ehp"] <= 0:
        return None
    return best
