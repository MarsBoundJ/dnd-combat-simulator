"""Hypnotic Pattern tests — SRD spell batch 1.

AoE crowd control: every creature in the area makes a WIS save or is
Incapacitated, with a per-creature turn-end re-save. Concentration. The
30-ft cube is approximated as a 15-ft-radius sphere (forced_save's AoE
resolver supports sphere/cone/line, not cube).

Layers:
  1. f_hypnotic_pattern loads with the right shape
  2. scoring: offensive_ehp_aoe values the AoE lockdown (>0)
  3. end-to-end: in-sphere enemies are Incapacitated + re-save; an enemy
     outside the sphere is untouched
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.ehp_scoring import offensive_ehp_aoe
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
    return dict(_registry().get("feature", "f_hypnotic_pattern")["action_template"])


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
                   spell_slots={3: 1})


def _enemy(eid, position, wis_save=-10):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["wis"]["save"] = wis_save
    return Actor(id=eid, name=eid,
                   template={"id": "t", "name": eid, "abilities": abilities,
                               "cr": {"proficiency_bonus": 2},
                               "actions": [{"id": "a", "name": "Club",
                                              "type": "weapon_attack",
                                              "pipeline": [
                                                  {"primitive": "attack_roll",
                                                    "params": {"bonus": 4}},
                                                  {"primitive": "damage",
                                                    "params": {"dice": "1d8",
                                                                 "type": "bludgeoning"}}]}]},
                   side="enemy", hp_current=40, hp_max=40, ac=13,
                   position=position, speed={"walk": 30}, abilities=abilities)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class WiringTest(unittest.TestCase):

    def test_loads(self):
        feat = _registry().get("feature", "f_hypnotic_pattern")
        self.assertEqual(feat["spell"]["level"], 3)
        self.assertEqual(feat["source"], "srd_5.2.1")
        a = _action()
        self.assertEqual(a["type"], "aoe_attack")
        self.assertEqual(a["area"]["shape"], "sphere")
        self.assertTrue(a["concentration"])


class ScoringTest(unittest.TestCase):

    def test_aoe_lockdown_scores_positive(self):
        wiz = _wizard()
        e1 = _enemy("e1", (4, 0))
        e2 = _enemy("e2", (5, 0))
        state = _state([wiz, e1, e2])
        # Origin centered between the two enemies (within 15-ft radius)
        score = offensive_ehp_aoe(wiz, (4, 0), _action(), state)
        self.assertGreater(score, 0.0)


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_in_sphere_incapacitated_far_untouched(self):
        wiz = _wizard()
        e1 = _enemy("e1", (4, 0), wis_save=-10)
        e2 = _enemy("e2", (5, 0), wis_save=-10)   # 1 sq from origin = 5 ft
        far = _enemy("far", (20, 0), wis_save=-10)  # 80 ft away — outside
        state = _state([wiz, e1, e2, far])
        chosen = {"kind": "aoe_attack", "action": _action(),
                    "target": e1, "origin_point": (4, 0), "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        for e in (e1, e2):
            conds = [c["condition_id"] for c in e.applied_conditions]
            self.assertIn("co_incapacitated", conds)
        self.assertNotIn("co_incapacitated",
                          [c["condition_id"] for c in far.applied_conditions])
        # Re-saves registered only for the in-sphere enemies
        rs_targets = {e["target_id"] for e in state.recurring_saves}
        self.assertEqual(rs_targets, {"e1", "e2"})


if __name__ == "__main__":
    unittest.main()
