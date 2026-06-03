"""Foundry-VTT export (Phase D) — sim geometry -> Foundry document dicts.

Verifies the wall -> WallDocument and area -> MeasuredTemplate mappings,
the grid-unit -> pixel coordinate scaling, and that the real loaded content
(Fireball sphere, a dragon's breath cone/line) round-trips to sane
templates. One-way export; the sim stays authoritative for mechanics.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.foundry_export import (
    CONE_ANGLE_DEG,
    FLAG_NAMESPACE,
    area_to_template,
    wall_to_document,
    walls_to_documents,
)
from engine.core.geometry import Wall, WALL_BLOCK_NONE, WALL_BLOCK_NORMAL
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


class WallDocumentTest(unittest.TestCase):
    def test_coords_scale_grid_units_to_pixels(self):
        w = Wall(c=(7.5, -3, 7.5, 3))
        doc = wall_to_document(w, grid_size=100)
        self.assertEqual(doc["c"], [750.0, -300.0, 750.0, 300.0])

    def test_wall_of_force_channels_pass_through(self):
        # move-blocking, sight-transparent (Wall of Force).
        w = Wall(c=(0, 0, 0, 5), move=WALL_BLOCK_NORMAL, sight=WALL_BLOCK_NONE)
        doc = wall_to_document(w)
        self.assertEqual(doc["move"], 20)
        self.assertEqual(doc["sight"], 0)
        self.assertEqual(doc["dir"], 0)

    def test_flags_namespaced(self):
        w = Wall(c=(0, 0, 0, 5),
                 flags={"effect": "wall_of_force", "caster_id": "wiz"})
        doc = wall_to_document(w)
        self.assertIn(FLAG_NAMESPACE, doc["flags"])
        self.assertEqual(doc["flags"][FLAG_NAMESPACE]["effect"], "wall_of_force")

    def test_empty_flags_is_empty_dict(self):
        self.assertEqual(wall_to_document(Wall(c=(0, 0, 1, 1)))["flags"], {})

    def test_walls_to_documents_list(self):
        walls = [Wall(c=(0, 0, 0, 5)), Wall(c=(1, 1, 2, 2))]
        docs = walls_to_documents(walls, grid_size=50)
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[1]["c"], [50.0, 50.0, 100.0, 100.0])

    def test_none_walls_empty_list(self):
        self.assertEqual(walls_to_documents(None), [])


class TemplateOriginTest(unittest.TestCase):
    def test_origin_is_square_center_in_pixels(self):
        t = area_to_template({"shape": "sphere", "radius_ft": 20}, (3, 4),
                             grid_size=100)
        self.assertEqual(t["x"], 350.0)   # (3 + 0.5) * 100
        self.assertEqual(t["y"], 450.0)   # (4 + 0.5) * 100


class TemplateShapeTest(unittest.TestCase):
    def test_sphere_radius(self):
        t = area_to_template({"shape": "sphere", "radius_ft": 20}, (0, 0))
        self.assertEqual(t["t"], "circle")
        self.assertEqual(t["distance"], 20.0)

    def test_sphere_size_ft_is_diameter(self):
        # Fireball: size_ft 20 = 20 ft diameter -> 10 ft radius.
        t = area_to_template({"shape": "sphere", "size_ft": 20}, (0, 0))
        self.assertEqual(t["t"], "circle")
        self.assertEqual(t["distance"], 10.0)

    def test_emanation_size_ft_is_radius(self):
        # Spirit Guardians: 15-ft emanation -> 15 ft radius circle.
        t = area_to_template({"shape": "emanation", "size_ft": 15}, (0, 0))
        self.assertEqual(t["t"], "circle")
        self.assertEqual(t["distance"], 15.0)

    def test_cone_east(self):
        t = area_to_template({"shape": "cone", "length_ft": 60}, (0, 0),
                             direction=(1, 0))
        self.assertEqual(t["t"], "cone")
        self.assertEqual(t["distance"], 60.0)
        self.assertEqual(t["direction"], 0.0)       # east
        self.assertEqual(t["angle"], CONE_ANGLE_DEG)

    def test_line_south_with_width(self):
        t = area_to_template({"shape": "line", "length_ft": 90, "width_ft": 5},
                             (0, 0), direction=(0, 1))
        self.assertEqual(t["t"], "ray")
        self.assertEqual(t["distance"], 90.0)
        self.assertEqual(t["width"], 5.0)
        self.assertEqual(t["direction"], 90.0)      # south (+y down)

    def test_cube_rect(self):
        t = area_to_template({"shape": "cube", "size_ft": 10}, (0, 0))
        self.assertEqual(t["t"], "rect")
        self.assertEqual(t["distance"], 10.0)

    def test_unmapped_shape_returns_none(self):
        self.assertIsNone(area_to_template({"shape": "blob"}, (0, 0)))

    def test_missing_dims_returns_none(self):
        self.assertIsNone(area_to_template({"shape": "cone"}, (0, 0)))


class RealContentRoundTripTest(unittest.TestCase):
    """Drive the mapper with the actual loaded content area dicts."""

    def test_fireball_sphere(self):
        fb = _registry().get("feature", "f_fireball")
        area = fb["action_template"]["area"]
        t = area_to_template(area, (5, 5))
        self.assertEqual(t["t"], "circle")
        self.assertGreater(t["distance"], 0)

    def test_red_dragon_breath_cone(self):
        drag = _registry().get("monster", "m_adult_red_dragon")
        breath = next(a for a in drag["actions"]
                      if a.get("area", {}).get("shape") == "cone")
        t = area_to_template(breath["area"], (0, 0), direction=(1, 0))
        self.assertEqual(t["t"], "cone")
        self.assertEqual(t["distance"], 60.0)


if __name__ == "__main__":
    unittest.main()
