"""Multiattack candidate target stamping (grind bug E).

`generate_candidates` emits ONE multiattack candidate with an informational
`target`; the scorer overkill-caps the multiattack's eHP at that target's
remaining HP, and execution re-picks targets to maximize damage anyway. So the
stamped target must be the HIGHEST-HP in-reach enemy, not the first by actor
order — otherwise a near-dead enemy pins the whole multiattack score to a
scrap of HP and a mediocre self-buff outscores it (a Champion sat idle for
rounds while a 5-HP incapacitated giant, first in order, capped its
multiattack to ~5 with a healthy giant in reach unhit).

Run via:
    python -m unittest tests.test_multiattack_target_stamp
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.cli import _build_actor
from engine.core.pipeline import generate_candidates
from engine.core.state import Encounter, CombatState
from engine.loader import load_content
from sims.run_first_sim import _party_specs

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _fighter(pos=(9, 4)):
    spec = [s for s in _party_specs()
            if s["instance_id"] == "Fighter_Champion"][0]
    spec["position"] = list(pos)
    return _build_actor(spec, _registry())


def _giant(gid, pos, hp):
    g = _build_actor({"instance_id": gid, "side": "enemy", "position": list(pos),
                      "template_ref": {"entity_type": "monster",
                                       "id": "m_fire_giant"}}, _registry())
    g.hp_current = hp
    return g


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 9
    st.content_registry = _registry()
    return st


def _multiattack_target(fighter, state):
    for c in generate_candidates(fighter, state, "action"):
        if c.get("kind") == "multiattack":
            return c["target"]
    return None


class MultiattackTargetStampTest(unittest.TestCase):

    def test_stamps_highest_hp_in_reach_enemy_not_first(self):
        # A 5-HP giant FIRST in actor order, a healthy 23-HP giant second,
        # both in melee reach. The multiattack must stamp the 23-HP one.
        f = _fighter((9, 4))
        low = _giant("g_low", (9, 5), hp=5)       # first in order, low HP
        high = _giant("g_high", (10, 4), hp=23)   # second, higher HP
        st = _state([f, low, high])
        target = _multiattack_target(f, st)
        self.assertIsNotNone(target)
        self.assertEqual(target.id, "g_high")

    def test_order_independent(self):
        # Swap actor order — still the highest-HP enemy, not first-in-list.
        f = _fighter((9, 4))
        high = _giant("g_high", (10, 4), hp=140)
        low = _giant("g_low", (9, 5), hp=8)
        st = _state([f, high, low])               # high listed first now
        self.assertEqual(_multiattack_target(f, st).id, "g_high")

    def test_single_enemy_still_stamped(self):
        # Degenerate: one enemy in reach is trivially the max.
        f = _fighter((9, 4))
        only = _giant("g_only", (9, 5), hp=50)
        st = _state([f, only])
        self.assertEqual(_multiattack_target(f, st).id, "g_only")


if __name__ == "__main__":
    unittest.main()
