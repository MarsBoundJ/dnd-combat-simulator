"""Summoning — spawn new combatants mid-encounter (engine.core.summoning).

Layers:
  1. summon builds a creature from a template, on the summoner's side,
     tagged summoned_by, added to encounter.actors
  2. it's inserted into turn_order right after the summoner
  3. count_summons counts living summons; max_total caps them
  4. the _summon primitive drives it from a current actor
  5. a summoned creature is immediately a live combatant (targetable)
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core import summoning
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _summon

REPO_ROOT = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO_ROOT / "schema" / "content",
                                   validate=True,
                                   schema_root=REPO_ROOT / "schema" / "definitions")
    return _REGISTRY


def _abil():
    return {k: {"score": 12, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _wraith(pos=(0, 0)):
    return Actor(id="wraith", name="wraith",
                  template={"id": "m_wraith", "name": "Wraith",
                             "abilities": _abil(), "actions": [],
                             "cr": {"proficiency_bonus": 3}},
                  side="enemy", hp_current=67, hp_max=67, ac=13,
                  speed={"walk": 30}, position=pos, abilities=_abil(),
                  size="medium", creature_type="undead")


def _hero(actor_id="hero", pos=(2, 0)):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                  template={"id": "pc", "name": actor_id, "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=30, hp_max=30, ac=14,
                  speed={"walk": 30}, position=pos, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=list(actors))
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class SummonTest(unittest.TestCase):

    def test_summon_adds_combatant_on_summoner_side(self):
        w, h = _wraith(), _hero()
        st = _state([w, h])
        before = len(st.encounter.actors)
        new = summoning.summon(w, "m_specter", st, count=1)
        self.assertEqual(len(new), 1)
        spec = new[0]
        self.assertEqual(len(st.encounter.actors), before + 1)
        self.assertEqual(spec.side, "enemy")            # summoner's side
        self.assertEqual(spec.summoned_by, "wraith")
        self.assertTrue(spec.is_alive())
        self.assertIn(spec, st.encounter.actors)

    def test_inserted_into_turn_order_after_summoner(self):
        w, h = _wraith(), _hero()
        st = _state([w, h])           # order: [wraith, hero]
        new = summoning.summon(w, "m_specter", st, count=1)
        wi = st.turn_order.index("wraith")
        self.assertEqual(st.turn_order[wi + 1], new[0].id)   # acts next

    def test_count_and_capacity_cap(self):
        w, h = _wraith(), _hero()
        st = _state([w, h])
        summoning.summon(w, "m_specter", st, count=2, max_total=3)
        self.assertEqual(summoning.count_summons(w, st), 2)
        # Cap at 3 total → only one more is created from a request of 5.
        more = summoning.summon(w, "m_specter", st, count=5, max_total=3)
        self.assertEqual(len(more), 1)
        self.assertEqual(summoning.count_summons(w, st), 3)

    def test_capacity_reached_returns_empty(self):
        w, h = _wraith(), _hero()
        st = _state([w, h])
        summoning.summon(w, "m_specter", st, count=3, max_total=3)
        none = summoning.summon(w, "m_specter", st, count=2, max_total=3)
        self.assertEqual(none, [])

    def test_primitive_summons_from_current_actor(self):
        w, h = _wraith(), _hero()
        st = _state([w, h])
        st.current_attack = {"actor": w}
        _summon({"monster": "m_specter", "count": 1}, st, EventBus())
        self.assertEqual(summoning.count_summons(w, st), 1)

    def test_unique_ids_for_multiple_summons(self):
        w, h = _wraith(), _hero()
        st = _state([w, h])
        new = summoning.summon(w, "m_specter", st, count=3)
        ids = [a.id for a in new]
        self.assertEqual(len(ids), len(set(ids)))       # all distinct


if __name__ == "__main__":
    unittest.main()
