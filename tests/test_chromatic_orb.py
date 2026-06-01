"""Chromatic Orb tests — SRD spell batch 2 (ranged spell attack, 3d8)."""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import _build_leveled_spell_attack_action
from engine.primitives import PrimitiveRegistry

REPO_ROOT = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO_ROOT / "schema" / "content", validate=True,
                                   schema_root=REPO_ROOT / "schema" / "definitions")
    return _REGISTRY


def _abil():
    return {k: {"score": 10, "save": 0} for k in
            ("str", "dex", "con", "int", "wis", "cha")} | {"int": {"score": 18, "save": 0}}


def _action():
    return _build_leveled_spell_attack_action(
        "a_chromatic_orb", "Chromatic Orb", slot_level=1, range_ft=90,
        ability_scores=_abil(), proficiency_bonus=2, class_id="c_wizard",
        damage_dice="3d8", damage_type="fire", upcast_dice="1d8")


def _wiz():
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": _abil(),
                               "cr": {"proficiency_bonus": 2}, "actions": [],
                               "spellcasting_ability": "intelligence"},
                   side="pc", hp_current=12, hp_max=12, ac=12, position=(0, 0),
                   speed={"walk": 30}, abilities=_abil(), spell_slots={1: 2})


def _enemy(ac=5, hp=40):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="foe", name="foe",
                   template={"id": "t", "name": "foe", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=ac, position=(1, 0),
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class ChromaticOrbTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        self.assertEqual(_registry().get("feature", "f_chromatic_orb")["spell"]["level"], 1)

    def test_builder(self):
        a = _action()
        self.assertEqual(a["pipeline"][0]["params"]["bonus"], 4 + 2)   # INT+4, PB 2
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "3d8")

    def test_hits_and_damages(self):
        wiz, foe = _wiz(), _enemy(ac=5)
        state = _state([wiz, foe])
        chosen = {"kind": "weapon_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
