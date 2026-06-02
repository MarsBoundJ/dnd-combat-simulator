"""PC retreat model — PCs fight until they drop; only the last conscious
party member flees (to recover the downed party). Monster morale-retreat
is unaffected.

Reuses the helpers from test_retreat.py.
"""
from __future__ import annotations

import random
import unittest

from engine.ai.retreat import check_retreat
from tests.test_retreat import _make_actor, _state_with


class PCRetreatTest(unittest.TestCase):

    def test_pc_does_not_flee_when_bloodied(self):
        """The core fix: a badly-hurt PC with allies still up does NOT flee
        (the old monster-morale 'bloodied' trigger must not apply to PCs)."""
        pc = _make_actor("hero", side="pc", hp=100, hp_current=8)   # 8% HP
        ally = _make_actor("ally", side="pc", hp=80, hp_current=80)
        state = _state_with([pc, ally])
        # Across many rng seeds it must NEVER flee (no save roll at all).
        for s in range(40):
            self.assertIsNone(check_retreat(pc, state, random.Random(s)))

    def test_last_conscious_pc_flees(self):
        """Last one standing (all other party members down) → flee to
        recover them."""
        pc = _make_actor("hero", side="pc", hp=100, hp_current=40)
        down1 = _make_actor("a1", side="pc", hp=80, hp_current=0)    # uncon.
        down2 = _make_actor("a2", side="pc", hp=70, hp_current=70)
        down2.is_dead = True
        state = _state_with([pc, down1, down2])
        result = check_retreat(pc, state, random.Random(0))
        self.assertIsNotNone(result)
        self.assertEqual(result["reason"], "last_conscious_pc")

    def test_solo_pc_self_preserves_via_normal_algorithm(self):
        """A solo PC has no party to revive it (dropping = death), so it
        self-preserves via the normal retreat algorithm: no trigger at full
        HP, but a badly-hurt solo PC CAN flee (unlike a party member)."""
        pc_full = _make_actor("hero", side="pc", hp=100, hp_current=100)
        enemy = _make_actor("ogre", side="enemy", hp=60, hp_current=60)
        state = _state_with([pc_full, enemy])
        self.assertIsNone(check_retreat(pc_full, state, random.Random(0)))

        pc_low = _make_actor("hero2", side="pc", hp=100, hp_current=5)
        enemy2 = _make_actor("ogre2", side="enemy", hp=60, hp_current=60)
        state2 = _state_with([pc_low, enemy2])
        fled = any(check_retreat(pc_low, state2, random.Random(s)) is not None
                    for s in range(40))
        self.assertTrue(fled, "a doomed solo PC should be able to flee")

    def test_pc_stays_while_one_ally_up(self):
        pc = _make_actor("hero", side="pc", hp=100, hp_current=12)
        up = _make_actor("a1", side="pc", hp=80, hp_current=3)       # barely up
        down = _make_actor("a2", side="pc", hp=80, hp_current=0)
        state = _state_with([pc, up, down])
        self.assertIsNone(check_retreat(pc, state, random.Random(0)))

    def test_monster_morale_retreat_unaffected(self):
        """Regression guard: an enemy still flees per its preset — the PC
        rule must only short-circuit side == 'pc'."""
        # Cowardly, bloodied enemy with an ally down; rng forces a failed
        # WIS save (d20=1) → it must flee via the normal algorithm.
        coward = _make_actor("goblin", side="enemy", hp=50, hp_current=5,
                              wis_save=0, presets={"retreat": "cowardly"})
        fallen = _make_actor("goblin2", side="enemy", hp=50, hp_current=0)
        state = _state_with([coward, fallen])

        class _R:   # always rolls 1 → save fails
            def randint(self, a, b):
                return 1
        result = check_retreat(coward, state, _R())
        self.assertIsNotNone(result)
        self.assertNotEqual(result.get("preset"), "pc_last_standing")


if __name__ == "__main__":
    unittest.main()
