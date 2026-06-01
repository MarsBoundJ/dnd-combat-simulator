"""SRD monster batch M2 (rating-4) — behavior tests.

Shape/primitive validation for every m_*.yaml is already covered by the
data-driven test in test_monsters_m1.py (it globs the whole monsters dir).
This file exercises the M2-specific offense: multiattacks, save-effect
riders, and on-hit conditions (Prone / Paralyzed / Frightened / Grappled /
Poisoned) — all reusing existing conditions.
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


def _dummy(eid="pc", *, ac=5, hp=80, position=(1, 0), **saves):
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


class M2BehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_m2_monsters_present(self):
        for mid in ("m_berserker", "m_knight", "m_gladiator", "m_warrior_veteran",
                    "m_scout", "m_spy"):
            self.assertEqual(_monster(mid)["source"], "srd_5.2.1")

    def test_knight_multiattack_swings_twice(self):
        knight = _actor_from("m_knight")
        pc = _dummy(ac=5, hp=80)
        st = _state([knight, pc])
        chosen = {"kind": "multiattack", "action": _action("m_knight", "a_multiattack"),
                    "target": pc, "actor": knight}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_gladiator_shield_bash_prones(self):
        pc = _dummy(hp=60, str=-10)                  # near-auto-fail STR
        st = _run("m_gladiator", "a_shield_bash", pc, kind="save_effect")
        self.assertIn("co_prone", _conds(pc))
        self.assertLess(pc.hp_current, 60)

    def test_griffon_rend_grapples_on_hit(self):
        pc = _dummy(ac=1, hp=60)
        _run("m_griffon", "a_rend", pc)
        self.assertIn("co_grappled", _conds(pc))

    def test_brown_bear_claw_prones_on_hit(self):
        pc = _dummy(ac=1, hp=60)
        _run("m_brown_bear", "a_claw", pc)
        self.assertIn("co_prone", _conds(pc))

    def test_ghast_claw_paralyzes_on_failed_save(self):
        pc = _dummy(ac=1, hp=60, con=-10)
        _run("m_ghast", "a_claw", pc)
        self.assertIn("co_paralyzed", _conds(pc))

    def test_mummy_dreadful_glare_frightens(self):
        pc = _dummy(hp=60, wis=-10)
        _run("m_mummy", "a_dreadful_glare", pc, kind="save_effect")
        self.assertIn("co_frightened", _conds(pc))

    def test_vampire_spawn_claw_grapples_and_bite_damages(self):
        pc = _dummy(ac=1, hp=80, con=-10)
        _run("m_vampire_spawn", "a_claw", pc)
        self.assertIn("co_grappled", _conds(pc))
        pc2 = _dummy(hp=80, con=-10)
        _run("m_vampire_spawn", "a_bite", pc2, kind="save_effect")
        self.assertLess(pc2.hp_current, 80)

    def test_stirge_proboscis_attaches(self):
        pc = _dummy(ac=1, hp=40)
        _run("m_stirge", "a_proboscis", pc)
        self.assertIn("co_grappled", _conds(pc))

    def test_will_o_wisp_shock_damages(self):
        pc = _dummy(ac=1, hp=40)
        _run("m_will_o_wisp", "a_shock", pc)
        self.assertLess(pc.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
