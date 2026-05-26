"""Grid geometry — 2D position math for melee reach / ranged range /
movement calculations.

Convention per D&D 5e 2024:
  - Positions are integer (x, y) pairs in 5-ft squares.
  - Distance uses Chebyshev metric × 5 ft (diagonals count as 5 ft, not
    the alternating 5/10 rule from earlier editions). Per 2024 PHB.
  - Movement is greedy toward a target: each "step" moves one square
    closer in both x and y until aligned; max_ft caps total movement.

**v1 scope:**
  - 2D only (no Z-axis / flying / climbing)
  - Open battlefield assumption (no walls / obstacles for pathing)
  - No cover, no difficult terrain, no line-of-sight (other than the
    existing Blinded condition handled via modifier registry)

**Deferred:**
  - 3D positions
  - Path-finding around obstacles
  - Cover detection
  - Difficult terrain speed halving
  - Alternating 5/10 diagonal rule (use Chebyshev for v1)
"""
from __future__ import annotations

from engine.core.state import Actor


SQUARE_SIZE_FT = 5


# ============================================================================
# Distance
# ============================================================================

def distance_ft(a: Actor | tuple[int, int],
                 b: Actor | tuple[int, int]) -> int:
    """Chebyshev distance × 5 ft. Accepts Actors or raw (x, y) tuples.

    Per 5e 2024: diagonals count as 5 ft, same as cardinal moves. The
    distance between (0,0) and (3,4) is max(3, 4) = 4 squares = 20 ft.
    """
    p1 = _as_position(a)
    p2 = _as_position(b)
    return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1])) * SQUARE_SIZE_FT


def is_within_ft(a: Actor | tuple[int, int],
                  b: Actor | tuple[int, int], ft: int) -> bool:
    """True if `a` is within `ft` feet of `b` (inclusive). Symmetric."""
    return distance_ft(a, b) <= ft


# ============================================================================
# Movement
# ============================================================================

def move_toward(mover: Actor, target: Actor | tuple[int, int],
                 max_ft: int, stop_at_ft: int = 0) -> int:
    """Move `mover` toward `target` by up to `max_ft` ft (in 5-ft steps).

    Greedy: each step moves one square toward the target in both axes
    where positions differ. Mover stops as soon as it's within
    `stop_at_ft` of the target — defaults to 0 (move all the way to
    the target's square, used for non-combat positioning), but the
    runner's engage step passes the actor's reach so creatures land
    adjacent for melee instead of stacking on the target.

    Returns the number of feet actually moved (0 if already in range
    or if max_ft < 5).

    Mutates mover.position in place. Pure aside from that mutation.
    """
    if max_ft < SQUARE_SIZE_FT:
        return 0
    if distance_ft(mover, target) <= stop_at_ft:
        return 0   # already in desired range
    target_pos = _as_position(target)
    max_squares = max_ft // SQUARE_SIZE_FT
    moved_squares = 0
    while moved_squares < max_squares:
        if distance_ft(mover, target) <= stop_at_ft:
            break
        x, y = mover.position
        tx, ty = target_pos
        dx = _step_toward(x, tx)
        dy = _step_toward(y, ty)
        if dx == 0 and dy == 0:
            break
        mover.position = (x + dx, y + dy)
        moved_squares += 1
    return moved_squares * SQUARE_SIZE_FT


def required_movement_ft(mover: Actor, target: Actor | tuple[int, int],
                          reach_ft: int) -> int:
    """How many ft `mover` would need to move to bring `target` within
    `reach_ft`. Returns 0 if already in reach.

    Same step-based Chebyshev math as `move_toward` but doesn't mutate
    state. Used by the runner to decide whether to move and by how much.
    """
    current = distance_ft(mover, target)
    if current <= reach_ft:
        return 0
    # Each square of movement reduces distance by exactly 5 ft under
    # Chebyshev (we move diagonally toward the target).
    deficit = current - reach_ft
    # ceil(deficit / 5)
    squares_needed = (deficit + SQUARE_SIZE_FT - 1) // SQUARE_SIZE_FT
    return squares_needed * SQUARE_SIZE_FT


# ============================================================================
# Helpers
# ============================================================================

def _as_position(x: Actor | tuple[int, int]) -> tuple[int, int]:
    """Accept either an Actor (uses .position) or a raw tuple."""
    if isinstance(x, tuple):
        return x
    return x.position


def _step_toward(current: int, target: int) -> int:
    """Return -1, 0, or +1 — the single-square step that brings
    current toward target."""
    if current < target:
        return 1
    if current > target:
        return -1
    return 0
