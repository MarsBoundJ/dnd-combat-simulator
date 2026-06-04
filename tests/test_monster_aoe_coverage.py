"""Phase 1b — max_aoe_coverage wired into monster AoE candidate emission.

Scenario: two foes straddle the dragon's east axis at (5, ±3). Aiming the
cone directly at either foe gives a diagonal facing that catches only that
one; only the (1, 0) east orientation catches BOTH. The old per-enemy
emission would never produce (1, 0); the coverage candidate does — proving
the wiring offers orientations not aimed at any single enemy.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _breath():
    mon = _registry().get("monster", "m_adult_red_dragon")
    return next(a for a in mon["actions"]
                if (a.get("area") or {}).get("shape") == "cone")


def _mk(actor_id, side, pos, actions=None, hp=60):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "actions": actions or [],
                           "cr": {"proficiency_bonus": 3}},
                 side=side, hp_current=hp, hp_max=hp, ac=14,
                 speed={"walk": 40}, position=pos, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.current_turn_idx = 0
    return st


class MonsterAoeCoverageTest(unittest.TestCase):
    def _aoe_dirs(self, state, dragon):
        cands = generate_candidates(dragon, state)
        return [c.get("direction") for c in cands
                if c.get("kind") == "aoe_attack"]

    def test_coverage_offers_between_enemies_orientation(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        # Two foes straddling the east axis — neither due-east.
        foes = [_mk("p1", "pc", (5, 3)), _mk("p2", "pc", (5, -3))]
        st = _state([dragon] + foes)
        dirs = self._aoe_dirs(st, dragon)
        self.assertIn((1, 0), dirs,
                      "coverage routine should offer the east cone that "
                      "catches both straddling foes")
        # The legacy per-enemy aim is still present (additive, not replaced).
        self.assertTrue(any(d in ((1, 1), (1, -1)) for d in dirs),
                        "per-enemy aim candidates should remain")

    def test_no_aoe_candidate_when_out_of_range(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        foes = [_mk("p1", "pc", (50, 0))]   # beyond the 60-ft cone
        st = _state([dragon] + foes)
        self.assertEqual(self._aoe_dirs(st, dragon), [])


if __name__ == "__main__":
    unittest.main()
