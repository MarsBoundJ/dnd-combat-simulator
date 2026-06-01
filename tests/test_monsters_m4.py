"""SRD monster batch M4 (rating-2) — behavior tests.

Shape/primitive validation for every m_*.yaml is covered by the
data-driven test in test_monsters_m1.py. This file exercises M4
offense: multiattacks and on-hit/save riders applying existing
conditions (Prone / Grappled / Poisoned).
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


def _actor_from(mid, *, position=(0, 0)):
    m = _monster(mid)
    hp = m["combat"]["hit_points"]["average"]
    return Actor(id=mid, name=m["name"], template=m, side="enemy",
                   hp_current=hp, hp_max=hp, ac=m["combat"]["armor_class"],
                   speed={"walk": m["combat"]["speed"].get("walk", 30)},
                   position=position, abilities=m["abilities"])


def _dummy(eid="pc", *, ac=5, hp=120, position=(1, 0), **saves):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in saves.items():
        ab[k] = {"score": 10, "save": v}
    return Actor(id=eid, name=eid,
                   template={"id": "t", "name": eid, "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": [], "size": "medium"},
                   side="pc", hp_current=hp, hp_max=hp, ac=ac, position=position,
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


def _action(mid, action_id, group="actions"):
    return next(a for a in _monster(mid)[group] if a["id"] == action_id)


def _conds(a):
    return [c["condition_id"] for c in a.applied_conditions]


def _run(mid, action_id, target, *, kind="weapon_attack", group="actions"):
    actor = _actor_from(mid)
    st = _state([actor, target])
    chosen = {"kind": kind, "action": _action(mid, action_id, group),
                "target": target, "actor": actor}
    pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
    return st


class M4BehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(4))

    def test_m4_monsters_present(self):
        for mid in ("m_allosaurus", "m_ankylosaurus", "m_ape", "m_elephant",
                    "m_killer_whale", "m_crocodile", "m_giant_vulture",
                    "m_vampire_familiar", "m_swarm_of_piranhas", "m_lemure"):
            self.assertEqual(_monster(mid)["source"], "srd_5.2.1")

    def test_ankylosaurus_tail_prones(self):
        pc = _dummy(ac=1, hp=80)
        _run("m_ankylosaurus", "a_tail", pc)
        self.assertIn("co_prone", _conds(pc))

    def test_crocodile_bite_grapples(self):
        pc = _dummy(ac=1, hp=60)
        _run("m_crocodile", "a_bite", pc)
        self.assertIn("co_grappled", _conds(pc))

    def test_giant_crab_claw_grapples(self):
        pc = _dummy(ac=1, hp=40)
        _run("m_giant_crab", "a_claw", pc)
        self.assertIn("co_grappled", _conds(pc))

    def test_giant_vulture_gouge_poisons(self):
        pc = _dummy(ac=1, hp=60)
        _run("m_giant_vulture", "a_gouge", pc)
        self.assertIn("co_poisoned", _conds(pc))

    def test_constrictor_snake_constrict_grapples(self):
        pc = _dummy(hp=60, str=-10)
        _run("m_constrictor_snake", "a_constrict", pc, kind="save_effect")
        self.assertIn("co_grappled", _conds(pc))

    def test_ape_multiattack_swings_twice(self):
        ape = _actor_from("m_ape")
        pc = _dummy(ac=5, hp=60)
        st = _state([ape, pc])
        chosen = {"kind": "multiattack", "action": _action("m_ape", "a_multiattack"),
                    "target": pc, "actor": ape}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_killer_whale_bite_damages(self):
        pc = _dummy(ac=1, hp=80)
        _run("m_killer_whale", "a_bite", pc)
        self.assertLess(pc.hp_current, 80)


if __name__ == "__main__":
    unittest.main()
