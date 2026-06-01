"""SRD monster batch M7 — Adult Chromatic Dragons (the first consumers of
both Legendary systems on top of the Recharge breath).

Shape/primitive validation for every m_*.yaml is covered by the data-driven
test in test_monsters_m1.py. This file pins the adult-chromatic roster,
confirms each breath carries `recharge: "5-6"`, each dragon declares
`legendary_resistance.uses` and a non-empty `legendary_actions.options`
list, spot-checks that a breath resolves damage, asserts an LA option is a
valid ability_entry that resolves, and exercises the Legendary Resistance
engine hook (a spent charge flips a failed save to a success).
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import legendary_resistance, recharge
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
_REGISTRY = None

ADULT_CHROMATICS = [
    "m_adult_black_dragon", "m_adult_blue_dragon", "m_adult_green_dragon",
    "m_adult_red_dragon", "m_adult_white_dragon",
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


class AdultChromaticTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_all_five_present(self):
        for mid in ADULT_CHROMATICS:
            m = _monster(mid)
            self.assertEqual(m["source"], "srd_5.2.1")
            self.assertEqual(m["creature_type"], "dragon")
            self.assertEqual(m["size"], "huge")

    def test_every_dragon_has_a_recharge_breath(self):
        for mid in ADULT_CHROMATICS:
            breath = _breath(mid)
            self.assertEqual(breath["recharge"], "5-6")
            self.assertEqual(breath["type"], "aoe_attack")
            self.assertIn(breath["area"]["shape"], ("line", "cone"))

    def test_every_dragon_has_legendary_resistance_and_actions(self):
        for mid in ADULT_CHROMATICS:
            m = _monster(mid)
            self.assertEqual(m["legendary_resistance"]["uses"], 3)
            opts = m["legendary_actions"]["options"]
            self.assertEqual(m["legendary_actions"]["uses_per_round"], 3)
            self.assertGreaterEqual(len(opts), 1)
            # every option is a valid ability_entry (id + name at minimum)
            for opt in opts:
                self.assertIn("id", opt)
                self.assertIn("name", opt)

    def test_recharge_engine_gates_each_breath(self):
        for mid in ADULT_CHROMATICS:
            breath = _breath(mid)
            self.assertEqual(recharge.parse_die_range(recharge.recharge_spec(breath)), (5, 6))
            actor = _actor_from(mid)
            st = _state([actor, _dummy()])
            self.assertTrue(recharge.is_available(actor, breath))
            recharge.mark_spent(actor, breath, st)
            self.assertFalse(recharge.is_available(actor, breath))

    def test_black_acid_breath_line_damages(self):
        # 60-ft line along +x; enemy 5 ft away (1 square) fails DEX.
        target = _dummy(position=(1, 0), dex=-10, hp=120)
        st = _run_aoe("m_adult_black_dragon", _breath("m_adult_black_dragon"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertTrue([e for e in st.event_log if e.get("event") == "forced_save"])
        self.assertLess(target.hp_current, 120)

    def test_red_fire_breath_cone_damages(self):
        target = _dummy(position=(2, 0), dex=-10, hp=160)
        st = _run_aoe("m_adult_red_dragon", _breath("m_adult_red_dragon"),
                        target, origin=(0, 0), direction=(1, 0))
        self.assertLess(target.hp_current, 160)

    def test_pounce_legendary_option_resolves_a_rend(self):
        # Pounce is an LA option present on most adult chromatics; it makes
        # one Rend attack. Run it as a multiattack against a soft target.
        pounce = next(o for o in _monster("m_adult_white_dragon")["legendary_actions"]["options"]
                        if o["id"] == "la_pounce")
        actor = _actor_from("m_adult_white_dragon")
        pc = _dummy(ac=1, hp=120)
        st = _state([actor, pc])
        chosen = {"kind": "multiattack", "action": pounce, "target": pc, "actor": actor}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(len([e for e in st.event_log if e.get("event") == "attack_roll"]), 1)
        self.assertLess(pc.hp_current, 120)

    def test_save_legendary_option_resolves_damage(self):
        # Cloud of Insects (Black) is a single-target DEX-save poison LA.
        opt = next(o for o in _monster("m_adult_black_dragon")["legendary_actions"]["options"]
                     if o["id"] == "la_cloud_of_insects")
        actor = _actor_from("m_adult_black_dragon")
        pc = _dummy(hp=120, dex=-10)
        st = _state([actor, pc])
        chosen = {"kind": "save_effect", "action": opt, "target": pc, "actor": actor}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(pc.hp_current, 120)

    def test_legendary_resistance_flips_a_failed_save(self):
        # Seed the LR resource (cli._build_actor does this in real combat) and
        # confirm the engine hook spends a charge to convert a fail->success.
        actor = _actor_from("m_adult_green_dragon")
        actor.resources[legendary_resistance.RESOURCE_KEY] = \
            _monster("m_adult_green_dragon")["legendary_resistance"]["uses"]
        st = _state([actor, _dummy()])
        self.assertTrue(legendary_resistance.has_charge(actor))
        used = legendary_resistance.maybe_use(actor, st, ability="wisdom", dc=20)
        self.assertTrue(used)
        self.assertEqual(actor.resources[legendary_resistance.RESOURCE_KEY], 2)


if __name__ == "__main__":
    unittest.main()
