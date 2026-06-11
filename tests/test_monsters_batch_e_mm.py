"""Monster Batch E (MM-only CR 2) — behavior.

Bulette Pup, Carrion Crawler, Faerie Dragon Adult, Githzerai Monk, Gnoll Pack
Lord, Lizardfolk Geomancer, Mage Apprentice, Modron Pentadrone, Myconid
Sovereign, Nothic, Peryton, Poltergeist, Quaggoth, Sahuagin Priest, Spined
Devil, Swarm of Stirges.

Exercises multiattack swing-counts (incl. mixed sub-action lists), dual damage
types, grapple-on-hit, AoE cone/cylinder saves (Paralysis Gas, Hail of Stone,
Euphoria Breath), save_effect damage (Rotting Gaze, Telekinetic Thrust), and the
carrion crawler's poison+paralysis tentacle save.
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


BATCH_E = (
    "m_bulette_pup", "m_carrion_crawler", "m_faerie_dragon_adult",
    "m_githzerai_monk", "m_gnoll_pack_lord", "m_lizardfolk_geomancer",
    "m_mage_apprentice", "m_modron_pentadrone", "m_myconid_sovereign",
    "m_nothic", "m_peryton", "m_poltergeist", "m_quaggoth",
    "m_sahuagin_priest", "m_spined_devil", "m_swarm_of_stirges",
)


class BatchEBehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(11))

    def test_batch_present_and_sourced(self):
        for mid in BATCH_E:
            self.assertEqual(_monster(mid)["source"], "mm_2024", mid)

    # ── multiattack swing-count checks ──────────────────────────────────────

    def test_githzerai_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_githzerai_monk", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_gnoll_pack_lord_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_gnoll_pack_lord", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_nothic_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_nothic", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_pentadrone_multiattack_swings_five_times(self):
        pc = _dummy(ac=1)
        st = _run("m_modron_pentadrone", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 5)

    def test_peryton_multiattack_makes_two_distinct_attacks(self):
        pc = _dummy(ac=1)
        st = _run("m_peryton", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    # ── dual damage-type checks ──────────────────────────────────────────────

    def test_githzerai_psi_strike_deals_bludgeoning_and_psychic(self):
        pc = _dummy(ac=1)
        st = _run("m_githzerai_monk", "a_psi_strike", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("bludgeoning", types)
        self.assertIn("psychic", types)

    def test_carrion_crawler_bite_deals_piercing_and_poison(self):
        pc = _dummy(ac=1)
        st = _run("m_carrion_crawler", "a_bite", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("piercing", types)
        self.assertIn("poison", types)

    def test_spined_devil_fork_deals_piercing_and_fire(self):
        pc = _dummy(ac=1)
        st = _run("m_spined_devil", "a_infernal_fork", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("piercing", types)
        self.assertIn("fire", types)

    def test_myconid_sovereign_slam_deals_bludgeoning_and_poison(self):
        pc = _dummy(ac=1)
        st = _run("m_myconid_sovereign", "a_slam", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("bludgeoning", types)
        self.assertIn("poison", types)

    # ── on-hit condition checks ──────────────────────────────────────────────

    def test_swarm_of_stirges_grapples_on_hit(self):
        pc = _dummy(ac=1)
        _run("m_swarm_of_stirges", "a_swarm_of_proboscises", pc)
        self.assertIn("co_grappled", _conds(pc))

    # ── save-effect / AoE checks ─────────────────────────────────────────────

    def test_carrion_crawler_tentacles_poison_and_paralyze_on_fail(self):
        pc = _dummy(con=-10)
        _run("m_carrion_crawler", "a_paralyzing_tentacles", pc, kind="save_effect")
        conds = _conds(pc)
        self.assertIn("co_poisoned", conds)
        self.assertIn("co_paralyzed", conds)

    def test_pentadrone_paralysis_gas_paralyzes_on_fail(self):
        pc = _dummy(con=-10)
        _run("m_modron_pentadrone", "a_paralysis_gas", pc, kind="aoe_attack")
        self.assertIn("co_paralyzed", _conds(pc))

    def test_faerie_dragon_euphoria_breath_incapacitates_on_fail(self):
        pc = _dummy(wis=-10)
        _run("m_faerie_dragon_adult", "a_euphoria_breath", pc, kind="aoe_attack")
        self.assertIn("co_incapacitated", _conds(pc))

    def test_lizardfolk_hail_of_stone_damages_and_prones_on_fail(self):
        pc = _dummy(con=-10)
        _run("m_lizardfolk_geomancer", "a_hail_of_stone", pc, kind="aoe_attack")
        self.assertIn("co_prone", _conds(pc))
        self.assertLess(pc.hp_current, 200)

    def test_nothic_rotting_gaze_deals_necrotic_on_fail(self):
        pc = _dummy(con=-10)
        st = _run("m_nothic", "a_rotting_gaze", pc, kind="save_effect")
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("necrotic", types)
        self.assertLess(pc.hp_current, 200)

    def test_poltergeist_telekinetic_thrust_deals_force_on_fail(self):
        pc = _dummy(str=-10)
        st = _run("m_poltergeist", "a_telekinetic_thrust", pc, kind="save_effect")
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("force", types)

    # ── basic attack resolution ──────────────────────────────────────────────

    def test_bulette_pup_bite_resolves(self):
        pc = _dummy(ac=1)
        _run("m_bulette_pup", "a_bite", pc)
        self.assertLess(pc.hp_current, 200)

    def test_mage_apprentice_arcane_burst_deals_force(self):
        pc = _dummy(ac=1)
        st = _run("m_mage_apprentice", "a_arcane_burst", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("force", types)

    def test_quaggoth_claw_resolves(self):
        pc = _dummy(ac=1)
        _run("m_quaggoth", "a_claw", pc)
        self.assertLess(pc.hp_current, 200)

    def test_sahuagin_priest_spectral_jaws_deals_force(self):
        pc = _dummy(ac=1)
        st = _run("m_sahuagin_priest", "a_spectral_jaws", pc)
        types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
        self.assertIn("force", types)


if __name__ == "__main__":
    unittest.main()
