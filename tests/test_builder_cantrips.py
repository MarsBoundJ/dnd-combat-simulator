"""Desktop-built attack cantrips via the pc_builder system.

These 5 cantrips (Chill Touch, Produce Flame, Shocking Grasp, Sorcerous
Burst, Starry Wisp) were flagged by the spell lane as "needs a pc_schema
builder" before the data-driven pc_builder refactor. They now build from
a pc_builder YAML block with ZERO pc_schema edits — proving the refactor
works on NEW spells, including the melee touch cantrips (which exercise
the attack_kind: melee extension).

Each test loads the real feature YAML, dispatches it via
_dispatch_pc_builder, and asserts the resulting action shape.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.loader import load_content
from engine.pc_schema import _dispatch_pc_builder

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_ABIL = {"str": {"score": 10}, "dex": {"score": 10}, "con": {"score": 10},
          "int": {"score": 18}, "wis": {"score": 18}, "cha": {"score": 18}}

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _dispatch(feature_id, level=1, pb=2):
    feat = _registry().get("feature", feature_id)
    class_id = feat["granted_by"]["class"]
    return _dispatch_pc_builder(feat, level, _ABIL, pb, class_id)


class BuilderCantripTest(unittest.TestCase):

    def test_chill_touch_is_melee(self) -> None:
        a = _dispatch("f_chill_touch")
        self.assertEqual(a["id"], "a_chill_touch")
        self.assertEqual(a["spell_slot_level"], 0)
        atk = a["pipeline"][0]["params"]
        self.assertEqual(atk["kind"], "melee")
        self.assertEqual(atk["reach_ft"], 5)
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "1d10")
        self.assertEqual(a["pipeline"][1]["params"]["type"], "necrotic")

    def test_shocking_grasp_is_melee(self) -> None:
        a = _dispatch("f_shocking_grasp")
        atk = a["pipeline"][0]["params"]
        self.assertEqual(atk["kind"], "melee")
        self.assertEqual(atk["reach_ft"], 5)
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "1d8")
        self.assertEqual(a["pipeline"][1]["params"]["type"], "lightning")

    def test_starry_wisp_ranged(self) -> None:
        a = _dispatch("f_starry_wisp")
        atk = a["pipeline"][0]["params"]
        self.assertEqual(atk["kind"], "ranged")
        self.assertEqual(atk["range_ft"], 60)
        self.assertEqual(a["pipeline"][1]["params"]["type"], "radiant")

    def test_produce_flame_ranged(self) -> None:
        a = _dispatch("f_produce_flame")
        self.assertEqual(a["pipeline"][0]["params"]["range_ft"], 60)
        self.assertEqual(a["pipeline"][1]["params"]["type"], "fire")

    def test_sorcerous_burst_ranged_120(self) -> None:
        a = _dispatch("f_sorcerous_burst")
        self.assertEqual(a["pipeline"][0]["params"]["range_ft"], 120)

    def test_cantrip_die_scales_with_level(self) -> None:
        # Character level 5 → 2 dice; 11 → 3; 17 → 4
        a5 = _dispatch("f_starry_wisp", level=5, pb=3)
        a11 = _dispatch("f_starry_wisp", level=11, pb=4)
        self.assertEqual(a5["pipeline"][1]["params"]["dice"], "2d8")
        self.assertEqual(a11["pipeline"][1]["params"]["dice"], "3d8")

    def test_attack_bonus_uses_caster_ability(self) -> None:
        # Wizard INT 18 (+4) + PB 2 = +6 (Chill Touch)
        a = _dispatch("f_chill_touch", level=1, pb=2)
        self.assertEqual(a["pipeline"][0]["params"]["bonus"], 6)
        # Sorcerer CHA 18 (+4) + PB 3 = +7 at level 5 (Sorcerous Burst)
        b = _dispatch("f_sorcerous_burst", level=5, pb=3)
        self.assertEqual(b["pipeline"][0]["params"]["bonus"], 7)


if __name__ == "__main__":
    unittest.main()
