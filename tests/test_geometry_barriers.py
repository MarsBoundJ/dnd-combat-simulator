"""Barrier geometry — Foundry-shaped Wall segments + line-of-effect crossing
tests (Phase A of the positional-barrier system).

Pure geometry: actors sit on integer square centers, walls on half-integer
square boundaries, so every genuine crossing is a clean transversal. No
engine state / Actors needed — these drive the geometry primitives directly.
"""
from __future__ import annotations

import unittest

from engine.core.geometry import (
    Wall,
    WALL_BLOCK_NONE,
    WALL_BLOCK_NORMAL,
    WALL_DIR_BOTH,
    line_of_effect_blocked,
    segment_blocked,
    segments_cross,
)


# A vertical wall sitting on the boundary between columns 2 and 3, spanning
# rows -1..5 — i.e. the segment x = 2.5 from y=-1 to y=5.
def _vertical_wall_at_x(x: float, y0: float = -1.0, y1: float = 5.0,
                        **kw) -> Wall:
    return Wall(c=(x, y0, x, y1), **kw)


class SegmentsCrossTest(unittest.TestCase):
    def test_proper_crossing_true(self):
        # Horizontal segment (0,2)->(5,2) crosses vertical x=2.5 boundary.
        self.assertTrue(segments_cross((0, 2), (5, 2), (2.5, -1), (2.5, 5)))

    def test_parallel_no_crossing(self):
        # Two horizontal segments never cross.
        self.assertFalse(segments_cross((0, 0), (5, 0), (0, 3), (5, 3)))

    def test_non_reaching_segment_false(self):
        # Segment ends at x=2 (before the x=2.5 wall) -> no crossing.
        self.assertFalse(segments_cross((0, 2), (2, 2), (2.5, -1), (2.5, 5)))

    def test_shared_endpoint_is_not_a_proper_cross(self):
        # Touching at an endpoint is contact, not a transversal -> False.
        self.assertFalse(segments_cross((0, 0), (2.5, 0), (2.5, -1), (2.5, 5)))

    def test_collinear_overlap_false(self):
        self.assertFalse(segments_cross((0, 0), (4, 0), (2, 0), (6, 0)))


class WallChannelTest(unittest.TestCase):
    def test_defaults_block_move_only(self):
        w = Wall(c=(2.5, -1, 2.5, 5))
        self.assertTrue(w.blocks("move"))
        self.assertFalse(w.blocks("sight"))
        self.assertFalse(w.blocks("sound"))
        self.assertEqual(w.dir, WALL_DIR_BOTH)
        self.assertEqual(w.flags, {})

    def test_sight_only_wall(self):
        w = Wall(c=(2.5, -1, 2.5, 5), move=WALL_BLOCK_NONE,
                 sight=WALL_BLOCK_NORMAL)
        self.assertFalse(w.blocks("move"))
        self.assertTrue(w.blocks("sight"))

    def test_endpoint_properties(self):
        w = Wall(c=(1.0, 2.0, 3.0, 4.0))
        self.assertEqual(w.p0, (1.0, 2.0))
        self.assertEqual(w.p1, (3.0, 4.0))


class SegmentBlockedTest(unittest.TestCase):
    def test_empty_walls_never_block(self):
        self.assertFalse(segment_blocked((0, 2), (5, 2), [], "move"))
        self.assertFalse(segment_blocked((0, 2), (5, 2), None, "move"))

    def test_move_wall_blocks_crossing_path(self):
        wall = _vertical_wall_at_x(2.5)
        self.assertTrue(segment_blocked((0, 2), (5, 2), [wall], "move"))

    def test_move_wall_does_not_block_same_side_path(self):
        # Both endpoints on the near side (x < 2.5) -> no crossing.
        wall = _vertical_wall_at_x(2.5)
        self.assertFalse(segment_blocked((0, 0), (2, 4), [wall], "move"))

    def test_channel_is_respected(self):
        # A sight-only wall does not block the 'move' channel.
        wall = _vertical_wall_at_x(2.5, move=WALL_BLOCK_NONE,
                                   sight=WALL_BLOCK_NORMAL)
        self.assertFalse(segment_blocked((0, 2), (5, 2), [wall], "move"))
        self.assertTrue(segment_blocked((0, 2), (5, 2), [wall], "sight"))

    def test_offset_wall_does_not_block(self):
        # Wall far to the side of the path.
        wall = _vertical_wall_at_x(20.5)
        self.assertFalse(segment_blocked((0, 2), (5, 2), [wall], "move"))

    def test_multiple_walls_any_blocks(self):
        walls = [_vertical_wall_at_x(20.5), _vertical_wall_at_x(2.5)]
        self.assertTrue(segment_blocked((0, 2), (5, 2), walls, "move"))


class LineOfEffectTest(unittest.TestCase):
    def test_move_wall_breaks_line_of_effect(self):
        # Wall of Force analogue: blocks move, transparent to sight.
        wall = _vertical_wall_at_x(2.5, move=WALL_BLOCK_NORMAL,
                                   sight=WALL_BLOCK_NONE)
        self.assertTrue(line_of_effect_blocked((0, 2), (5, 2), [wall]))

    def test_sight_wall_breaks_line_of_effect(self):
        wall = _vertical_wall_at_x(2.5, move=WALL_BLOCK_NONE,
                                   sight=WALL_BLOCK_NORMAL)
        self.assertTrue(line_of_effect_blocked((0, 2), (5, 2), [wall]))

    def test_no_wall_clear(self):
        self.assertFalse(line_of_effect_blocked((0, 2), (5, 2), []))

    def test_path_not_crossing_is_clear(self):
        wall = _vertical_wall_at_x(2.5)
        self.assertFalse(line_of_effect_blocked((0, 0), (2, 4), [wall]))


if __name__ == "__main__":
    unittest.main()
