"""Suggestion tests — SRD spell batch 1.

Single-target WIS save or Charmed (won't harm the caster) for the
duration. Concentration. v1 models the Charmed combat effect + a
turn-end re-save escape.

Layers:
  1. f_suggestion loads with the right shape
  2. end-to-end: a failed save applies Charmed + registers the re-save
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
    return dict(_registry().get("feature", "f_suggestion")["action_template"])


def _wizard(int_score=18):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["int"]["score"] = int_score
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": abilities,
                               "cr": {"proficiency_bonus": 3}, "actions": [],
                               "spellcasting_ability": "intelligence"},
                   side="pc", hp_current=20, hp_max=20, ac=12,
                   position=(0, 0), speed={"walk": 30}, abilities=abilities,
                   spell_slots={2: 2})


def _enemy(wis_save=-10):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["wis"]["save"] = wis_save
    return Actor(id="thug", name="thug",
                   template={"id": "t", "name": "thug", "abilities": abilities,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=30, hp_max=30, ac=12,
                   position=(1, 0), speed={"walk": 30}, abilities=abilities)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class WiringTest(unittest.TestCase):

    def test_loads(self):
        feat = _registry().get("feature", "f_suggestion")
        self.assertEqual(feat["spell"]["level"], 2)
        self.assertEqual(feat["source"], "srd_5.2.1")
        a = _action()
        self.assertEqual(a["range_ft"], 30)
        self.assertTrue(a["concentration"])


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_failed_save_charms_and_registers_resave(self):
        wiz = _wizard()
        thug = _enemy(wis_save=-10)
        state = _state([wiz, thug])
        chosen = {"kind": "hard_control", "action": _action(),
                    "target": thug, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        conds = [c["condition_id"] for c in thug.applied_conditions]
        self.assertIn("co_charmed", conds)
        rs = [e for e in state.recurring_saves if e["target_id"] == "thug"]
        self.assertEqual(len(rs), 1)
        self.assertEqual(wiz.concentration_on["action_id"], "a_suggestion")


if __name__ == "__main__":
    unittest.main()
