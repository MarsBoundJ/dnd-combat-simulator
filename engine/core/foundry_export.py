"""Foundry-VTT export (Phase D of the positional-barrier system).

One-way serializer: sim state -> Foundry document dicts, for visualization
and the eventual Foundry bridge. The SIM remains authoritative for all
mechanics (wall occlusion, AoE membership are resolved in the engine); these
documents are rendering/automation hints Foundry consumes.

The alignment was the whole point of building barriers Foundry-shaped:
  - geometry.Wall  ->  Foundry WallDocument   (segment + blocking channels)
  - an `area` dict ->  Foundry MeasuredTemplate (circle / cone / ray / rect)

Coordinate model
----------------
Sim positions and wall endpoints are in GRID UNITS (1 unit = one square =
`grid_distance` feet, default 5). Foundry stores geometry in PIXELS, with
`grid_size` pixels per square (default 100). So:
  - a wall endpoint  (gx, gy) grid units -> (gx * grid_size, gy * grid_size) px
  - a token/AoE origin on square (x, y) -> the square CENTER,
        ((x + 0.5) * grid_size, (y + 0.5) * grid_size) px
Distances on templates stay in FEET (Foundry template `distance` is in grid
units of distance, i.e. feet) — only positions convert to pixels.

Foundry CONST values mirrored here (so move/sight pass through unchanged):
  WALL_SENSE/MOVEMENT NONE = 0, NORMAL = 20.
"""
from __future__ import annotations

import math

from engine.core.geometry import Wall

# Foundry scene defaults (square grid, 5 ft per square, 100 px per square).
FOUNDRY_GRID_SIZE = 100      # pixels per square
FOUNDRY_GRID_DISTANCE = 5    # feet per square

# 5e cone: length == width at the far end -> ~53.13° full angle. Matches the
# dnd5e system's MeasuredTemplate cone angle.
CONE_ANGLE_DEG = 53.13

# Provenance namespace for module flags (Foundry convention: system/module
# data lives under a namespaced key in `flags`).
FLAG_NAMESPACE = "trusight"


def _square_center_px(square: tuple[float, float], grid_size: int) -> tuple[float, float]:
    """Grid square (x, y) -> its CENTER point in Foundry pixels."""
    return ((square[0] + 0.5) * grid_size, (square[1] + 0.5) * grid_size)


def _direction_deg(direction: tuple[int, int] | None) -> float:
    """Convert a sim unit direction (dx, dy) to Foundry degrees.

    Foundry screen space has +y pointing DOWN and measures direction
    clockwise from east, so atan2(dy, dx) in degrees is exactly Foundry's
    convention (0 = east, 90 = south). None / (0,0) -> 0.0 (east default).
    """
    if not direction or direction == (0, 0):
        return 0.0
    return math.degrees(math.atan2(direction[1], direction[0]))


def wall_to_document(wall: Wall, grid_size: int = FOUNDRY_GRID_SIZE) -> dict:
    """Serialize a geometry.Wall to a Foundry WallDocument dict.

    Endpoints scale grid-units -> pixels; the move/sight/sound/light
    channels pass through unchanged (already 0 / 20, mirroring Foundry's
    WALL_SENSE/MOVEMENT NONE/NORMAL); the Wall's `flags` are nested under
    the module namespace, as Foundry expects.
    """
    x0, y0, x1, y1 = wall.c
    return {
        "c": [x0 * grid_size, y0 * grid_size,
              x1 * grid_size, y1 * grid_size],
        "move": int(wall.move),
        "sight": int(wall.sight),
        "sound": int(wall.sound),
        "light": int(wall.light),
        "dir": int(wall.dir),
        "flags": {FLAG_NAMESPACE: dict(wall.flags)} if wall.flags else {},
    }


def token_to_document(actor, grid_size: int = FOUNDRY_GRID_SIZE) -> dict:
    """Serialize an Actor's grid placement to a Foundry TokenDocument dict.

    The sim's `position` (grid square) scales to the token's top-left pixel,
    and the sim's `elevation` (FEET) maps straight onto Foundry's native
    `token.elevation` field — Foundry stores token altitude in scene-distance
    units (feet), so a flying creature at elevation 30 renders aloft and its
    elevation badge reads 30. This is the visualization half of the altitude
    model; the sim's own Chebyshev-3D `distance_ft` stays authoritative for
    combat reach (Foundry doesn't auto-enforce 3-D melee reach)."""
    x, y = actor.position
    return {
        "name": getattr(actor, "name", None) or getattr(actor, "id", ""),
        "x": x * grid_size,
        "y": y * grid_size,
        "elevation": int(getattr(actor, "elevation", 0) or 0),
        "flags": {FLAG_NAMESPACE: {"actor_id": getattr(actor, "id", "")}},
    }


