"""Monster Batch F (MM-only CR 3) — behavior.

Displacer Beast, Flaming Skeleton, Githyanki Warrior, Goblin Hexer, Hook
Horror, Kuo-toa Monitor, Quaggoth Thonot, Scout Captain, Spectator, Swarm
of Lemures, Water Weird, Yeti, Yuan-ti Malison (Types 1-3).

Exercises multiattack swing-counts, dual damage types (bludgeoning+fire,
slashing+psychic, slashing+lightning, slashing+cold), on-hit conditions
(prone, grappled, restrained), save_effect (wounding ray necrotic, chilling
gaze paralysis, constrict grapple+restrain), and basic attack resolution.
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


def _action(mid, action_id, *, bucket="actions"):
    return next(a for a in _monster(mid)[bucket] if a["id"] == action_id)


def _conds(a):
    return [c["condition_id"] for c in a.applied_conditions]


def _run(mid, action_id, target, *, kind="weapon_attack", bucket="actions"):
    actor = _actor_from(mid)
    st = _state([actor, target])
    chosen = {"kind": kind, "action": _action(mid, action_id, bucket=bucket),
              "target": target, "actor": actor}
    pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
    return st


BATCH_F = (
    "m_displacer_beast", "m_flaming_skeleton", "m_githyanki_warrior",
    "m_goblin_hexer", "m_hook_horror", "m_kuo_toa_monitor",
    "m_quaggoth_thonot", "m_scout_captain", "m_spectator",
    "m_swarm_of_lemures", "m_water_weird", "m_yeti",
    "m_yuan_ti_malison_1", "m_yuan_ti_malison_2", "m_yuan_ti_malison_3",
)


class BatchFBehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(42))

    def test_batch_present_and_sourced(self):
        for mid in BATCH_F:
            self.assertEqual(_monster(mid)["source"], "mm_2024", mid)

    # ── multiattack swing-count checks ──────────────────────────────────────

    def test_displacer_beast_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_displacer_beast", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_flaming_skeleton_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_flaming_skeleton", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_githyanki_warrior_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_githyanki_warrior", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_hook_horror_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_hook_horror", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_yeti_multiattack_makes_two_claw_attacks(self):
        pc = _dummy(ac=1, con=10)
        st = _run("m_yeti", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    # ── dual damage-type checks ──────────────────────────────────────────────

    def test_flaming_skeleton_flame_scepter_deals_bludgeoning_and_fire(self):
        pc = _dummy(ac=1)
        st = _run("m_flaming_skeleton", "a_flame_scepter", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("bludgeoning", types)
        self.assertIn("fire", types)

    def test_githyanki_warrior_psi_blade_deals_slashing_and_psychic(self):
        pc = _dummy(ac=1)
        st = _run("m_githyanki_warrior", "a_psi_blade", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("slashing", types)
        self.assertIn("psychic", types)

    def test_kuo_toa_monitor_bone_whip_deals_slashing_and_lightning(self):
        pc = _dummy(ac=1)
        st = _run("m_kuo_toa_monitor", "a_bone_whip", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("slashing", types)
        self.assertIn("lightning", types)

    def test_quaggoth_thonot_claw_deals_slashing_and_psychic(self):
        pc = _dummy(ac=1)
        st = _run("m_quaggoth_thonot", "a_claw", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("slashing", types)
        self.assertIn("psychic", types)

    def test_yeti_claw_deals_slashing_and_cold(self):
        pc = _dummy(ac=1)
        st = _run("m_yeti", "a_claw", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("slashing", types)
        self.assertIn("cold", types)

    # ── on-hit condition checks ──────────────────────────────────────────────

    def test_displacer_beast_rend_prones_on_hit(self):
        pc = _dummy(ac=1)
        _run("m_displacer_beast", "a_rend", pc)
        self.assertIn("co_prone", _conds(pc))

    def test_water_weird_surge_grapples_and_restrains_on_hit(self):
        pc = _dummy(ac=1)
        _run("m_water_weird", "a_surge", pc)
        conds = _conds(pc)
        self.assertIn("co_grappled", conds)
        self.assertIn("co_restrained", conds)

    # ── save-effect checks ───────────────────────────────────────────────────

    def test_spectator_wounding_ray_deals_necrotic_on_fail(self):
        pc = _dummy(con=-10)
        st = _run("m_spectator", "a_wounding_ray", pc, kind="save_effect")
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("necrotic", types)
        self.assertLess(pc.hp_current, 200)

    def test_yeti_chilling_gaze_paralyzes_on_fail(self):
        pc = _dummy(con=-10)
        _run("m_yeti", "a_chilling_gaze", pc, kind="save_effect")
        self.assertIn("co_paralyzed", _conds(pc))

    def test_yuan_ti_malison_3_constrict_grapples_on_fail(self):
        pc = _dummy(str=-10)
        _run("m_yuan_ti_malison_3", "a_constrict", pc, kind="save_effect")
        conds = _conds(pc)
        self.assertIn("co_grappled", conds)
        self.assertIn("co_restrained", conds)

    # ── basic attack resolution ──────────────────────────────────────────────

    def test_goblin_hexer_hex_stick_deals_psychic(self):
        pc = _dummy(ac=1)
        st = _run("m_goblin_hexer", "a_hex_stick", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("psychic", types)

    def test_yuan_ti_malison_1_bite_resolves(self):
        pc = _dummy(ac=1)
        _run("m_yuan_ti_malison_1", "a_bite", pc)
        self.assertLess(pc.hp_current, 200)

    def test_yuan_ti_malison_2_bite_resolves(self):
        pc = _dummy(ac=1)
        _run("m_yuan_ti_malison_2", "a_bite", pc)
        self.assertLess(pc.hp_current, 200)

    def test_scout_captain_shortsword_resolves(self):
        pc = _dummy(ac=1)
        _run("m_scout_captain", "a_shortsword", pc)
        self.assertLess(pc.hp_current, 200)

    def test_swarm_of_lemures_vile_slime_resolves(self):
        pc = _dummy(ac=1)
        _run("m_swarm_of_lemures", "a_vile_slime", pc)
        self.assertLess(pc.hp_current, 200)

    def test_hook_horror_hook_resolves(self):
        pc = _dummy(ac=1)
        _run("m_hook_horror", "a_hook", pc)
        self.assertLess(pc.hp_current, 200)


if __name__ == "__main__":
    unittest.main()
