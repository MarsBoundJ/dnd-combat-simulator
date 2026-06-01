"""Disintegrate tests — SRD spell batch 2 (DEX save or nothing, 10d6+40)."""
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
    return dict(_registry().get("feature", "f_disintegrate")["action_template"])


def _wiz():
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["int"] = {"score": 20, "save": 0}
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": ab,
                               "cr": {"proficiency_bonus": 4}, "actions": [],
                               "spellcasting_ability": "intelligence"},
                   side="pc", hp_current=40, hp_max=40, ac=15, position=(0, 0),
                   speed={"walk": 30}, abilities=ab, spell_slots={6: 1})


def _enemy(dex_save, hp=120):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["dex"]["save"] = dex_save
    return Actor(id="foe", name="foe",
                   template={"id": "t", "name": "foe", "abilities": ab,
                               "cr": {"proficiency_bonus": 3}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=18, position=(1, 0),
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class DisintegrateTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def test_loads(self):
        a = _action()
        self.assertEqual(a["type"], "save_attack")
        self.assertFalse(a["half_on_success"])
        self.assertEqual(a["pipeline"][0]["params"]["on_fail"][0]["params"]["modifier"], 40)
        self.assertEqual(a["pipeline"][0]["params"]["on_success"], [])

    def test_failed_save_takes_big_force(self):
        wiz, foe = _wiz(), _enemy(dex_save=-10)
        state = _state([wiz, foe])
        chosen = {"kind": "save_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 120 - foe.hp_current
        self.assertGreaterEqual(dealt, 50)           # 10d6+40 = 50..100
        self.assertLessEqual(dealt, 100)

    def test_success_takes_nothing(self):
        wiz, foe = _wiz(), _enemy(dex_save=100)      # auto-succeed
        state = _state([wiz, foe])
        chosen = {"kind": "save_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(foe.hp_current, 120)        # no half-on-success


if __name__ == "__main__":
    unittest.main()
