"""Monster Batch D (MM-only CR 1/2–1) — behavior.

CR 1/2: Gas Spore Fungus, Jackalwere, Modron Tridrone, Myconid Adult, Performer,
Piercer, Vine Blight.

CR 1: Empyrean Iota ×2, Faerie Dragon Youth, Kuo-toa Whip, Lacedon Ghoul, Manes
Vaporspawn, Modron Quadrone, Myconid Spore Servant, Ogrillon Ogre, Psychic Gray
Ooze, Salamander Fire Snake, Swarm of Larvae, Thri-kreen Marauder, Yuan-ti
Infiltrator.
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


BATCH_D = (
    "m_gas_spore_fungus", "m_jackalwere", "m_modron_tridrone", "m_myconid_adult",
    "m_performer", "m_piercer", "m_vine_blight",
    "m_empyrean_iota_celestial", "m_empyrean_iota_fiend", "m_faerie_dragon_youth",
    "m_kuo_toa_whip", "m_lacedon_ghoul", "m_manes_vaporspawn", "m_modron_quadrone",
    "m_myconid_spore_servant", "m_ogrillon_ogre", "m_psychic_gray_ooze",
    "m_salamander_fire_snake", "m_swarm_of_larvae", "m_thri_kreen_marauder",
    "m_yuan_ti_infiltrator",
)


class BatchDBehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(11))

    def test_batch_present_and_sourced(self):
        for mid in BATCH_D:
            self.assertEqual(_monster(mid)["source"], "mm_2024", mid)

    # ── multiattack swing-count checks ──────────────────────────────────────

    def test_jackalwere_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_jackalwere", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_modron_tridrone_multiattack_swings_thrice(self):
        pc = _dummy(ac=1)
        st = _run("m_modron_tridrone", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 3)

    def test_modron_quadrone_multiattack_swings_four_times(self):
        pc = _dummy(ac=1)
        st = _run("m_modron_quadrone", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 4)

    def test_lacedon_ghoul_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_lacedon_ghoul", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_yuan_ti_infiltrator_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_yuan_ti_infiltrator", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    # ── dual damage-type checks ──────────────────────────────────────────────

    def test_thri_kreen_gythka_deals_slashing_and_poison(self):
        pc = _dummy(ac=1)
        st = _run("m_thri_kreen_marauder", "a_gythka", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("slashing", types)
        self.assertIn("poison", types)

    def test_myconid_adult_slam_deals_bludgeoning_and_poison(self):
        pc = _dummy(ac=1)
        st = _run("m_myconid_adult", "a_slam", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("bludgeoning", types)
        self.assertIn("poison", types)

    def test_myconid_spore_servant_slam_deals_bludgeoning_and_poison(self):
        pc = _dummy(ac=1)
        st = _run("m_myconid_spore_servant", "a_slam", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("bludgeoning", types)
        self.assertIn("poison", types)

    def test_manes_vaporspawn_claw_deals_slashing_and_necrotic(self):
        pc = _dummy(ac=1)
        st = _run("m_manes_vaporspawn", "a_claw", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("slashing", types)
        self.assertIn("necrotic", types)

    def test_faerie_dragon_bite_deals_piercing_and_psychic(self):
        pc = _dummy(ac=1)
        st = _run("m_faerie_dragon_youth", "a_bite", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("piercing", types)
        self.assertIn("psychic", types)

    def test_salamander_fire_snake_bite_deals_piercing_and_fire(self):
        pc = _dummy(ac=1)
        st = _run("m_salamander_fire_snake", "a_bite", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("piercing", types)
        self.assertIn("fire", types)

    # ── on-hit condition checks ──────────────────────────────────────────────

    def test_gas_spore_tendril_poisons_on_hit(self):
        pc = _dummy(ac=1)
        _run("m_gas_spore_fungus", "a_tendril", pc)
        self.assertIn("co_poisoned", _conds(pc))

    def test_vine_blight_constricting_vine_grapples_on_hit(self):
        pc = _dummy(ac=1)
        _run("m_vine_blight", "a_constricting_vine", pc)
        self.assertIn("co_grappled", _conds(pc))

    def test_kuo_toa_whip_pincer_staff_grapples_on_hit(self):
        pc = _dummy(ac=1)
        _run("m_kuo_toa_whip", "a_pincer_staff", pc)
        self.assertIn("co_grappled", _conds(pc))

    # ── save-effect condition checks ─────────────────────────────────────────

    def test_jackalwere_sleep_gaze_incapacitates_on_failed_save(self):
        pc = _dummy(wis=-10)
        _run("m_jackalwere", "a_sleep_gaze", pc, kind="save_effect")
        self.assertIn("co_incapacitated", _conds(pc))

    def test_myconid_adult_pacifying_spores_stuns_on_failed_save(self):
        pc = _dummy(con=-10)
        _run("m_myconid_adult", "a_pacifying_spores", pc, kind="save_effect")
        self.assertIn("co_stunned", _conds(pc))

    def test_lacedon_ghoul_claw_paralysis_on_failed_save(self):
        pc = _dummy(ac=1, con=-10)
        _run("m_lacedon_ghoul", "a_claw", pc)
        self.assertIn("co_paralyzed", _conds(pc))

    def test_piercer_drop_deals_damage_on_failed_save(self):
        pc = _dummy(dex=-10)
        _run("m_piercer", "a_drop", pc, kind="save_effect")
        self.assertLess(pc.hp_current, 200)

    def test_psychic_gray_ooze_psychic_crush_deals_damage_on_failed_save(self):
        pc = _dummy(int=-10)
        _run("m_psychic_gray_ooze", "a_psychic_crush", pc, kind="save_effect")
        self.assertLess(pc.hp_current, 200)

    # ── basic attack resolution ──────────────────────────────────────────────

    def test_performer_shortsword_resolves(self):
        pc = _dummy(ac=1)
        _run("m_performer", "a_shortsword", pc)
        self.assertLessEqual(pc.hp_current, 200)

    def test_ogrillon_ogre_battleaxe_resolves(self):
        pc = _dummy(ac=1)
        _run("m_ogrillon_ogre", "a_battleaxe", pc)
        self.assertLess(pc.hp_current, 200)

    def test_empyrean_celestial_radiant_resolves(self):
        pc = _dummy(ac=1)
        st = _run("m_empyrean_iota_celestial", "a_otherworldly_strike", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("radiant", types)

    def test_empyrean_fiend_necrotic_resolves(self):
        pc = _dummy(ac=1)
        st = _run("m_empyrean_iota_fiend", "a_otherworldly_strike", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("necrotic", types)

    def test_swarm_of_larvae_bites_resolves(self):
        pc = _dummy(ac=1)
        _run("m_swarm_of_larvae", "a_bites", pc)
        self.assertLess(pc.hp_current, 200)


if __name__ == "__main__":
    unittest.main()
