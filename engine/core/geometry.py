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


def actors_in_radius(origin: tuple[int, int], radius_ft: int,
                       actors: list[Actor]) -> list[Actor]:
    """Return all actors whose position is within `radius_ft` of `origin`.

    Uses the same Chebyshev metric as `distance_ft`. A 20-ft radius
    sphere centered at (0, 0) catches all squares (x, y) with
    max(|x|, |y|) ≤ 4 — a 9 × 9 square envelope per 5e 2024 sphere/cube
    convention. Order preserved from input list.

    Living-status filtering is left to the caller; this is pure
    geometry.
    """
    return [a for a in actors if distance_ft(a.position, origin) <= radius_ft]


def actors_in_cube(origin: tuple[int, int], size_ft: int,
                     actors: list[Actor]) -> list[Actor]:
    """Return all actors whose position is within a cube of side
    `size_ft` centered on `origin`.

    Cube semantics (RAW 2024): "centered on a point" — the cube
    extends size_ft / 2 in each direction from origin. In our 5-ft
    grid that's `size_ft // 10` squares per half-extent (integer
    truncation):
      - 5-ft cube  → half=0 → only the origin square
      - 10-ft cube → half=1 → 3×3 (origin + 8 neighbors)
      - 20-ft cube → half=2 → 5×5

    This matches Cloud of Daggers (5-ft cube = 1 square) and Sleet
    Storm-class spells. Returns actors in arbitrary-order list
    preserving input order.
    """
    half = size_ft // 10
    return [a for a in actors
            if abs(a.position[0] - origin[0]) <= half
            and abs(a.position[1] - origin[1]) <= half]


def unit_direction(from_pos: tuple[int, int],
                     to_pos: tuple[int, int]) -> tuple[int, int]:
    """Snap a vector from `from_pos` to `to_pos` to one of 8 cardinal/
    ordinal grid directions: (1,0), (-1,0), (0,1), (0,-1), and the
    four diagonals. Returns (0, 0) if the positions are identical.

    Used by cone / line AoE candidate generation to snap the caster's
    "I'm pointing this spell at that enemy" intent to a grid-aligned
    direction.
    """
    dx = to_pos[0] - from_pos[0]
    dy = to_pos[1] - from_pos[1]
    if dx == 0 and dy == 0:
        return (0, 0)
    # Sign each axis to {-1, 0, +1}. Ties at exactly 0 produce cardinals.
    sx = (dx > 0) - (dx < 0)
    sy = (dy > 0) - (dy < 0)
    return (sx, sy)


def actors_in_cone(origin: tuple[int, int], direction: tuple[int, int],
                     length_ft: int, actors: list[Actor]) -> list[Actor]:
    """Return actors caught in a cone of `length_ft` from `origin` in
    `direction`.

    5e RAW cone semantics: a cone's length equals its width at the
    far end (half-angle ≈ 26.6°). On a grid this approximates to:
    a square is in the cone if its FORWARD projection onto the
    direction vector is in (0, L] AND its perpendicular distance from
    the cone axis is at most FORWARD × 0.5 (with a small grid-snap
    tolerance — see implementation).

    The origin square itself is excluded (RAW: cone originates AT
    the origin and extends OUTWARD).

    Direction must be one of the 8 unit_direction outputs. (0, 0)
    direction returns [].
    """
    if direction == (0, 0):
        return []
    length_squares = length_ft // SQUARE_SIZE_FT
    if length_squares <= 0:
        return []
    out: list[Actor] = []
    for actor in actors:
        if actor.position == origin:
            continue  # origin square excluded
        if _in_cone(actor.position, origin, direction, length_squares):
            out.append(actor)
    return out


def _in_cone(square: tuple[int, int], origin: tuple[int, int],
              direction: tuple[int, int], length_squares: int) -> bool:
    """Test whether a single grid square is in a cone.

    Cone math (snapped to 8 directions): we project the displacement
    (square - origin) onto the direction vector to get FORWARD
    distance, and onto the perpendicular axis to get LATERAL. A square
    is in the cone iff:
      - FORWARD in [1, length_squares]
      - |LATERAL| × 2 <= FORWARD + 0.5  (with grid-snap tolerance)

    The +0.5 tolerance ensures the cone "boundary" squares (lateral
    equal to forward/2 in continuous math) are included on the grid.
    """
    dx = square[0] - origin[0]
    dy = square[1] - origin[1]

    # Project onto direction (cardinal/ordinal). For diagonals, both
    # components contribute. Use the Chebyshev-aligned forward distance:
    # forward = "steps in the direction's primary axis (or both axes
    # for diagonals)" measured by max along the relevant components.
    # Simpler: forward = max(dx * dir_x, dy * dir_y) but only when the
    # signs match. We compute forward + lateral in the rotated frame.

    if direction[0] == 0 or direction[1] == 0:
        # Cardinal direction (one axis is 0)
        if direction[0] != 0:
            forward = dx * direction[0]
            lateral = abs(dy)
        else:
            forward = dy * direction[1]
            lateral = abs(dx)
    else:
        # Diagonal direction — both components ±1. Rotate displacement
        # into the diagonal frame: forward = (dx*dir_x + dy*dir_y)/2
        # (along the diagonal), lateral = |dx*dir_x - dy*dir_y|/2
        # (perpendicular). Both reductions are exact integers since
        # dx*dir_x ± dy*dir_y has the same parity as dx + dy.
        a = dx * direction[0] + dy * direction[1]
        b = dx * direction[0] - dy * direction[1]
        # In diagonal frames the "forward" distance is half the sum
        # along the diagonal, but for grid-cone purposes we use a/2
        # only when a >= 0. Easier intuition: just check if both dx
        # and dy go in the direction's signs at all.
        if dx * direction[0] < 0 or dy * direction[1] < 0:
            return False
        # On the diagonal axis: forward = max of |dx|, |dy| (Chebyshev
        # in the rotated frame). Lateral = min.
        ax = abs(dx)
        ay = abs(dy)
        forward = max(ax, ay)
        lateral = min(ax, ay) - 0   # for a perfect diagonal lateral = 0
        # In the rotated diagonal frame, the lateral distance is the
        # difference between ax and ay (or 0 for a square exactly on the
        # diagonal). Use that for the cone check.
        lateral = abs(ax - ay)

    if forward < 1 or forward > length_squares:
        return False
    # Cone half-width condition: lateral <= forward * 0.5 (with grid
    # tolerance). Equivalent to 2*lateral <= forward + 1 in integers.
    return 2 * lateral <= forward + 1


