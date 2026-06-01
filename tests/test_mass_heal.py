"""Mass Heal tests — SRD spell batch 1.

The L9 capstone heal: a 700-HP pool, modeled in v1 as a fixed 700-HP
single-target full top-off (the heal primitive clamps to hp_max).

Layers:
  1. f_mass_heal loads with the right shape
  2. end-to-end: fully tops off even a badly wounded high-HP creature
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _action():
    return dict(_registry().get("feature", "f_mass_heal")["action_template"])


def _cleric():
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="cleric", name="cleric",
                   template={"id": "t", "name": "cleric", "abilities": abilities,
                               "cr": {"proficiency_bonus": 6}, "actions": []},
                   side="pc", hp_current=60, hp_max=60, ac=18,
                   position=(0, 0), speed={"walk": 30}, abilities=abilities,
                   spell_slots={9: 1})


def _ally(hp, hp_max):
    return Actor(id="tank", name="tank",
                   template={"id": "t", "name": "tank", "abilities": {},
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="pc", hp_current=hp, hp_max=hp_max, ac=18,
                   position=(1, 0), speed={"walk": 30}, abilities={})


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class WiringTest(unittest.TestCase):

    def test_loads(self):
        feat = _registry().get("feature", "f_mass_heal")
        self.assertEqual(feat["spell"]["level"], 9)
        self.assertEqual(feat["source"], "srd_5.2.1")
        self.assertEqual(_action()["pipeline"][0]["params"]["fixed"], 700)


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_full_top_off(self):
        cleric = _cleric()
        tank = _ally(hp=12, hp_max=250)
        state = _state([cleric, tank])
        chosen = {"kind": "heal", "action": _action(),
                    "target": tank, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(tank.hp_current, 250)         # fully restored
        self.assertEqual(cleric.spell_slots.get(9), 0)


if __name__ == "__main__":
    unittest.main()
