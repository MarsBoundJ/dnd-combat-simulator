"""SRD monster batch M9 — Spellcasters: Mage, Priest, Archmage.

These are the first pure spellcaster NPCs: a weapon/Arcane-Burst attack
plus a Spellcasting action whose listed spells are modeled as `casts:`
actions. The loader's monster_spellcasting expansion rewrites each `casts`
into the referenced spell's full effect (type + pipeline) at the caster's
spell save DC. This file pins the roster, confirms each caster carries a
`spellcasting` block and that every `casts` action/bonus-action expanded to
a runnable shape, and drives a save-cast (Fireball / Spirit Guardians) and
a spell-attack-flavored cast end-to-end.
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

CASTERS = ["m_mage", "m_priest", "m_archmage"]


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


def _casts(mid):
    """Every expanded `casts` action across actions + bonus_actions."""
    m = _monster(mid)
    out = []
    for grp in ("actions", "bonus_actions"):
        out += [a for a in m.get(grp, []) if a.get("casts")]
    return out


class M9CasterTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(9))

    def test_all_three_present(self):
        for mid in CASTERS:
            m = _monster(mid)
            self.assertEqual(m["source"], "srd_5.2.1")
            self.assertEqual(m["creature_type"], "humanoid")

    def test_each_has_a_spellcasting_block(self):
        for mid in CASTERS:
            m = _monster(mid)
            self.assertIn("spellcasting", m)
            self.assertIn(m["spellcasting"]["ability"], ("intelligence", "wisdom"))
            # the block stamps the template after expansion
            self.assertEqual(m["spellcasting_ability"], m["spellcasting"]["ability"])
            self.assertEqual(m["spell_save_dc"], m["spellcasting"]["save_dc"])

    def test_every_casts_action_expanded(self):
        for mid in CASTERS:
            casts = _casts(mid)
            self.assertTrue(casts, f"{mid} has no casts actions")
            for act in casts:
                self.assertIn("type", act, f"{mid}:{act['id']} did not expand")
                self.assertTrue(act.get("pipeline"),
                                  f"{mid}:{act['id']} expanded without a pipeline")

    def test_mage_fireball_save_cast_resolves(self):
        fireball = _action("m_mage", "a_cast_fireball")
        self.assertEqual(fireball["type"], "aoe_attack")
        mage = _actor_from("m_mage")
        target = _dummy(position=(3, 0), dex=-10, hp=120)
        st = _state([mage, target])
        chosen = {"kind": "aoe_attack", "action": fireball, "target": target,
                    "origin_point": (3, 0), "direction": (1, 0), "actor": mage}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertTrue([e for e in st.event_log if e.get("event") == "forced_save"])
        self.assertLess(target.hp_current, 120)

    def test_priest_spirit_guardians_aura_cast_resolves(self):
        sg = _action("m_priest", "a_cast_spirit_guardians")
        self.assertEqual(sg["type"], "persistent_aura")
        priest = _actor_from("m_priest")
        target = _dummy(hp=80)
        st = _state([priest, target])
        chosen = {"kind": sg["type"], "action": sg, "target": target, "actor": priest}
        # a persistent-aura cast should resolve without error and register
        # the named effect / aura on the caster
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertTrue(st.event_log)

    def test_priest_radiant_flame_attack_hits(self):
        rf = _action("m_priest", "a_radiant_flame")
        priest = _actor_from("m_priest")
        target = _dummy(ac=1, hp=80)
        st = _state([priest, target])
        chosen = {"kind": "weapon_attack", "action": rf, "target": target, "actor": priest}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(target.hp_current, 80)

    def test_archmage_arcane_burst_multiattack_swings_four_times(self):
        archmage = _actor_from("m_archmage")
        target = _dummy(ac=1, hp=200)
        st = _state([archmage, target])
        chosen = {"kind": "multiattack", "action": _action("m_archmage", "a_multiattack"),
                    "target": target, "actor": archmage}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(len([e for e in st.event_log if e.get("event") == "attack_roll"]), 4)


if __name__ == "__main__":
    unittest.main()
