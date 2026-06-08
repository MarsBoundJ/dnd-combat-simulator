"""Ranged-attack range parsing — `attack_range_ft`.

Monster ranged attacks are commonly authored as
`{kind: ranged, range: [normal, long]}` (Manticore tail spike, most humanoid
bows/crossbows — 25 stat blocks). The reach readers only knew `range_ft` /
`reach_ft`, so that form fell through to 5 ft and the attack was silently
treated as melee (it auto-missed past 5 ft). `attack_range_ft` centralizes the
resolution and reads the NORMAL range from the list.

Run via:
    python -m unittest tests.test_attack_range
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.geometry import attack_range_ft
from engine.core.pipeline import _action_reach_ft
from engine.ai.positioning import _action_range_ft
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


class AttackRangeFtTest(unittest.TestCase):
    def test_range_list_uses_normal_range(self):
        self.assertEqual(attack_range_ft({"kind": "ranged",
                                          "range": [100, 200]}), 100)
        self.assertEqual(attack_range_ft({"range": [25, 50]}), 25)

    def test_explicit_range_ft_and_reach_ft(self):
        self.assertEqual(attack_range_ft({"range_ft": 120}), 120)
        self.assertEqual(attack_range_ft({"reach_ft": 10}), 10)

    def test_range_ft_wins_over_list(self):
        # explicit range_ft takes precedence if both somehow present
        self.assertEqual(attack_range_ft({"range_ft": 60,
                                          "range": [100, 200]}), 60)

    def test_scalar_range(self):
        self.assertEqual(attack_range_ft({"range": 30}), 30)

    def test_melee_default(self):
        self.assertEqual(attack_range_ft({}), 5)
        self.assertEqual(attack_range_ft({"kind": "melee"}), 5)


class ReadersAgreeTest(unittest.TestCase):
    """Both reach readers now resolve the `range: [n, m]` form, not 5 ft."""

    def setUp(self):
        m = _registry().get("monster", "m_manticore")
        self.spike = next(a for a in m["actions"] if a["id"] == "a_tail_spike")
        self.rend = next(a for a in m["actions"] if a["id"] == "a_rend")

    def test_tail_spike_is_ranged_not_melee(self):
        self.assertEqual(_action_reach_ft(self.spike), 100)
        self.assertEqual(_action_range_ft(self.spike), 100)

    def test_melee_rend_unchanged(self):
        self.assertEqual(_action_reach_ft(self.rend), 5)
        self.assertEqual(_action_range_ft(self.rend), 5)


if __name__ == "__main__":
    unittest.main()
