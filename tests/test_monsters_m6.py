"""SRD monster batch M6 — Dragon Wyrmlings (recharge breath weapons).

Shape/primitive validation for every m_*.yaml is covered by the
data-driven test in test_monsters_m1.py. This file pins the wyrmling
roster, confirms each breath weapon carries a `recharge` field, and
spot-checks that the area breaths actually resolve (line/cone damage +
the metallic status breaths' conditions).
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

WYRMLINGS = [
    "m_black_dragon_wyrmling", "m_blue_dragon_wyrmling", "m_green_dragon_wyrmling",
    "m_red_dragon_wyrmling", "m_white_dragon_wyrmling", "m_brass_dragon_wyrmling",
    "m_bronze_dragon_wyrmling", "m_copper_dragon_wyrmling", "m_gold_dragon_wyrmling",
    "m_silver_dragon_wyrmling",
]


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


def _action(mid, action_id):
    return next(a for a in _monster(mid)["actions"] if a["id"] == action_id)


def _breath(mid):
    """The recharge breath action (the one carrying a `recharge` field)."""
    return next(a for a in _monster(mid)["actions"] if a.get("recharge"))


def _run_aoe(mid, action, target, *, origin, direction=None):
    actor = _actor_from(mid)
    st = _state([actor, target])
    chosen = {"kind": "aoe_attack", "action": action, "target": target,
                "origin_point": origin, "direction": direction, "actor": actor}
    pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
    return st


class WyrmlingTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(6))

    def test_all_ten_present(self):
        for mid in WYRMLINGS:
            m = _monster(mid)
            self.assertEqual(m["source"], "srd_5.2.1")
            self.assertEqual(m["creature_type"], "dragon")

    def test_every_wyrmling_has_a_recharge_breath(self):
        for mid in WYRMLINGS:
            breath = _breath(mid)
            self.assertEqual(breath["recharge"], "5-6")
            self.assertEqual(breath["type"], "aoe_attack")
            self.assertIn(breath["area"]["shape"], ("line", "cone"))

    def test_black_acid_breath_line_damages(self):
        # 15-ft line along +x; enemy 5 ft away (1 square) fails DEX.
        target = _dummy(position=(1, 0), dex=-10, hp=60)
        st = _run_aoe("m_black_dragon_wyrmling", _breath("m_black_dragon_wyrmling"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertTrue([e for e in st.event_log if e.get("event") == "forced_save"])
        self.assertLess(target.hp_current, 60)

    def test_red_fire_breath_cone_damages(self):
        target = _dummy(position=(2, 0), dex=-10, hp=80)
        st = _run_aoe("m_red_dragon_wyrmling", _breath("m_red_dragon_wyrmling"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertLess(target.hp_current, 80)

    def test_copper_slowing_breath_applies_slowed(self):
        target = _dummy(position=(2, 0), con=-10, hp=60)
        st = _run_aoe("m_copper_dragon_wyrmling",
                        _action("m_copper_dragon_wyrmling", "a_slowing_breath"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertIn("co_slowed", [c["condition_id"] for c in target.applied_conditions])

    def test_bronze_repulsion_pushes_and_prones(self):
        target = _dummy(position=(2, 0), str=-10, hp=60)
        before = target.position
        st = _run_aoe("m_bronze_dragon_wyrmling",
                        _action("m_bronze_dragon_wyrmling", "a_repulsion_breath"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertIn("co_prone", [c["condition_id"] for c in target.applied_conditions])
        self.assertGreater(target.position[0], before[0])

    def test_recharge_engine_gates_breath(self):
        # The recharge engine parses the "5-6" spec and gates the breath:
        # available -> spent (unavailable) -> recharges on a [5,6] roll.
        from engine.core import recharge
        breath = _breath("m_blue_dragon_wyrmling")
        self.assertEqual(recharge.parse_die_range(recharge.recharge_spec(breath)), (5, 6))
        actor = _actor_from("m_blue_dragon_wyrmling")
        st = _state([actor, _dummy()])
        self.assertTrue(recharge.is_available(actor, breath))
        recharge.mark_spent(actor, breath, st)
        self.assertFalse(recharge.is_available(actor, breath))


if __name__ == "__main__":
    unittest.main()
