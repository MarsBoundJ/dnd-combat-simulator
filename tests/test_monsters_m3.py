"""SRD monster batch M3 (rating-3) — behavior tests.

Shape/primitive validation for every m_*.yaml is covered by the
data-driven test in test_monsters_m1.py (it globs the monsters dir).
This file exercises M3-specific offense: multiattacks, save-effect
actions/bonus-actions, and on-hit conditions (Prone / Grappled /
Frightened / Restrained / Charmed) — all reusing existing conditions.
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


def _dummy(eid="pc", *, ac=5, hp=120, position=(1, 0), size="medium", **saves):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in saves.items():
        ab[k] = {"score": 10, "save": v}
    return Actor(id=eid, name=eid,
                   template={"id": "t", "name": eid, "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": [], "size": size},
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


class M3BehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_m3_monsters_present(self):
        for mid in ("m_lion", "m_tiger", "m_giant_scorpion", "m_ettin",
                    "m_pirate_captain", "m_cockatrice", "m_swarm_of_bats"):
            self.assertEqual(_monster(mid)["source"], "srd_5.2.1")

    def test_tiger_rend_prones(self):
        pc = _dummy(ac=1, hp=60)
        _run("m_tiger", "a_rend", pc)
        self.assertIn("co_prone", _conds(pc))

    def test_lion_roar_frightens(self):
        pc = _dummy(hp=60, wis=-10)
        _run("m_lion", "a_roar", pc, kind="save_effect")
        self.assertIn("co_frightened", _conds(pc))

    def test_giant_scorpion_multiattack_and_claw_grapple(self):
        scorp = _actor_from("m_giant_scorpion")
        pc = _dummy(ac=1, hp=120)
        st = _state([scorp, pc])
        chosen = {"kind": "multiattack",
                    "action": _action("m_giant_scorpion", "a_multiattack"),
                    "target": pc, "actor": scorp}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(len([e for e in st.event_log if e.get("event") == "attack_roll"]), 3)
        self.assertIn("co_grappled", _conds(pc))

    def test_giant_constrictor_constrict_grapples(self):
        pc = _dummy(hp=80, str=-10)
        _run("m_giant_constrictor_snake", "a_constrict", pc, kind="save_effect")
        self.assertIn("co_grappled", _conds(pc))

    def test_cockatrice_bite_restrains(self):
        pc = _dummy(ac=1, hp=60, con=-10)
        _run("m_cockatrice", "a_petrifying_bite", pc)
        self.assertIn("co_restrained", _conds(pc))

    def test_ettin_battleaxe_prones(self):
        pc = _dummy(ac=1, hp=80)
        _run("m_ettin", "a_battleaxe", pc)
        self.assertIn("co_prone", _conds(pc))

    def test_pirate_captain_charm(self):
        pc = _dummy(hp=80, wis=-10)
        _run("m_pirate_captain", "ba_captains_charm", pc, kind="save_effect", group="bonus_actions")
        self.assertIn("co_charmed", _conds(pc))

    def test_tough_boss_warhammer_pushes(self):
        boss = _actor_from("m_tough_boss")
        pc = _dummy(ac=1, hp=80, position=(1, 0))
        before = pc.position
        st = _state([boss, pc])
        chosen = {"kind": "weapon_attack", "action": _action("m_tough_boss", "a_warhammer"),
                    "target": pc, "actor": boss}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertGreater(pc.position[0], before[0])

    def test_mammoth_trample_prones(self):
        pc = _dummy(hp=120, dex=-10)
        _run("m_mammoth", "ba_trample", pc, kind="save_effect", group="bonus_actions")
        self.assertIn("co_prone", _conds(pc))


if __name__ == "__main__":
    unittest.main()
