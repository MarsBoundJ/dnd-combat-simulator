"""Monster Batch G (MM-only CR 4) — behavior.

Flameskull, Gnoll Fang of Yeenoghu, Helmed Horror, Juvenile Shadow Dragon,
Lizardfolk Sovereign, Shadow Demon, Swarm of Dretches.

Exercises multiattack swing-counts, dual damage types (Slashing+Necrotic,
Slashing+Force), on-hit conditions (Prone via Earthen Maul, Poisoned via
Bite), heterogeneous multiattack (Gnoll: 1×Bite + 2×Bone Flail), save_effect
(Shadow Breath — DEX DC 13, 5d6 Necrotic half on success), and swarm tag.
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
    chosen = {"kind": kind, "action": _action(mid, action_id),
              "target": target, "actor": actor}
    pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
    return st


BATCH_G = (
    "m_flameskull", "m_gnoll_fang_of_yeenoghu", "m_helmed_horror",
    "m_juvenile_shadow_dragon", "m_lizardfolk_sovereign",
    "m_shadow_demon", "m_swarm_of_dretches",
)


class BatchGPresenceTest(unittest.TestCase):
    """All 7 monsters are present, sourced correctly, and have expected metadata."""

    def test_all_present_and_sourced_mm_2024(self):
        for mid in BATCH_G:
            with self.subTest(mid=mid):
                m = _monster(mid)
                self.assertEqual(m["source"], "mm_2024")
                self.assertEqual(m["cr"]["value"], 4)

    def test_habitat_present(self):
        for mid in BATCH_G:
            with self.subTest(mid=mid):
                m = _monster(mid)
                self.assertIn("habitat", m)

    def test_treasure_present(self):
        for mid in BATCH_G:
            with self.subTest(mid=mid):
                m = _monster(mid)
                self.assertIn("treasure", m)

    def test_flameskull_magic_resistance_trait(self):
        traits = [t["id"] for t in _monster("m_flameskull").get("traits", [])]
        self.assertIn("t_magic_resistance", traits)

    def test_helmed_horror_spell_immunity_trait(self):
        traits = [t["id"] for t in _monster("m_helmed_horror").get("traits", [])]
        self.assertIn("t_spell_immunity", traits)

    def test_juvenile_shadow_dragon_living_shadow_trait(self):
        traits = [t["id"] for t in _monster("m_juvenile_shadow_dragon").get("traits", [])]
        self.assertIn("t_living_shadow", traits)

    def test_swarm_of_dretches_swarm_tag(self):
        self.assertIn("swarm", _monster("m_swarm_of_dretches").get("type_tags", []))


class FlameskulllTest(unittest.TestCase):
    """Flameskull: 2× Fire Ray, fire damage, Magic Resistance trait."""

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_flameskull", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_fire_ray_deals_fire_damage(self):
        pc = _dummy(ac=1, hp=500)
        for seed in range(20):
            primitives_module.set_rng(random.Random(seed))
            st = _run("m_flameskull", "a_fire_ray", pc)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                dmg = next(e for e in st.event_log if e.get("event") == "damage_dealt")
                self.assertEqual(dmg.get("type"), "fire")
                return
        self.fail("no hit in 20 seeds")


class GnollFangTest(unittest.TestCase):
    """Gnoll Fang: heterogeneous multiattack (1 Bite + 2 Bone Flail), Bite poisons."""

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_multiattack_swings_three_times(self):
        pc = _dummy(ac=1)
        st = _run("m_gnoll_fang_of_yeenoghu", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 3)

    def test_bite_applies_poisoned(self):
        for seed in range(30):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=200)
            st = _run("m_gnoll_fang_of_yeenoghu", "a_bite", pc)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                self.assertIn("co_poisoned", _conds(pc))
                return
        self.fail("no hit in 30 seeds")

    def test_bite_deals_piercing_and_poison_damage(self):
        for seed in range(30):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=500)
            st = _run("m_gnoll_fang_of_yeenoghu", "a_bite", pc)
            types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
            if types:
                self.assertIn("piercing", types)
                self.assertIn("poison", types)
                return
        self.fail("no hit in 30 seeds")

    def test_bone_flail_deals_piercing(self):
        for seed in range(20):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=500)
            st = _run("m_gnoll_fang_of_yeenoghu", "a_bone_flail", pc)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                dmg = next(e for e in st.event_log if e.get("event") == "damage_dealt")
                self.assertEqual(dmg.get("type"), "piercing")
                return
        self.fail("no hit in 20 seeds")


class HelmedHorrorTest(unittest.TestCase):
    """Helmed Horror: 2× Arcane Sword (Slashing + Force dual), AC 20."""

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_ac_is_20(self):
        self.assertEqual(_monster("m_helmed_horror")["combat"]["armor_class"], 20)

    def test_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_helmed_horror", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_arcane_sword_deals_slashing_and_force(self):
        for seed in range(20):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=500)
            st = _run("m_helmed_horror", "a_arcane_sword", pc)
            types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
            if types:
                self.assertIn("slashing", types)
                self.assertIn("force", types)
                return
        self.fail("no hit in 20 seeds")


class JuvenileShadowDragonTest(unittest.TestCase):
    """Juvenile Shadow Dragon: 2× Rend (Slashing+Necrotic), Shadow Breath save effect."""

    def setUp(self):
        primitives_module.set_rng(random.Random(4))

    def test_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_juvenile_shadow_dragon", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_rend_deals_slashing_and_necrotic(self):
        for seed in range(20):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=500)
            st = _run("m_juvenile_shadow_dragon", "a_rend", pc)
            types = {e.get("type") for e in st.event_log if e.get("event") == "damage_dealt"}
            if types:
                self.assertIn("slashing", types)
                self.assertIn("necrotic", types)
                return
        self.fail("no hit in 20 seeds")

    def test_shadow_breath_deals_necrotic_damage(self):
        primitives_module.set_rng(random.Random(99))
        pc = _dummy(ac=5, hp=200)
        st = _run("m_juvenile_shadow_dragon", "a_shadow_breath", pc, kind="save_effect")
        dmg_events = [e for e in st.event_log if e.get("event") == "damage_dealt"]
        self.assertTrue(len(dmg_events) >= 1)
        self.assertTrue(all(e.get("type") == "necrotic" for e in dmg_events))

    def test_shadow_breath_half_on_save_success(self):
        # Force success: pass a very high DEX save
        pc = _dummy(ac=5, hp=200, dex=20)
        full_pc = _dummy(eid="pc2", ac=5, hp=200, dex=-5)
        fail_dealt = []
        success_dealt = []
        for seed in range(40):
            primitives_module.set_rng(random.Random(seed))
            st_fail = _run("m_juvenile_shadow_dragon", "a_shadow_breath", full_pc,
                           kind="save_effect")
            dmg_f = sum(e.get("amount", 0) for e in st_fail.event_log
                        if e.get("event") == "damage_dealt")
            if dmg_f > 0:
                fail_dealt.append(dmg_f)
            primitives_module.set_rng(random.Random(seed))
            st_suc = _run("m_juvenile_shadow_dragon", "a_shadow_breath", pc,
                          kind="save_effect")
            dmg_s = sum(e.get("amount", 0) for e in st_suc.event_log
                        if e.get("event") == "damage_dealt")
            if dmg_s > 0:
                success_dealt.append(dmg_s)
        if fail_dealt and success_dealt:
            self.assertLess(sum(success_dealt) / len(success_dealt),
                            sum(fail_dealt) / len(fail_dealt))


class LizardfolkSovereignTest(unittest.TestCase):
    """Lizardfolk Sovereign: 1×Bite + 1×Earthen Maul; Maul applies Prone."""

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def test_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_lizardfolk_sovereign", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_earthen_maul_applies_prone_on_hit(self):
        for seed in range(30):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=200)
            st = _run("m_lizardfolk_sovereign", "a_earthen_maul", pc)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                self.assertIn("co_prone", _conds(pc))
                return
        self.fail("no hit in 30 seeds")

    def test_earthen_maul_deals_bludgeoning(self):
        for seed in range(20):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=500)
            st = _run("m_lizardfolk_sovereign", "a_earthen_maul", pc)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                dmg = next(e for e in st.event_log if e.get("event") == "damage_dealt")
                self.assertEqual(dmg.get("type"), "bludgeoning")
                return
        self.fail("no hit in 20 seeds")


class ShadowDemonTest(unittest.TestCase):
    """Shadow Demon: Umbral Claw deals Psychic; radiant vulnerability; resistances."""

    def setUp(self):
        primitives_module.set_rng(random.Random(6))

    def test_umbral_claw_deals_psychic(self):
        for seed in range(20):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=500)
            st = _run("m_shadow_demon", "a_umbral_claw", pc)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                dmg = next(e for e in st.event_log if e.get("event") == "damage_dealt")
                self.assertEqual(dmg.get("type"), "psychic")
                return
        self.fail("no hit in 20 seeds")

    def test_radiant_vulnerability_present(self):
        m = _monster("m_shadow_demon")
        self.assertIn("radiant", m.get("damage_vulnerabilities", []))

    def test_bps_resistances_present(self):
        m = _monster("m_shadow_demon")
        for dmg in ("bludgeoning", "piercing", "slashing"):
            self.assertIn(dmg, m.get("damage_resistances", []))

    def test_no_multiattack(self):
        actions = _monster("m_shadow_demon")["actions"]
        self.assertFalse(any(a["type"] == "multiattack" for a in actions))


class SwarmOfDretchesTest(unittest.TestCase):
    """Swarm of Dretches: 2× Rend slashing, swarm tag, resistances."""

    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_multiattack_swings_twice(self):
        pc = _dummy(ac=1)
        st = _run("m_swarm_of_dretches", "a_multiattack", pc, kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_rend_deals_slashing(self):
        for seed in range(20):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1, hp=500)
            st = _run("m_swarm_of_dretches", "a_rend", pc)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                dmg = next(e for e in st.event_log if e.get("event") == "damage_dealt")
                self.assertEqual(dmg.get("type"), "slashing")
                return
        self.fail("no hit in 20 seeds")

    def test_bps_resistances(self):
        m = _monster("m_swarm_of_dretches")
        for dmg in ("bludgeoning", "piercing", "slashing"):
            self.assertIn(dmg, m.get("damage_resistances", []))


if __name__ == "__main__":
    unittest.main()
