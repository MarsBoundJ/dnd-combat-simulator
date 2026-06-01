"""Banishment tests — SRD spell batch 1.

Single-target CHA save or banished (Incapacitated) for the duration,
with a turn-end CHA re-save (v1 escape). Concentration.

Layers:
  1. f_banishment loads with the right shape
  2. scoring: defensive_ehp_hard_control values the removal (>0)
  3. end-to-end: a failed save Incapacitates + registers the CHA re-save
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_hard_control
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
    return dict(_registry().get("feature", "f_banishment")["action_template"])


def _wizard(int_score=18):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["int"]["score"] = int_score
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": abilities,
                               "cr": {"proficiency_bonus": 4}, "actions": [],
                               "spellcasting_ability": "intelligence"},
                   side="pc", hp_current=40, hp_max=40, ac=15,
                   position=(0, 0), speed={"walk": 30}, abilities=abilities,
                   spell_slots={4: 1})


def _enemy(cha_save=-3, attack_bonus=6, dmg="2d8"):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["cha"]["save"] = cha_save
    return Actor(id="demon", name="demon",
                   template={"id": "t", "name": "demon", "abilities": abilities,
                               "cr": {"proficiency_bonus": 3},
                               "actions": [{"id": "a", "name": "Claw",
                                              "type": "weapon_attack",
                                              "pipeline": [
                                                  {"primitive": "attack_roll",
                                                    "params": {"bonus": attack_bonus}},
                                                  {"primitive": "damage",
                                                    "params": {"dice": dmg,
                                                                 "type": "slashing"}}]}]},
                   side="enemy", hp_current=80, hp_max=80, ac=16,
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
        feat = _registry().get("feature", "f_banishment")
        self.assertEqual(feat["spell"]["level"], 4)
        self.assertEqual(feat["source"], "srd_5.2.1")
        save = _action()["pipeline"][0]["params"]
        self.assertEqual(save["ability"], "charisma")


class ScoringTest(unittest.TestCase):

    def test_removal_scores_positive(self):
        wiz = _wizard()
        demon = _enemy(cha_save=-3)
        state = _state([wiz, demon])
        self.assertGreater(
            defensive_ehp_hard_control(wiz, demon, _action(), state), 0.0)


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_failed_save_incapacitates_and_resaves(self):
        wiz = _wizard()
        demon = _enemy(cha_save=-10)
        state = _state([wiz, demon])
        chosen = {"kind": "hard_control", "action": _action(),
                    "target": demon, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertIn("co_incapacitated",
                       [c["condition_id"] for c in demon.applied_conditions])
        rs = [e for e in state.recurring_saves if e["target_id"] == "demon"]
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["ability"], "charisma")
        self.assertEqual(wiz.concentration_on["action_id"], "a_banishment")


if __name__ == "__main__":
    unittest.main()
