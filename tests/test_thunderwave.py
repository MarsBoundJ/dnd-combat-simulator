"""Thunderwave tests — SRD spell batch 2 (self-burst, CON save 2d8 + push)."""
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
    return dict(_registry().get("feature", "f_thunderwave")["action_template"])


def _wiz():
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["int"] = {"score": 16, "save": 0}
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": [],
                               "spellcasting_ability": "intelligence", "size": "medium"},
                   side="pc", hp_current=14, hp_max=14, ac=12, position=(0, 0),
                   speed={"walk": 30}, abilities=ab, spell_slots={1: 1})


def _enemy(con_save=-10, hp=30, pos=(1, 0)):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["con"]["save"] = con_save
    return Actor(id="foe", name="foe",
                   template={"id": "t", "name": "foe", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": [],
                               "size": "medium"},
                   side="enemy", hp_current=hp, hp_max=hp, ac=14, position=pos,
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class ThunderwaveTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        a = _action()
        self.assertEqual(a["area"]["shape"], "sphere")
        self.assertEqual(a["area"]["radius_ft"], 15)
        on_fail = a["pipeline"][0]["params"]["on_fail"]
        prims = [s["primitive"] for s in on_fail]
        self.assertIn("damage", prims)
        self.assertIn("forced_movement", prims)

    def test_self_burst_damages_and_pushes(self):
        wiz = _wiz()
        foe = _enemy(con_save=-10, pos=(1, 0))       # adjacent, in the 15-ft burst
        state = _state([wiz, foe])
        chosen = {"kind": "aoe_attack", "action": _action(), "target": foe,
                    "origin_point": (0, 0), "actor": wiz}
        before = foe.position
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 30)
        # Pushed away from the caster (its x grew)
        self.assertGreater(foe.position[0], before[0])


if __name__ == "__main__":
    unittest.main()
