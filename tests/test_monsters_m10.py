"""MM (2024) monster batch M10 — CR 4: Aarakocra Aeromancer, Banshee,
Bone Naga, Bullywug Bog Sage.

First non-SRD batch (`source: mm_2024`). Pins the roster, the multiattack
shapes (including save_effect sub-actions — Banshee Horrify, Bone Naga
Serpentine Gaze), the `casts:` expansions (incl. the first at-will
spell-ATTACK cast on a regular action list: Bullywug Ray of Sickness),
and drives the Banshee's Deathly Wail emanation + Horrify save
end-to-end.
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

BATCH = ["m_aarakocra_aeromancer", "m_banshee", "m_bone_naga",
         "m_bullywug_bog_sage"]


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


class M10RosterTest(unittest.TestCase):

    def test_all_four_present_with_mm_source(self):
        for mid in BATCH:
            m = _monster(mid)
            self.assertEqual(m["source"], "mm_2024")
            self.assertEqual(m["cr"]["value"], 4)
            self.assertEqual(m["cr"]["xp"], 1100)

    def test_casters_carry_spellcasting_blocks(self):
        self.assertEqual(_monster("m_aarakocra_aeromancer")["spellcasting"],
                          {"ability": "wisdom", "save_dc": 13})
        self.assertEqual(_monster("m_bone_naga")["spellcasting"],
                          {"ability": "intelligence", "save_dc": 13})
        bw = _monster("m_bullywug_bog_sage")["spellcasting"]
        self.assertEqual(bw["attack_bonus"], 5)

    def test_every_casts_action_expanded(self):
        for mid in BATCH:
            for act in _monster(mid).get("actions", []):
                if act.get("casts"):
                    self.assertIn("type", act, f"{mid}:{act['id']} did not expand")
                    self.assertTrue(act.get("pipeline"),
                                      f"{mid}:{act['id']} expanded without a pipeline")

    def test_ray_of_sickness_builds_at_monster_attack_bonus(self):
        ray = _action("m_bullywug_bog_sage", "a_cast_ray_of_sickness")
        self.assertEqual(ray["type"], "weapon_attack")
        atk = next(s for s in ray["pipeline"]
                    if s["primitive"] == "attack_roll")
        self.assertEqual(atk["params"]["bonus"], 5)
        dmg = next(s for s in ray["pipeline"] if s["primitive"] == "damage")
        self.assertEqual(dmg["params"]["dice"], "2d8")
        self.assertEqual(dmg["params"]["type"], "poison")


class M10BansheeTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(10))

    def test_multiattack_two_touches_one_horrify(self):
        banshee = _actor_from("m_banshee")
        target = _dummy(ac=1, hp=120, wis=-10)
        st = _state([banshee, target])
        chosen = {"kind": "multiattack",
                    "action": _action("m_banshee", "a_multiattack"),
                    "target": target, "actor": banshee}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        attacks = [e for e in st.event_log if e.get("event") == "attack_roll"]
        saves = [e for e in st.event_log if e.get("event") == "forced_save"]
        self.assertEqual(len(attacks), 2)     # two Corrupting Touch swings
        self.assertEqual(len(saves), 1)       # one Horrify save
        self.assertTrue(any(c.get("condition_id") == "co_frightened"
                              for c in target.applied_conditions))

    def test_deathly_wail_emanation_spares_banshee_hits_others(self):
        banshee = _actor_from("m_banshee")
        near = _dummy("near", position=(1, 0), con=-10, hp=50)
        far = _dummy("far", position=(20, 0), con=-10, hp=50)   # 100 ft away
        st = _state([banshee, near, far])
        wail = _action("m_banshee", "a_deathly_wail")
        self.assertEqual(wail["recharge"], "daily:1")
        chosen = {"kind": "aoe_attack", "action": wail, "target": near,
                    "origin_point": banshee.position, "actor": banshee}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(near.hp_current, 50)      # in the 30-ft emanation
        self.assertEqual(far.hp_current, 50)      # outside it
        self.assertEqual(banshee.hp_current, banshee.hp_max)  # self-excluded


class M10BoneNagaTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(10))

    def test_multiattack_bite_plus_gaze(self):
        naga = _actor_from("m_bone_naga")
        target = _dummy(ac=1, hp=120, wis=-10)
        st = _state([naga, target])
        chosen = {"kind": "multiattack",
                    "action": _action("m_bone_naga", "a_multiattack"),
                    "target": target, "actor": naga}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        attacks = [e for e in st.event_log if e.get("event") == "attack_roll"]
        saves = [e for e in st.event_log if e.get("event") == "forced_save"]
        self.assertEqual(len(attacks), 1)     # one Bite
        self.assertEqual(len(saves), 1)       # one Serpentine Gaze
        self.assertTrue(any(c.get("condition_id") == "co_charmed"
                              for c in target.applied_conditions))

    def test_lightning_bolt_cast_is_line_aoe(self):
        bolt = _action("m_bone_naga", "a_cast_lightning_bolt")
        self.assertEqual(bolt["type"], "aoe_attack")
        self.assertEqual(bolt["recharge"], "daily:1")
        self.assertEqual(bolt["area"]["shape"], "line")


class M10AeromancerTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(10))

    def test_wind_staff_multiattack_double_tap(self):
        aero = _actor_from("m_aarakocra_aeromancer")
        target = _dummy(ac=1, hp=120)
        st = _state([aero, target])
        chosen = {"kind": "multiattack",
                    "action": _action("m_aarakocra_aeromancer", "a_multiattack"),
                    "target": target, "actor": aero}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        attacks = [e for e in st.event_log if e.get("event") == "attack_roll"]
        self.assertEqual(len(attacks), 2)
        # both bludgeoning + lightning riders landed
        self.assertLess(target.hp_current, 120)

    def test_gust_of_wind_cast_is_at_will(self):
        gust = _action("m_aarakocra_aeromancer", "a_cast_gust_of_wind")
        self.assertNotIn("recharge", gust)
        self.assertTrue(gust.get("pipeline"))


if __name__ == "__main__":
    unittest.main()
