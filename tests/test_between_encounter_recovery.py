"""Between-encounter recovery (RAW play behavior, Phil 2026-06-05).

After EVERY fight, PCs stabilize downed allies and heal up to ~85% of max via
Hit Dice — whether or not they take a formal short rest. A downed (dying) PC
that's recovered does NOT carry the death-save clock into the next fight (the
bug that was permanently losing the party's damage dealers). Recovery does NOT
recharge short-rest RESOURCES (that's only a real short rest).

Run via:
    python -m unittest tests.test_between_encounter_recovery
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.cli import _build_actor
from engine.core import death_saves as ds
from engine.core.rest import (apply_between_encounter_recovery,
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


def _pc(level=13, cls="c_fighter"):
    spec = {"instance_id": "pc", "side": "pc",
            "pc": {"class": cls, "level": level,
                   "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                       "int": 10, "wis": 12, "cha": 10}}}
    return _build_actor(spec, _registry())


def _state(actors):
    return CombatState(encounter=Encounter(id="t", actors=actors))


class BetweenEncounterRecoveryTest(unittest.TestCase):

    def test_downed_pc_stabilizes_and_heals_up(self):
        pc = _pc()
        pc.hp_current = 0
        st = _state([pc])
        ds.enter_dying(pc, st)
        self.assertTrue(pc.is_dying)
        apply_between_encounter_recovery(pc, st)
        # Death-save clock cleared, and Hit Dice climbed it back into the fight.
        self.assertFalse(pc.is_dying)
        self.assertFalse(pc.is_dead)
        self.assertTrue(pc.is_alive())
        self.assertGreaterEqual(pc.hp_current,
                                int(pc.hp_max * RECOVERY_TARGET_FRAC))

    def test_downed_with_no_hit_dice_stabilizes_but_stays_down(self):
        pc = _pc()
        pc.hp_current = 0
        pc.hit_dice_remaining = 0
        st = _state([pc])
        ds.enter_dying(pc, st)
        apply_between_encounter_recovery(pc, st)
        self.assertFalse(pc.is_dying)        # no longer on the death-save clock
        self.assertEqual(pc.hp_current, 0)   # but no dice to climb off 0

    def test_dead_pc_stays_dead(self):
        pc = _pc()
        pc.hp_current = 0
        pc.is_dead = True
        st = _state([pc])
        apply_between_encounter_recovery(pc, st)
        self.assertTrue(pc.is_dead)
        self.assertEqual(pc.hp_current, 0)

    def test_wounded_conscious_pc_heals_to_near_max(self):
        pc = _pc()
        pc.hp_current = max(1, int(pc.hp_max * 0.3))
        st = _state([pc])
        apply_between_encounter_recovery(pc, st)
        self.assertGreaterEqual(pc.hp_current,
                                int(pc.hp_max * RECOVERY_TARGET_FRAC))
        self.assertLessEqual(pc.hp_current, pc.hp_max)

    def test_does_not_recharge_short_rest_resources(self):
        # A Fighter's Second Wind is a SHORT-REST resource — recovery (not a
        # formal short rest) must not refresh it.
        pc = _pc(cls="c_fighter")
        pc.hp_current = max(1, int(pc.hp_max * 0.3))
        pc.resources["second_wind_uses_remaining"] = 0
        st = _state([pc])
        apply_between_encounter_recovery(pc, st)
        self.assertEqual(pc.resources.get("second_wind_uses_remaining"), 0)


if __name__ == "__main__":
    unittest.main()
