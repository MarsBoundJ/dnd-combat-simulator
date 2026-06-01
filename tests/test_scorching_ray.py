"""Scorching Ray tests — SRD spell batch 2 (three 2d6 fire rays)."""
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
        "a_scorching_ray", "Scorching Ray", slot_level=2, range_ft=120,
        ability_scores=_abil(), proficiency_bonus=3, class_id="c_wizard",
        damage_dice="2d6", damage_type="fire", ray_count=3)


def _wiz():
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": _abil(),
                               "cr": {"proficiency_bonus": 3}, "actions": [],
                               "spellcasting_ability": "intelligence"},
                   side="pc", hp_current=18, hp_max=18, ac=12, position=(0, 0),
                   speed={"walk": 30}, abilities=_abil(), spell_slots={2: 2})


def _enemy(ac=5, hp=60):
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


class ScorchingRayTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        self.assertEqual(_registry().get("feature", "f_scorching_ray")["spell"]["level"], 2)

    def test_three_ray_pipeline(self):
        a = _action()
        attacks = [s for s in a["pipeline"] if s["primitive"] == "attack_roll"]
        damages = [s for s in a["pipeline"] if s["primitive"] == "damage"]
        self.assertEqual(len(attacks), 3)
        self.assertEqual(len(damages), 3)
        self.assertNotIn("upcast_scaling", a)        # ray-count upcast deferred

    def test_three_rays_fire(self):
        wiz, foe = _wiz(), _enemy(ac=5)
        state = _state([wiz, foe])
        chosen = {"kind": "weapon_attack", "action": _action(), "target": foe, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        # Three attack rolls landed in the log; low AC → real damage dealt
        atk_rolls = [e for e in state.event_log if e.get("event") == "attack_roll"]
        self.assertEqual(len(atk_rolls), 3)
        self.assertLess(foe.hp_current, 60)


if __name__ == "__main__":
    unittest.main()
