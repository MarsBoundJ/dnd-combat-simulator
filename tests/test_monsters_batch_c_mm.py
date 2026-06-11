"""Monster Batch C (MM-only CR 0–1/4: blights, mephits, modrons, etc.) — behavior.

Load/shape + composable-primitive validation for every m_*.yaml is covered
data-driven by test_monsters_m1.py. This file exercises Batch C's offense:
the multiattack, the recharge save-effect breaths (Restrained / Blinded), the
1/Day Sticky Net, Faerie Dust's Charmed rider, the dual-type Insectile Rapier,
and a presence/source sweep.
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


BATCH_C = (
    "m_larva", "m_twig_blight", "m_animated_broom", "m_bullywug_warrior",
    "m_kenku", "m_kuo_toa", "m_modron_duodrone", "m_mud_mephit",
    "m_needle_blight", "m_pixie", "m_smoke_mephit", "m_troglodyte",
    "m_winged_kobold",
)


class BatchCBehaviorTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(11))

    def test_batch_present_and_sourced(self):
        for mid in BATCH_C:
            self.assertEqual(_monster(mid)["source"], "mm_2024", mid)

    def test_duodrone_multiattack_swings_twice(self):
        duo = _actor_from("m_modron_duodrone")
        pc = _dummy(ac=1)
        st = _state([duo, pc])
        chosen = {"kind": "multiattack",
                  "action": _action("m_modron_duodrone", "a_multiattack"),
                  "target": pc, "actor": duo}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_pixie_faerie_dust_charms_on_hit(self):
        pc = _dummy(ac=1)
        _run("m_pixie", "a_faerie_dust", pc)
        self.assertIn("co_charmed", _conds(pc))

    def test_kuo_toa_sticky_net_restrains_on_failed_save(self):
        pc = _dummy(dex=-10)  # near-auto-fail DEX
        _run("m_kuo_toa", "a_sticky_net", pc, kind="save_effect")
        self.assertIn("co_restrained", _conds(pc))

    def test_mud_mephit_breath_restrains_on_failed_save(self):
        pc = _dummy(dex=-10)
        _run("m_mud_mephit", "a_mud_breath", pc, kind="save_effect")
        self.assertIn("co_restrained", _conds(pc))

    def test_smoke_mephit_cinder_breath_blinds_on_failed_save(self):
        pc = _dummy(dex=-10)
        _run("m_smoke_mephit", "a_cinder_breath", pc, kind="save_effect")
        self.assertIn("co_blinded", _conds(pc))

    def test_bullywug_rapier_deals_piercing_and_poison(self):
        pc = _dummy(ac=1)
        st = _run("m_bullywug_warrior", "a_insectile_rapier", pc)
        types = {e.get("type") for e in st.event_log
                 if e.get("event") == "damage_dealt"}
        self.assertIn("piercing", types)
        self.assertIn("poison", types)

    def test_needle_blight_ranged_needles_land(self):
        pc = _dummy(ac=1)
        _run("m_needle_blight", "a_needles", pc)
        self.assertLess(pc.hp_current, 200)

    def test_larva_flat_bite_resolves(self):
        pc = _dummy(ac=1)
        _run("m_larva", "a_bite", pc)
        # CR-0 flat bite (1d4-1) lands without crashing the dice roller.
        self.assertLessEqual(pc.hp_current, 200)


if __name__ == "__main__":
    unittest.main()
