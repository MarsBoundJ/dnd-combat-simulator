"""Inflict Wounds tests — SRD spell batch 2.

Single-target save-for-half (CON save, 2d10 necrotic, +1d10/slot). Static
save_attack action_template; DC resolves dynamically from the caster.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.ehp_scoring import offensive_ehp_save_attack
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
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _action():
    return dict(_registry().get("feature", "f_inflict_wounds")["action_template"])


def _cleric():
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["wis"] = {"score": 18, "save": 0}
    return Actor(id="cle", name="cle",
                   template={"id": "t", "name": "cle", "abilities": ab,
                               "cr": {"proficiency_bonus": 3}, "actions": [],
                               "spellcasting_ability": "wisdom"},
                   side="pc", hp_current=24, hp_max=24, ac=16, position=(0, 0),
                   speed={"walk": 30}, abilities=ab, spell_slots={1: 2})


def _enemy(con_save=-5, hp=40):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["con"]["save"] = con_save
    return Actor(id="foe", name="foe",
                   template={"id": "t", "name": "foe", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=14, position=(1, 0),
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class InflictWoundsTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        f = _registry().get("feature", "f_inflict_wounds")
        self.assertEqual(f["spell"]["level"], 1)
        a = _action()
        self.assertEqual(a["type"], "save_attack")
        self.assertTrue(a["half_on_success"])
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "constitution")

    def test_scores_positive(self):
        cle, foe = _cleric(), _enemy()
        self.assertGreater(offensive_ehp_save_attack(cle, foe, _action(), _state([cle, foe])), 0.0)

    def test_failed_save_takes_full(self):
        cle, foe = _cleric(), _enemy(con_save=-10)   # near-guaranteed fail
        state = _state([cle, foe])
        chosen = {"kind": "save_attack", "action": _action(), "target": foe, "actor": cle}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        dealt = 40 - foe.hp_current
        self.assertGreaterEqual(dealt, 2)            # 2d10 on a fail
        self.assertLessEqual(dealt, 20)
        self.assertEqual(cle.spell_slots.get(1), 1)


if __name__ == "__main__":
    unittest.main()