def sphere_to_documents(sphere, grid_size: int = FOUNDRY_GRID_SIZE,
                        segments: int = 16) -> list[dict]:
    """Serialize a geometry.Sphere barrier to a ring of Foundry WallDocuments
    approximating the circle (Foundry walls are line segments, so a closed
    sphere renders as an N-gon). The sim's own segment-vs-circle math stays
    authoritative for blocking; this ring is the render hint."""
    cx, cy = sphere.center
    r = sphere.radius
    pts = [(cx + r * math.cos(2 * math.pi * i / segments),
            cy + r * math.sin(2 * math.pi * i / segments))
           for i in range(segments)]
    docs = []
    for i in range(segments):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % segments]
        docs.append({
            "c": [x0 * grid_size, y0 * grid_size,
                  x1 * grid_size, y1 * grid_size],
            "move": int(sphere.move), "sight": int(sphere.sight),
            "sound": int(sphere.sound), "light": int(sphere.light),
            "dir": int(sphere.dir),
            "flags": {FLAG_NAMESPACE: dict(sphere.flags)} if sphere.flags else {},
        })
    return docs


def walls_to_documents(walls: list,
                        grid_size: int = FOUNDRY_GRID_SIZE) -> list[dict]:
    """Serialize a barrier list (e.g. state.walls — Walls AND Spheres) to
    Foundry WallDocument dicts. A Sphere expands to a ring of segments."""
    from engine.core.geometry import Sphere
    out: list[dict] = []
    for w in (walls or []):
        if isinstance(w, Sphere):
            out.extend(sphere_to_documents(w, grid_size))
        else:
            out.append(wall_to_document(w, grid_size))
    return out


def area_to_template(area: dict, origin: tuple[float, float],
                      direction: tuple[int, int] | None = None,
                      grid_size: int = FOUNDRY_GRID_SIZE) -> dict | None:
    """Serialize an `area` dict + its grid origin to a Foundry
    MeasuredTemplate dict. Returns None for an unmapped/empty shape.

    Mapping (distances stay in feet; origin -> pixel square-center):
      sphere / emanation -> circle (distance = radius_ft, or size_ft/2 for a
                            sphere whose size_ft is a DIAMETER; emanation
                            size_ft is the radius)
      cone               -> cone   (distance = length_ft, angle 53.13°,
                            direction from the unit vector)
      line               -> ray    (distance = length_ft, width = width_ft)
      cube               -> rect    (distance = size_ft, direction 45°)

    cube->rect is a visualization approximation: Foundry's rect grows from a
    corner, while a 5e cube is centered on a point. The sim's own
    actors_in_cube math stays authoritative; the rect is a render hint.
    """
    shape = (area.get("shape") or "sphere").lower()
    px, py = _square_center_px(origin, grid_size)
    base = {"x": px, "y": py}

    if shape in ("sphere", "emanation"):
        radius_ft = area.get("radius_ft")
        if radius_ft is None:
            size_ft = area.get("size_ft")
            if size_ft is None:
                return None
            # A sphere's size_ft is a diameter; an emanation's is the radius.
            radius_ft = (size_ft / 2.0) if shape == "sphere" else float(size_ft)
        return {**base, "t": "circle", "distance": float(radius_ft)}

    if shape == "cone":
        length_ft = area.get("length_ft")
        if length_ft is None:
            return None
        return {**base, "t": "cone", "distance": float(length_ft),
                "direction": _direction_deg(direction),
                "angle": CONE_ANGLE_DEG}

    if shape == "line":
        length_ft = area.get("length_ft")
        if length_ft is None:
            return None
        return {**base, "t": "ray", "distance": float(length_ft),
                "direction": _direction_deg(direction),
                "width": float(area.get("width_ft", 5))}

    if shape == "cube":
        size_ft = area.get("size_ft")
        if size_ft is None:
            return None
        return {**base, "t": "rect", "distance": float(size_ft),
                "direction": 45.0}

    return None
