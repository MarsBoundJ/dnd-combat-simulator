"""SRD monster batch M1 (rating-5 roster) — load/shape + behavior tests.

The load/validate test is data-driven: it globs every m_*.yaml built by this
lane and checks the required stat-block shape + that each action's pipeline
uses only the composable primitives the guide allows (attack_roll, damage,
forced_save, apply_condition, forced_movement, multiattack sub_actions).
Targeted tests then exercise representative offense: a single attack, a
multiattack, a grapple/poison/paralyze/prone on-hit or save rider.
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
MONSTER_DIR = CONTENT_ROOT / "monsters"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


# Monsters this lane (batch M1) authored — keyed by file stem.
def _m1_ids():
    return sorted(p.stem for p in MONSTER_DIR.glob("m_*.yaml"))


def _monster(mid):
    return _registry().get("monster", mid)


def _actor_from(mid, *, side="enemy", position=(0, 0), hp=None):
    m = _monster(mid)
    hpv = hp if hp is not None else m["combat"]["hit_points"]["average"]
    return Actor(id=mid, name=m["name"], template=m, side=side,
                   hp_current=hpv, hp_max=hpv, ac=m["combat"]["armor_class"],
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


def _action(mid, action_id):
    return next(a for a in _monster(mid)["actions"] if a["id"] == action_id)


_ALLOWED_PRIMITIVES = {"attack_roll", "damage", "forced_save", "apply_condition",
                        "forced_movement", "recurring_save"}


class LoadShapeTest(unittest.TestCase):

    def test_every_monster_loads_with_required_fields(self):
        ids = _m1_ids()
        self.assertIn("m_bandit", ids)              # sanity: batch is present
        for mid in ids:
            m = _monster(mid)
            for field in ("id", "name", "source", "size", "creature_type",
                          "combat", "abilities", "cr"):
                self.assertIn(field, m, f"{mid} missing {field}")
            # SRD monsters are srd_5.2.1; summon-spell stat blocks for
            # PHB-only spells (Bestial Spirit, Celestial Spirit) are
            # our own re-expression -> user_authored; non-SRD Monster
            # Manual stat blocks (batch M10+) are mm_2024 (mechanics-only
            # re-expression — see MONSTER_BUILD_GUIDE.md provenance).
            self.assertIn(m["source"],
                          ("srd_5.2.1", "user_authored", "mm_2024"), mid)
            self.assertIn("walk", m["combat"]["speed"], f"{mid} needs a walk speed")

    def test_action_pipelines_use_only_composable_primitives(self):
        for mid in _m1_ids():
            for act in _monster(mid).get("actions", []):
                if act.get("type") == "multiattack":
                    # sub_actions must reference real action ids on the monster
                    ids = {a["id"] for a in _monster(mid)["actions"]}
                    for sid in act.get("sub_actions", []):
                        self.assertIn(sid, ids, f"{mid}:{act['id']} bad sub_action {sid}")
                    continue
                # `casts`-expanded actions (monster_spellcasting) borrow a
                # built spell's whole pipeline — richer than the hand-authored
                # monster whitelist (persistent_aura, buffs, …). Those are
                # validated by the spell library's own tests, not here.
                if act.get("casts"):
                    continue
                for step in act.get("pipeline", []):
                    self.assertIn(step["primitive"], _ALLOWED_PRIMITIVES,
                                    f"{mid}:{act['id']} uses {step['primitive']}")


class AttackBehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_bandit_scimitar_hits(self):
        bandit = _actor_from("m_bandit")
        pc = _dummy(ac=5, hp=40)
        st = _state([bandit, pc])
        chosen = {"kind": "weapon_attack", "action": _action("m_bandit", "a_scimitar"),
                    "target": pc, "actor": bandit}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(pc.hp_current, 40)

    def test_bandit_captain_multiattack_swings_twice(self):
        cap = _actor_from("m_bandit_captain")
        pc = _dummy(ac=5, hp=80)
        st = _state([cap, pc])
        chosen = {"kind": "multiattack", "action": _action("m_bandit_captain", "a_multiattack"),
                    "target": pc, "actor": cap}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        atk_rolls = [e for e in st.event_log if e.get("event") == "attack_roll"]
        self.assertEqual(len(atk_rolls), 2)


class RiderBehaviorTest(unittest.TestCase):
    """On-hit / save riders that apply existing conditions."""

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_ghoul_claw_paralyzes_on_failed_save(self):
        ghoul = _actor_from("m_ghoul")
        pc = _dummy(ac=1, hp=40, con=-10)            # low AC + near-auto-fail CON
        st = _state([ghoul, pc])
        chosen = {"kind": "weapon_attack", "action": _action("m_ghoul", "a_claw"),
                    "target": pc, "actor": ghoul}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_paralyzed", [c["condition_id"] for c in pc.applied_conditions])

    def test_wolf_bite_knocks_prone_on_hit(self):
        wolf = _actor_from("m_wolf")
        pc = _dummy(ac=1, hp=40)                      # low AC so the bite lands
        st = _state([wolf, pc])
        chosen = {"kind": "weapon_attack", "action": _action("m_wolf", "a_bite"),
                    "target": pc, "actor": wolf}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(pc.hp_current, 40)
        self.assertIn("co_prone", [c["condition_id"] for c in pc.applied_conditions])

    def test_wyvern_sting_poisons_on_hit(self):
        wyvern = _actor_from("m_wyvern")
        pc = _dummy(ac=1, hp=120)
        st = _state([wyvern, pc])
        chosen = {"kind": "weapon_attack", "action": _action("m_wyvern", "a_sting"),
                    "target": pc, "actor": wyvern}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_poisoned", [c["condition_id"] for c in pc.applied_conditions])

    def test_bugbear_grab_grapples_on_hit(self):
        bug = _actor_from("m_bugbear_warrior")
        pc = _dummy(ac=1, hp=60)
        st = _state([bug, pc])
        chosen = {"kind": "weapon_attack", "action": _action("m_bugbear_warrior", "a_grab"),
                    "target": pc, "actor": bug}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_grappled", [c["condition_id"] for c in pc.applied_conditions])

    def test_bugbear_stalker_quick_grapple_save(self):
        bug = _actor_from("m_bugbear_stalker")
        pc = _dummy(hp=60, dex=-10)                  # near-auto-fail DEX
        st = _state([bug, pc])
        ba = next(a for a in _monster("m_bugbear_stalker")["bonus_actions"]
                   if a["id"] == "ba_quick_grapple")
        chosen = {"kind": "save_effect", "action": ba, "target": pc, "actor": bug}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_grappled", [c["condition_id"] for c in pc.applied_conditions])


if __name__ == "__main__":
    unittest.main()
