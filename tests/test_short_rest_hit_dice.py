"""Short-rest Hit-Dice HP recovery — PCs spend Hit Dice to heal on a short
rest (each = avg(hit die) + CON mod), spending just enough to top up; the
pool refreshes (half, min 1) on a long rest. Monsters don't track Hit Dice.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.cli import _build_actor
from engine.core.rest import (apply_short_rest, apply_long_rest,
                              RECOVERY_TARGET_FRAC)
from engine.core.state import Encounter, CombatState
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _pc(level=13, cls="c_wizard"):
    spec = {"instance_id": "pc", "side": "pc",
            "pc": {"class": cls, "level": level,
                   "ability_scores": {"str": 8, "dex": 14, "con": 14,
                                       "int": 18, "wis": 12, "cha": 10}}}
    return _build_actor(spec, _registry())


def _monster(mid="m_ogre"):
    return _build_actor({"instance_id": "m", "side": "enemy",
                         "template_ref": {"entity_type": "monster", "id": mid}},
                        _registry())


def _state(actors):
    return CombatState(encounter=Encounter(id="t", actors=actors))


class ShortRestHitDiceTest(unittest.TestCase):
    def test_pc_initialized_with_level_hit_dice(self):
        pc = _pc(13)
        self.assertEqual(pc.hit_dice_max, 13)
        self.assertEqual(pc.hit_dice_remaining, 13)

    def test_short_rest_heals_up_to_near_max(self):
        # Heavily wounded -> heals up to ~85% of max (NOT to max).
        pc = _pc(13)
        pc.hp_current = max(1, int(pc.hp_max * 0.30))
        summary = apply_short_rest(pc, _state([pc]))
        self.assertIn("hit_dice", summary)
        self.assertLess(pc.hit_dice_remaining, 13)          # dice spent
        self.assertGreaterEqual(
            pc.hp_current, int(pc.hp_max * RECOVERY_TARGET_FRAC))  # near max
        self.assertLessEqual(pc.hp_current, pc.hp_max)      # never over max

    def test_does_not_waste_dice_near_max(self):
        # Above the ~85% target -> spends NO dice (topping the last few HP to
        # max would burn a whole die for a few points — Phil's no-waste rule).
        pc = _pc(13)
        pc.hp_current = int(pc.hp_max * 0.95)
        before = pc.hp_current
        summary = apply_short_rest(pc, _state([pc]))
        self.assertNotIn("hit_dice", summary)
        self.assertEqual(pc.hit_dice_remaining, 13)         # none spent
        self.assertEqual(pc.hp_current, before)             # unchanged

    def test_full_hp_spends_nothing(self):
        pc = _pc(13)
        pc.hp_current = pc.hp_max
        summary = apply_short_rest(pc, _state([pc]))
        self.assertNotIn("hit_dice", summary)
        self.assertEqual(pc.hit_dice_remaining, 13)

    def test_out_of_hit_dice_no_heal(self):
        pc = _pc(13)
        pc.hp_current = 5
        pc.hit_dice_remaining = 0
        apply_short_rest(pc, _state([pc]))
        self.assertEqual(pc.hp_current, 5)

    def test_long_rest_regains_half_hit_dice(self):
        pc = _pc(13)
        pc.hit_dice_remaining = 0
        apply_long_rest(pc, _state([pc]))
        self.assertEqual(pc.hit_dice_remaining, 13 // 2)    # 6
        self.assertEqual(pc.hp_current, pc.hp_max)          # long rest = full

    def test_monster_has_no_hit_dice(self):
        mon = _monster("m_ogre")
        self.assertEqual(mon.hit_dice_max, 0)
        mon.hp_current = 5
        summary = apply_short_rest(mon, _state([mon]))
        self.assertNotIn("hit_dice", summary)
        self.assertEqual(mon.hp_current, 5)


if __name__ == "__main__":
    unittest.main()
