"""Vicious Mockery tests — SRD spell batch 2 (save-for-damage cantrip)."""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import _build_save_cantrip_action
from engine.primitives import PrimitiveRegistry

REPO_ROOT = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO_ROOT / "schema" / "content", validate=True,
                                   schema_root=REPO_ROOT / "schema" / "definitions")
    return _REGISTRY


def _action(level=1):
    return _build_save_cantrip_action("a_vicious_mockery", "Vicious Mockery", level,
                                         save_ability="wisdom", damage_type="psychic",
                                         die=6, range_ft=60)


def _bard():
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["cha"] = {"score": 18, "save": 0}
    return Actor(id="bard", name="bard",
                   template={"id": "t", "name": "bard", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": [],
                               "spellcasting_ability": "charisma"},
                   side="pc", hp_current=16, hp_max=16, ac=13, position=(0, 0),
                   speed={"walk": 30}, abilities=ab)


def _enemy(wis_save=-10, hp=30):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["wis"]["save"] = wis_save
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


class ViciousMockeryTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_loads(self):
        f = _registry().get("feature", "f_vicious_mockery")
        self.assertEqual(f["spell"]["level"], 0)
        self.assertEqual(f["granted_by"]["class"], "c_bard")

    def test_scaling(self):
        for lvl, n in [(1, 1), (5, 2), (11, 3), (17, 4)]:
            on_fail = _action(lvl)["pipeline"][0]["params"]["on_fail"][0]["params"]
            self.assertEqual(on_fail["dice"], f"{n}d6")
            self.assertEqual(on_fail["type"], "psychic")

    def test_failed_save_takes_psychic(self):
        bard, foe = _bard(), _enemy(wis_save=-10)
        state = _state([bard, foe])
        chosen = {"kind": "save_attack", "action": _action(), "target": foe, "actor": bard}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, 30)


class BardKnowsViciousMockeryTest(unittest.TestCase):
    """Wiring (grind bug D): a built Bard must actually HAVE Vicious Mockery
    — its only ranged damage option, so a concentrating Bard chips instead of
    idling. The feature + builder existed but were never granted/dispatched."""

    def _bard_actions(self, level):
        from engine.pc_schema import build_pc_template
        spec = {"class": "c_bard", "level": level,
                "ability_scores": {"str": 8, "dex": 14, "con": 12,
                                    "int": 10, "wis": 12, "cha": 18}}
        template = build_pc_template(spec, _registry())
        return {a.get("id"): a for a in template.get("actions", [])}

    def test_bard_has_vicious_mockery_from_level_1(self):
        self.assertIn("a_vicious_mockery", self._bard_actions(1))
        self.assertIn("a_vicious_mockery", self._bard_actions(13))

    def test_built_action_is_ranged_save_cantrip(self):
        vm = self._bard_actions(13)["a_vicious_mockery"]
        self.assertEqual(vm["type"], "save_attack")
        self.assertEqual(vm["spell_slot_level"], 0)         # cantrip, no slot
        self.assertEqual(vm["save_ability"], "wisdom")
        self.assertEqual(vm["range_ft"], 60)                # ranged chip option
        on_fail = vm["pipeline"][0]["params"]["on_fail"][0]["params"]
        self.assertEqual(on_fail["type"], "psychic")
        self.assertEqual(on_fail["dice"], "3d6")            # L13 → 3 dice


if __name__ == "__main__":
    unittest.main()
