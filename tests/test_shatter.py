"""Shatter tests — SRD spell batch 2 (10-ft sphere, CON save 3d8 thunder)."""
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
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO_ROOT / "schema" / "content", validate=True,
                                   schema_root=REPO_ROOT / "schema" / "definitions")
    return _REGISTRY


def _action():
    return dict(_registry().get("feature", "f_shatter")["action_template"])


def _wiz():
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["int"] = {"score": 18, "save": 0}
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": ab,
                               "cr": {"proficiency_bonus": 3}, "actions": [],
                               "spellcasting_ability": "intelligence"},
                   side="pc", hp_current=20, hp_max=20, ac=13, position=(0, 0),
                   speed={"walk": 30}, abilities=ab, spell_slots={2: 1})


def _enemy(eid, pos, con_save=-5, hp=40):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["con"]["save"] = con_save
    return Actor(id=eid, name=eid,
                   template={"id": "t", "name": eid, "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=14, position=pos,
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class ShatterTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = _action()
        self.assertEqual(a["area"]["shape"], "sphere")
        self.assertEqual(a["area"]["radius_ft"], 10)

    def test_sphere_burst(self):
        wiz = _wiz()
        near = _enemy("near", (8, 0), con_save=-10)      # 1 sq from origin
        far = _enemy("far", (12, 0), con_save=-10)        # 20 ft from origin (outside 10-ft)
        state = _state([wiz, near, far])
        chosen = {"kind": "aoe_attack", "action": _action(), "target": near,
                    "origin_point": (8, 0), "actor": wiz}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in state.event_log
                         if e.get("event") == "forced_save"}
        self.assertEqual(save_targets, {"near"})
        self.assertLess(near.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
