"""AoE coverage routine (engine/ai/positioning.max_aoe_coverage), Phase 1a.

Drives the routine with REAL loaded content (the Adult Red Dragon's cone
breath + a dragon sphere action) so it exercises the actual eHP scorer
end-to-end. Asserts the routine orients toward the densest eHP cluster.
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from engine.ai.positioning import max_aoe_coverage
from engine.core.geometry import is_within_ft
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


def _mk(actor_id: str, side: str, pos: tuple[int, int], hp: int = 60) -> Actor:
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "actions": [], "cr": {"proficiency_bonus": 3}},
                 side=side, hp_current=hp, hp_max=hp, ac=14,
                 speed={"walk": 30}, position=pos, abilities=ab)


def _state(actors: list[Actor]) -> CombatState:
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    return st


def _action_with_shape(monster_id: str, shape: str) -> dict:
    mon = _registry().get("monster", monster_id)
    for a in mon["actions"]:
        if (a.get("area") or {}).get("shape") == shape:
            return a
    raise AssertionError(f"{monster_id} has no {shape} action")


class ConeCoverageTest(unittest.TestCase):
    def setUp(self):
        self.breath = _action_with_shape("m_adult_red_dragon", "cone")

    def test_orients_toward_east_cluster(self):
        dragon = _mk("dragon", "enemy", (0, 0), hp=256)
        pcs = [_mk("p1", "pc", (5, 0)), _mk("p2", "pc", (6, 1)),
               _mk("p3", "pc", (6, -1))]
        st = _state([dragon] + pcs)
        best = max_aoe_coverage(self.breath, dragon, st)
        self.assertIsNotNone(best)
        self.assertGreater(best["ehp"], 0)
        self.assertGreater(best["direction"][0], 0,  # faces east, toward them
                           "cone should orient toward the eastern cluster")

    def test_orients_toward_west_cluster(self):
        dragon = _mk("dragon", "enemy", (0, 0), hp=256)
        pcs = [_mk("p1", "pc", (-5, 0)), _mk("p2", "pc", (-6, 1)),
               _mk("p3", "pc", (-6, -1))]
        st = _state([dragon] + pcs)
        best = max_aoe_coverage(self.breath, dragon, st)
        self.assertIsNotNone(best)
        self.assertLess(best["direction"][0], 0,
                        "cone should orient toward the western cluster")

    def test_no_enemies_in_reach_returns_none(self):
        dragon = _mk("dragon", "enemy", (0, 0), hp=256)
        # All PCs far beyond the 60-ft cone length.
        pcs = [_mk("p1", "pc", (50, 0)), _mk("p2", "pc", (50, 5))]
        st = _state([dragon] + pcs)
        self.assertIsNone(max_aoe_coverage(self.breath, dragon, st))

    def test_only_allies_in_area_returns_none(self):
        # The "attacker" with only same-side creatures around -> friendly
        # fire makes every placement non-positive -> None.
        caster = _mk("caster", "enemy", (0, 0))
        allies = [_mk("a1", "enemy", (5, 0)), _mk("a2", "enemy", (6, 1))]
        st = _state([caster] + allies)
        self.assertIsNone(max_aoe_coverage(self.breath, caster, st))


class SphereCoverageTest(unittest.TestCase):
    def test_sphere_anchors_on_cluster(self):
        # Derive a guaranteed-scorable sphere by putting the dragon breath's
        # flat-DC save/damage pipeline onto a sphere area (real sphere
        # actions on dragons live in nested spellcasting blocks and use
        # caster-spell-DC, which a bare attacker can't resolve).
        action = copy.deepcopy(_action_with_shape("m_adult_red_dragon", "cone"))
        action["area"] = {"shape": "sphere", "radius_ft": 20, "range_ft": 90}
        dragon = _mk("dragon", "enemy", (0, 0), hp=207)
        # A tight cluster well within the sphere's cast range.
        pcs = [_mk("p1", "pc", (8, 0)), _mk("p2", "pc", (9, 0)),
               _mk("p3", "pc", (8, 1))]
        st = _state([dragon] + pcs)
        best = max_aoe_coverage(action, dragon, st)
        self.assertIsNotNone(best)
        self.assertGreater(best["ehp"], 0)
        self.assertIsNone(best["direction"])          # sphere has no facing
        # Origin is anchored on one of the clustered PCs (within range).
        self.assertIn(best["origin"], {(8, 0), (9, 0), (8, 1)})


class NoAreaTest(unittest.TestCase):
    def test_action_without_area_returns_none(self):
        dragon = _mk("dragon", "enemy", (0, 0))
        pc = _mk("p1", "pc", (5, 0))
        st = _state([dragon, pc])
        self.assertIsNone(
            max_aoe_coverage({"id": "a_bite", "type": "weapon_attack"},
                             dragon, st))


if __name__ == "__main__":
    unittest.main()
