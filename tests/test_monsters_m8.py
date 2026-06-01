"""SRD monster batch M8 — Adult Metallic Dragons (the first content to
combine all four monster systems: Recharge breath, both Legendary systems,
and a `casts` action that references a built spell).

Shape/primitive validation for every m_*.yaml is covered by the
data-driven test in test_monsters_m1.py. This file pins the
adult-metallic roster, confirms each primary breath carries
`recharge: "5-6"`, each dragon declares `legendary_resistance.uses` and a
non-empty `legendary_actions.options` list, spot-checks that a breath
resolves damage and an LA option resolves, and confirms each dragon's
`casts` actions expanded cleanly into a runnable spell effect.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import recharge
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
_REGISTRY = None

ADULT_METALLICS = [
    "m_adult_brass_dragon", "m_adult_bronze_dragon", "m_adult_copper_dragon",
    "m_adult_gold_dragon", "m_adult_silver_dragon",
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


def _dummy(eid="pc", *, ac=5, hp=140, position=(1, 0), **saves):
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
    """The recharge breath action (the one carrying a `recharge` field).

    Metallic dragons can carry a 1/Day spell cast that also rides the
    recharge gate ("daily:1"), so pick the "5-6" one explicitly.
    """
    return next(a for a in _monster(mid)["actions"] if a.get("recharge") == "5-6")


def _run_aoe(mid, action, target, *, origin, direction=None):
    actor = _actor_from(mid)
    st = _state([actor, target])
    chosen = {"kind": "aoe_attack", "action": action, "target": target,
                "origin_point": origin, "direction": direction, "actor": actor}
    pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
    return st


class AdultMetallicTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(8))

    def test_all_five_present(self):
        for mid in ADULT_METALLICS:
            m = _monster(mid)
            self.assertEqual(m["source"], "srd_5.2.1")
            self.assertEqual(m["creature_type"], "dragon")
            self.assertEqual(m["size"], "huge")
            self.assertIn("metallic", m.get("type_tags", []))

    def test_every_dragon_has_a_recharge_breath(self):
        for mid in ADULT_METALLICS:
            breath = _breath(mid)
            self.assertEqual(breath["recharge"], "5-6")
            self.assertEqual(breath["type"], "aoe_attack")
            self.assertIn(breath["area"]["shape"], ("line", "cone"))

    def test_every_dragon_has_legendary_resistance_and_actions(self):
        for mid in ADULT_METALLICS:
            m = _monster(mid)
            self.assertEqual(m["legendary_resistance"]["uses"], 3)
            self.assertEqual(m["legendary_actions"]["uses_per_round"], 3)
            opts = m["legendary_actions"]["options"]
            self.assertGreaterEqual(len(opts), 1)
            for opt in opts:
                self.assertIn("id", opt)
                self.assertIn("name", opt)

    def test_recharge_engine_gates_each_breath(self):
        for mid in ADULT_METALLICS:
            breath = _breath(mid)
            self.assertEqual(recharge.parse_die_range(recharge.recharge_spec(breath)), (5, 6))
            actor = _actor_from(mid)
            st = _state([actor, _dummy()])
            self.assertTrue(recharge.is_available(actor, breath))
            recharge.mark_spent(actor, breath, st)
            self.assertFalse(recharge.is_available(actor, breath))

    def test_brass_fire_breath_line_damages(self):
        target = _dummy(position=(1, 0), dex=-10, hp=140)
        st = _run_aoe("m_adult_brass_dragon", _breath("m_adult_brass_dragon"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertTrue([e for e in st.event_log if e.get("event") == "forced_save"])
        self.assertLess(target.hp_current, 140)

    def test_silver_cold_breath_cone_damages(self):
        target = _dummy(position=(2, 0), con=-10, hp=160)
        st = _run_aoe("m_adult_silver_dragon", _breath("m_adult_silver_dragon"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertLess(target.hp_current, 160)

    def test_copper_slowing_breath_applies_slowed(self):
        target = _dummy(position=(2, 0), con=-10, hp=140)
        st = _run_aoe("m_adult_copper_dragon", _action("m_adult_copper_dragon", "a_slowing_breath"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertIn("co_slowed", [c["condition_id"] for c in target.applied_conditions])

    def test_bronze_repulsion_pushes_and_prones(self):
        target = _dummy(position=(2, 0), str=-10, hp=140)
        before = target.position
        st = _run_aoe("m_adult_bronze_dragon", _action("m_adult_bronze_dragon", "a_repulsion_breath"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertIn("co_prone", [c["condition_id"] for c in target.applied_conditions])
        self.assertGreater(target.position[0], before[0])

    def test_pounce_legendary_option_resolves_a_rend(self):
        pounce = next(o for o in _monster("m_adult_gold_dragon")["legendary_actions"]["options"]
                        if o["id"] == "la_pounce")
        actor = _actor_from("m_adult_gold_dragon")
        pc = _dummy(ac=1, hp=140)
        st = _state([actor, pc])
        chosen = {"kind": "multiattack", "action": pounce, "target": pc, "actor": actor}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(len([e for e in st.event_log if e.get("event") == "attack_roll"]), 1)
        self.assertLess(pc.hp_current, 140)

    def test_save_legendary_option_resolves_damage(self):
        # Giggling Magic (Copper) is a single-target CHA-save psychic LA.
        opt = next(o for o in _monster("m_adult_copper_dragon")["legendary_actions"]["options"]
                     if o["id"] == "la_giggling_magic")
        actor = _actor_from("m_adult_copper_dragon")
        pc = _dummy(hp=140, cha=-10)
        st = _state([actor, pc])
        chosen = {"kind": "save_effect", "action": opt, "target": pc, "actor": actor}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(pc.hp_current, 140)

    def test_casts_actions_expanded_into_runnable_spells(self):
        # The loader's monster_spellcasting expansion rewrites each `casts`
        # action into the referenced spell's full effect (type + pipeline),
        # stamping the monster's spell save DC. Only the dragons that cast a
        # SAVE/AoE spell are listed: spell-ATTACK spells (Scorching Ray /
        # Guiding Bolt) lack an action_template and so were deferred, not
        # built. The `casts` key is kept on the expanded action as
        # provenance — what proves expansion ran is the added type+pipeline.
        casters = {
            "m_adult_copper_dragon": "a_cast_mind_spike",
            "m_adult_gold_dragon": "a_cast_flame_strike",
            "m_adult_silver_dragon": "a_cast_hold_monster",
        }
        for mid, action_id in casters.items():
            m = _monster(mid)
            self.assertEqual(m["spellcasting_ability"], "charisma")
            act = _action(mid, action_id)
            self.assertIn("type", act, f"{mid}:{action_id} did not expand")
            self.assertTrue(act.get("pipeline"),
                              f"{mid}:{action_id} expanded without a pipeline")


if __name__ == "__main__":
    unittest.main()
