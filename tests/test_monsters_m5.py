"""SRD monster batch M5 (rating-1) — behavior tests.

Shape/primitive validation for every m_*.yaml is covered by the
data-driven test in test_monsters_m1.py. Rating-1 is the trivial-critter
tail (plain weapon attacks / multiattacks), so this file just pins the
multiattacks and confirms the roster loads + deals damage.
"""
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
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _monster(mid):
    return _registry().get("monster", mid)


def _actor_from(mid):
    m = _monster(mid)
    hp = m["combat"]["hit_points"]["average"]
    return Actor(id=mid, name=m["name"], template=m, side="enemy",
                   hp_current=max(hp, 1), hp_max=max(hp, 1), ac=m["combat"]["armor_class"],
                   speed={"walk": m["combat"]["speed"].get("walk", 30)},
                   position=(0, 0), abilities=m["abilities"])


def _dummy(*, ac=5, hp=120):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="pc", name="pc",
                   template={"id": "t", "name": "pc", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": [], "size": "medium"},
                   side="pc", hp_current=hp, hp_max=hp, ac=ac, position=(1, 0),
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


def _action(mid, action_id):
    return next(a for a in _monster(mid)["actions"] if a["id"] == action_id)


class M5BehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def test_m5_monsters_present(self):
        for mid in ("m_archelon", "m_axe_beak", "m_baboon", "m_badger", "m_blood_hawk",
                    "m_camel", "m_crab", "m_giant_seahorse", "m_giant_weasel",
                    "m_hippopotamus", "m_jackal", "m_octopus", "m_piranha",
                    "m_seahorse", "m_weasel"):
            self.assertEqual(_monster(mid)["source"], "srd_5.2.1")

    def test_seahorse_is_noncombatant(self):
        # The seahorse has no attack action — just a Bubble Dash bonus action.
        self.assertEqual(_monster("m_seahorse")["actions"], [])
        self.assertTrue(_monster("m_seahorse")["bonus_actions"])

    def test_archelon_multiattack_swings_twice(self):
        arch = _actor_from("m_archelon")
        pc = _dummy(ac=5, hp=80)
        st = _state([arch, pc])
        chosen = {"kind": "multiattack", "action": _action("m_archelon", "a_multiattack"),
                    "target": pc, "actor": arch}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_hippopotamus_multiattack_damages(self):
        hippo = _actor_from("m_hippopotamus")
        pc = _dummy(ac=1, hp=80)
        st = _state([hippo, pc])
        chosen = {"kind": "multiattack", "action": _action("m_hippopotamus", "a_multiattack"),
                    "target": pc, "actor": hippo}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(pc.hp_current, 80)

    def test_axe_beak_attacks(self):
        primitives_module.set_rng(random.Random(1))   # deterministic hit
        ab = _actor_from("m_axe_beak")
        pc = _dummy(ac=1, hp=40)
        st = _state([ab, pc])
        chosen = {"kind": "weapon_attack", "action": _action("m_axe_beak", "a_beak"),
                    "target": pc, "actor": ab}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        # The attack resolved (a beak attack roll was logged) and, on this
        # seeded hit, dealt damage.
        self.assertTrue([e for e in st.event_log if e.get("event") == "attack_roll"])
        self.assertLess(pc.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
