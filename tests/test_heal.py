"""Heal tests — SRD spell batch 1.

A flat, large single-target heal: 70 HP, no spellcasting modifier, so it
ships as a static `heal` action_template (auto-attached, no PC-build-time
construction). Enumerated per ally and scored by defensive_ehp_healing.

Layers:
  1. f_heal loads with the right shape
  2. end-to-end: restores 70 HP, clamped to max
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
    return dict(_registry().get("feature", "f_heal")["action_template"])


def _cleric():
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="cleric", name="cleric",
                   template={"id": "t", "name": "cleric", "abilities": abilities,
                               "cr": {"proficiency_bonus": 4}, "actions": []},
                   side="pc", hp_current=40, hp_max=40, ac=16,
                   position=(0, 0), speed={"walk": 30}, abilities=abilities,
                   spell_slots={6: 1})


def _ally(hp, hp_max):
    return Actor(id="ally", name="ally",
                   template={"id": "t", "name": "ally", "abilities": {},
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="pc", hp_current=hp, hp_max=hp_max, ac=15,
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
        feat = _registry().get("feature", "f_heal")
        self.assertEqual(feat["spell"]["level"], 6)
        self.assertEqual(feat["source"], "srd_5.2.1")
        a = _action()
        self.assertEqual(a["type"], "heal")
        self.assertEqual(a["pipeline"][0]["params"]["fixed"], 70)


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_restores_70(self):
        cleric = _cleric()
        wounded = _ally(hp=10, hp_max=120)
        state = _state([cleric, wounded])
        chosen = {"kind": "heal", "action": _action(),
                    "target": wounded, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(wounded.hp_current, 80)       # 10 + 70

    def test_clamps_to_max(self):
        cleric = _cleric()
        nearly_full = _ally(hp=60, hp_max=80)
        state = _state([cleric, nearly_full])
        chosen = {"kind": "heal", "action": _action(),
                    "target": nearly_full, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(nearly_full.hp_current, 80)   # clamped (60+70→80)

    def test_slot_consumed(self):
        cleric = _cleric()
        wounded = _ally(hp=10, hp_max=120)
        state = _state([cleric, wounded])
        chosen = {"kind": "heal", "action": _action(),
                    "target": wounded, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(cleric.spell_slots.get(6), 0)


if __name__ == "__main__":
    unittest.main()
