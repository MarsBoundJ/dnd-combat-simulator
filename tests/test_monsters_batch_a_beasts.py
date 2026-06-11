"""SRD monster Batch A (Animals appendix beasts/mounts/swarms) — behavior.

Load/shape + composable-primitive validation for every m_*.yaml is covered
data-driven by test_monsters_m1.py. This file exercises Batch A's offense:
the on-hit condition riders (Grappled / Restrained / Prone / Poisoned), a
multiattack, multi-type damage, and a presence/source sanity sweep.
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


def _dummy(eid="pc", *, ac=5, hp=200, position=(1, 0), **saves):
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


def _action(mid, action_id):
    return next(a for a in _monster(mid)["actions"] if a["id"] == action_id)


def _conds(a):
    return [c["condition_id"] for c in a.applied_conditions]


def _run(mid, action_id, target, *, kind="weapon_attack"):
    actor = _actor_from(mid)
    st = _state([actor, target])
    chosen = {"kind": kind, "action": _action(mid, action_id), "target": target, "actor": actor}
    pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
    return st


BATCH_A = (
    "m_bat", "m_cat", "m_deer", "m_eagle", "m_frog", "m_goat", "m_hawk",
    "m_lizard", "m_owl", "m_rat", "m_raven", "m_scorpion", "m_spider",
    "m_vulture", "m_flying_snake", "m_giant_rat", "m_mule", "m_pony",
    "m_giant_bat", "m_giant_centipede", "m_giant_owl", "m_draft_horse",
    "m_mastiff", "m_riding_horse", "m_warhorse", "m_swarm_of_insects",
    "m_swarm_of_venomous_snakes", "m_tyrannosaurus_rex",
)


class BatchABehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_batch_present_and_sourced(self):
        for mid in BATCH_A:
            self.assertEqual(_monster(mid)["source"], "srd_5.2.1", mid)

    def test_trex_bite_grapples_and_restrains(self):
        pc = _dummy(ac=1)
        _run("m_tyrannosaurus_rex", "a_bite", pc)
        self.assertIn("co_grappled", _conds(pc))
        self.assertIn("co_restrained", _conds(pc))

    def test_trex_tail_prones(self):
        pc = _dummy(ac=1)
        _run("m_tyrannosaurus_rex", "a_tail", pc)
        self.assertIn("co_prone", _conds(pc))

    def test_trex_multiattack_swings_twice(self):
        trex = _actor_from("m_tyrannosaurus_rex")
        pc = _dummy(ac=1)
        st = _state([trex, pc])
        chosen = {"kind": "multiattack",
                  "action": _action("m_tyrannosaurus_rex", "a_multiattack"),
                  "target": pc, "actor": trex}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_giant_centipede_bite_poisons(self):
        pc = _dummy(ac=1)
        _run("m_giant_centipede", "a_bite", pc)
        self.assertIn("co_poisoned", _conds(pc))

    def test_mastiff_bite_prones(self):
        pc = _dummy(ac=1)
        _run("m_mastiff", "a_bite", pc)
        self.assertIn("co_prone", _conds(pc))

    def test_venomous_snake_swarm_bites_damage(self):
        pc = _dummy(ac=1, hp=80)
        _run("m_swarm_of_venomous_snakes", "a_bites", pc)
        self.assertLess(pc.hp_current, 80)

    def test_flat_damage_attack_still_hits(self):
        # CR-0 critters deal a flat 1 on hit (dice "0", modifier 1).
        pc = _dummy(ac=1, hp=10)
        _run("m_bat", "a_bite", pc)
        self.assertLess(pc.hp_current, 10)


if __name__ == "__main__":
    unittest.main()