def actors_in_line(origin: tuple[int, int], direction: tuple[int, int],
                     length_ft: int, width_ft: int,
                     actors: list[Actor]) -> list[Actor]:
    """Return actors caught in a line of `length_ft` × `width_ft` from
    `origin` in `direction`.

    Line semantics (v1):
      - A square is in the line if its FORWARD projection in `direction`
        is in [1, length_squares] AND its perpendicular distance from
        the line axis is at most (width_squares - 1) / 2.
      - Width of 5 ft = 1 square wide (just the axis); 10 ft = 3 wide
        (axis ± 1); 15 ft = 3 wide too (rounded for grid).
      - Origin square excluded (line originates AT origin, extends out).
      - For diagonal directions, the line is one square wide along the
        diagonal (matches Lightning Bolt practical play).

    Direction must be one of the 8 unit_direction outputs. (0, 0)
    direction returns [].
    """
    if direction == (0, 0):
        return []
    length_squares = length_ft // SQUARE_SIZE_FT
    width_squares = width_ft // SQUARE_SIZE_FT
    if length_squares <= 0 or width_squares <= 0:
        return []
    out: list[Actor] = []
    half_width = (width_squares - 1) // 2   # int, RAW: ±half from axis
    for actor in actors:
        if actor.position == origin:
            continue
        if _in_line(actor.position, origin, direction, length_squares,
                     half_width):
            out.append(actor)
    return out


def _in_line(square: tuple[int, int], origin: tuple[int, int],
              direction: tuple[int, int], length_squares: int,
              half_width_squares: int) -> bool:
    """Test whether a single grid square is in a line.

    For cardinal direction (e.g., east (1, 0)):
      - forward = dx * dir_x, lateral = |dy|
      - in line iff forward in [1, L] and lateral <= half_width

    For diagonal direction:
      - The diagonal line is one square wide on the rotated diagonal —
        we accept only squares directly on the diagonal (lateral = 0
        in the rotated frame).
    """
    dx = square[0] - origin[0]
    dy = square[1] - origin[1]
    if direction[0] == 0 or direction[1] == 0:
        # Cardinal
        if direction[0] != 0:
            forward = dx * direction[0]
            lateral = abs(dy)
        else:
            forward = dy * direction[1]
            lateral = abs(dx)
        return (1 <= forward <= length_squares
                and lateral <= half_width_squares)
    # Diagonal
    if dx * direction[0] < 0 or dy * direction[1] < 0:
        return False
    ax = abs(dx)
    ay = abs(dy)
    if ax != ay:
        return False   # off the diagonal axis
    return 1 <= ax <= length_squares


def push_creature(pusher: Actor, target: Actor, distance_ft_amount: int) -> int:
    """Push `target` straight away from `pusher` up to `distance_ft_amount`
    feet (PR #58 — Push weapon mastery).

    Direction: snapped to the 8-direction unit vector from pusher's
    position to target's position (via `unit_direction`). If pusher
    and target are stacked on the same square (rare), the helper
    returns 0 (no defined direction).

    Movement is step-wise (5 ft per square). Each step moves the
    target one square in the push direction. v1 doesn't handle
    collision with other actors or map edges — it always moves the
    full requested distance. Tracked as a deferred refinement.

    Returns the number of feet actually pushed.
    """
    direction = unit_direction(pusher.position, target.position)
    if direction == (0, 0):
        return 0
    max_squares = distance_ft_amount // SQUARE_SIZE_FT
    if max_squares <= 0:
        return 0
    x, y = target.position
    dx, dy = direction
    for _ in range(max_squares):
        x += dx
        y += dy
    target.position = (x, y)
    return max_squares * SQUARE_SIZE_FT


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
