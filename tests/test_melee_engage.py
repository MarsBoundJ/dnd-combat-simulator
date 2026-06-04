"""Regression — a melee PC out of reach must CLOSE, not freeze on a Ready.

Bug (run-3 trace): _run_slot only called _move_to_engage when the candidate
set was EMPTY. A far-from-melee Fighter still had one self-targeted Ready
candidate (Ready-when-enemy-enters-reach), so the set wasn't empty → it
Readied in place forever instead of advancing. Fix: move-to-engage fires
when no candidate TARGETS AN ENEMY, not merely when the set is empty.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.cli import _build_actor
from engine.core.geometry import distance_ft
from engine.core.runner import EncounterRunner
from engine.core.state import Encounter, CombatState
from engine.loader import load_content
from sims.run_boss_sim import _spread_specs, _dragon_spec

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _setup():
    actors = [_build_actor(s, _registry())
              for s in (_spread_specs() + [_dragon_spec()])]
    enc = Encounter(id="t", actors=actors)
    runner = EncounterRunner.new(enc, seed=1, content_registry=_registry())
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return runner, st, actors


class MeleeEngageTest(unittest.TestCase):
    def test_far_melee_fighter_closes_instead_of_readying(self):
        runner, st, actors = _setup()
        fighter = next(a for a in actors if a.id == "Fighter_Champion")
        dragon = next(a for a in actors if a.side == "enemy")
        # Spread-start Fighter at (10,0); dragon at (0,0) = 50 ft, well beyond
        # its greatsword reach (5) — only a Ready candidate exists.
        before = distance_ft(fighter, dragon)
        self.assertGreater(before, 5)
        runner._run_slot(fighter, st, slot="action")
        # It must have advanced toward the dragon (not frozen Readying).
        self.assertLess(distance_ft(fighter, dragon), before,
                        "melee Fighter froze on a Ready instead of closing")
        self.assertTrue(fighter.moved_this_turn)


if __name__ == "__main__":
    unittest.main()
