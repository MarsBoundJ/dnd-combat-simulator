"""Slow tests — SRD spell batch 1.

AoE WIS save or co_slowed (−2 AC + DEX-save disadvantage enforced; speed
/ reaction / action-economy facets are spec). Per-creature turn-end
re-save. Concentration. 40-ft cube modeled as a 20-ft sphere.

Layers:
  1. f_slow + co_slowed load
  2. co_slowed's −2 AC is a real, query-able modifier
  3. end-to-end: in-sphere enemies are Slowed + re-save
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import modifiers, pipeline
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
    return dict(_registry().get("feature", "f_slow")["action_template"])


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


def _enemy(eid, position=(2, 0), wis_save=-10):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["wis"]["save"] = wis_save
    return Actor(id=eid, name=eid,
                   template={"id": "t", "name": eid, "abilities": abilities,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=40, hp_max=40, ac=15,
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
        feat = _registry().get("feature", "f_slow")
        self.assertEqual(feat["spell"]["level"], 3)
        self.assertEqual(feat["source"], "srd_5.2.1")
        co = _registry().get("condition", "co_slowed")
        self.assertEqual(co["scope"], "absolute")

    def test_ac_penalty_is_enforced(self):
        # Apply co_slowed and confirm the −2 reaches query_attack_modifiers
        wiz = _wizard()
        foe = _enemy("foe")
        state = _state([wiz, foe])
        state.current_attack = {"actor": wiz, "target": foe}
        primitives_module._apply_condition(
            {"condition_id": "co_slowed"}, state, EventBus())
        mods = modifiers.query_attack_modifiers(wiz, foe, state)
        self.assertEqual(mods.ac_modifier, -2)


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_in_sphere_slowed_and_resaves(self):
        wiz = _wizard()
        e1 = _enemy("e1", (4, 0), wis_save=-10)
        e2 = _enemy("e2", (6, 0), wis_save=-10)    # 2 sq = 10 ft from origin
        far = _enemy("far", (30, 0), wis_save=-10)  # 140 ft away
        state = _state([wiz, e1, e2, far])
        chosen = {"kind": "aoe_attack", "action": _action(),
                    "target": e1, "origin_point": (5, 0), "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        for e in (e1, e2):
            self.assertIn("co_slowed",
                           [c["condition_id"] for c in e.applied_conditions])
        self.assertNotIn("co_slowed",
                          [c["condition_id"] for c in far.applied_conditions])
        rs_targets = {e["target_id"] for e in state.recurring_saves}
        self.assertEqual(rs_targets, {"e1", "e2"})
        self.assertEqual(wiz.concentration_on["action_id"], "a_slow")


if __name__ == "__main__":
    unittest.main()
