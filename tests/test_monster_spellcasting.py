"""Monster spellcasting — a monster action that casts a built spell
(engine.core.monster_spellcasting + loader expansion + DC override).

Layers:
  1. expand_template: a `casts` action becomes the spell's full effect
     (type/area/pipeline copied; spell_slot_level dropped; id/name + gate
     kept; provenance recorded)
  2. spellcasting block stamps spellcasting_ability + spell_save_dc
  3. _caster_spell_save_dc honors the monster's explicit DC; falls back to
     the formula otherwise
  4. gating: an at-will cast is always a candidate; a daily:1 cast rides
     the recharge gate (filtered after one use)
  5. end-to-end: a referenced spell generates a candidate, executes, and
     forces saves at the monster's DC
  6. a dangling `casts` reference fails fast
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import monster_spellcasting as ms
from engine.core import recharge
from engine.core.events import EventBus
from engine.core.pipeline import generate_candidates, execute
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import PrimitiveRegistry
from engine.loader import load_content
from engine.primitives import _caster_spell_save_dc

REPO_ROOT = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO_ROOT / "schema" / "content",
                                   validate=True,
                                   schema_root=REPO_ROOT / "schema" / "definitions")
    return _REGISTRY


def _abil(intel=18):
    a = {k: {"score": 12, "save": 1}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    a["int"] = {"score": intel, "save": 4}
    return a


def _mage_template(*, save_dc=15, actions=None):
    return {"id": "m_test_mage", "name": "Test Mage", "abilities": _abil(),
            "size": "medium", "creature_type": "humanoid",
            "cr": {"proficiency_bonus": 3},
            "spellcasting": {"ability": "intelligence", "save_dc": save_dc},
            "actions": actions if actions is not None else [
                {"id": "a_cast_fireball", "name": "Fireball",
                  "casts": "f_fireball", "recharge": "daily:1"},
            ]}


def _build_mage(**kw):
    tpl = _mage_template(**kw)
    ms.expand_template(tpl, _registry())
    return tpl


def _mage_actor(tpl, pos=(0, 0)):
    return Actor(id="mage", name="mage", template=tpl, side="enemy",
                  hp_current=40, hp_max=40, ac=12, speed={"walk": 30},
                  position=pos, abilities=tpl["abilities"],
                  size="medium", creature_type="humanoid",
                  resources=dict(tpl.get("_resources") or {}))


def _target(actor_id="hero", pos=(2, 0)):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                  template={"id": "pc", "name": actor_id, "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=30, hp_max=30, ac=13,
                  speed={"walk": 30}, position=pos, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class ExpandTest(unittest.TestCase):

    def test_casts_becomes_spell_effect(self):
        tpl = _build_mage()
        a = next(x for x in tpl["actions"] if x["id"] == "a_cast_fireball")
        self.assertEqual(a["type"], "aoe_attack")           # from f_fireball
        self.assertEqual(a["area"]["shape"], "sphere")
        self.assertTrue(a.get("pipeline"))
        self.assertEqual(a["name"], "Fireball")             # monster label kept
        self.assertEqual(a["casts"], "f_fireball")          # provenance

    def test_slot_and_upcast_dropped(self):
        tpl = _build_mage()
        a = next(x for x in tpl["actions"] if x["id"] == "a_cast_fireball")
        self.assertNotIn("spell_slot_level", a)
        self.assertNotIn("upcast_scaling", a)

    def test_gate_applied(self):
        tpl = _build_mage()
        a = next(x for x in tpl["actions"] if x["id"] == "a_cast_fireball")
        self.assertEqual(a["recharge"], "daily:1")

    def test_at_will_has_no_gate(self):
        tpl = _build_mage(actions=[
            {"id": "a_cast_fb", "name": "Fireball", "casts": "f_fireball"}])
        a = tpl["actions"][0]
        self.assertNotIn("recharge", a)
        self.assertNotIn("feature_use", a)

    def test_spellcasting_block_stamped(self):
        tpl = _build_mage(save_dc=17)
        self.assertEqual(tpl["spellcasting_ability"], "intelligence")
        self.assertEqual(tpl["spell_save_dc"], 17)

    def test_dangling_reference_fails_fast(self):
        tpl = {"id": "m_bad", "name": "Bad", "abilities": _abil(),
               "actions": [{"id": "a_x", "name": "X", "casts": "f_not_real"}]}
        with self.assertRaises(KeyError):
            ms.expand_template(tpl, _registry())


class DCTest(unittest.TestCase):

    def test_explicit_dc_used_verbatim(self):
        tpl = _build_mage(save_dc=15)
        actor = _mage_actor(tpl)
        self.assertEqual(_caster_spell_save_dc(actor), 15)

    def test_formula_fallback_without_override(self):
        # No spellcasting.save_dc → 8 + PB(3) + INT mod(+4) = 15
        tpl = {"id": "m_f", "name": "F", "abilities": _abil(18),
               "cr": {"proficiency_bonus": 3},
               "spellcasting_ability": "intelligence", "actions": []}
        actor = _mage_actor(tpl)
        self.assertEqual(_caster_spell_save_dc(actor), 15)


class GatingTest(unittest.TestCase):
    """At-will is always available; daily:1 rides the recharge gate."""

    def _has(self, actor, state, action_id):
        return any(c["action"].get("id") == action_id
                    for c in generate_candidates(actor, state, slot="action"))

    def test_at_will_always_candidate(self):
        tpl = _build_mage(actions=[
            {"id": "a_fb", "name": "Fireball", "casts": "f_fireball"}])
        mage = _mage_actor(tpl)
        st = _state([mage, _target()])
        self.assertTrue(self._has(mage, st, "a_fb"))
        # Even after "using" it (no gate to spend), still available.
        recharge.mark_spent(mage, tpl["actions"][0], st)   # no-op (no recharge)
        self.assertTrue(self._has(mage, st, "a_fb"))

    def test_daily_cast_filtered_after_use(self):
        tpl = _build_mage()   # fireball recharge daily:1
        mage = _mage_actor(tpl)
        st = _state([mage, _target()])
        self.assertTrue(self._has(mage, st, "a_cast_fireball"))
        recharge.mark_spent(mage, tpl["actions"][0], st)
        self.assertFalse(self._has(mage, st, "a_cast_fireball"))


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_cast_fireball_forces_saves_at_monster_dc(self):
        tpl = _build_mage(save_dc=15)
        mage = _mage_actor(tpl, pos=(0, 0))
        h1 = _target("h1", pos=(2, 0))
        h2 = _target("h2", pos=(2, 1))
        st = _state([mage, h1, h2])
        cands = generate_candidates(mage, st, slot="action")
        fb = next(c for c in cands
                   if c["action"].get("id") == "a_cast_fireball")
        execute(fb, st, EventBus(), PrimitiveRegistry.with_defaults())
        saves = [e for e in st.event_log if e["event"] == "forced_save"]
        self.assertTrue(saves, "fireball should force DEX saves")
        self.assertTrue(all(e["dc"] == 15 for e in saves),
                         "saves use the monster's spell DC (15)")
        self.assertEqual(saves[0]["ability"], "dexterity")


# ---------------------------------------------------------------------------
# v2: spell-ATTACK casts, fail-fast, and casts in legendary_actions.options
# ---------------------------------------------------------------------------

class SpellAttackCastTest(unittest.TestCase):
    """A `casts` to a spell-ATTACK marker (pc_builder, no action_template)
    now builds a runnable ranged attack at the monster's spell bonus."""

    def _mage(self, *, attack_bonus=None, action):
        tpl = {"id": "m_caster", "name": "Caster", "abilities": _abil(18),
                "size": "medium", "creature_type": "humanoid",
                "cr": {"proficiency_bonus": 4},
                "spellcasting": {"ability": "intelligence", "save_dc": 16},
                "actions": [action]}
        if attack_bonus is not None:
            tpl["spellcasting"]["attack_bonus"] = attack_bonus
        ms.expand_template(tpl, _registry())
        return tpl

    def test_scorching_ray_expands_to_multi_ray_attack(self):
        tpl = self._mage(attack_bonus=8, action={
            "id": "a_sr", "name": "Scorching Ray", "casts": "f_scorching_ray"})
        a = tpl["actions"][0]
        self.assertEqual(a["type"], "weapon_attack")
        rolls = [s for s in a["pipeline"] if s["primitive"] == "attack_roll"]
        self.assertEqual(len(rolls), 3)                 # three rays
        self.assertTrue(all(r["params"]["bonus"] == 8 for r in rolls))
        self.assertNotIn("spell_slot_level", a)

    def test_attack_bonus_falls_back_to_ability_plus_pb(self):
        # No explicit attack_bonus: INT 18 (+4) + PB 4 = +8.
        tpl = self._mage(action={
            "id": "a_gb", "name": "Guiding Bolt", "casts": "f_guiding_bolt"})
        roll = tpl["actions"][0]["pipeline"][0]
        self.assertEqual(roll["params"]["bonus"], 8)

    def test_unexpandable_feature_fails_fast(self):
        # A feature with neither action_template nor a buildable pc_builder.
        feature = {"id": "f_bogus", "name": "Bogus"}
        with self.assertRaises(ValueError):
            ms._expand_action({"id": "a", "name": "A", "casts": "f_bogus"},
                              feature, attack_bonus=5)


class LegendaryAndBonusCastTest(unittest.TestCase):

    def test_casts_in_legendary_options_expands(self):
        tpl = {"id": "m_dragon", "name": "Dragon", "abilities": _abil(18),
                "cr": {"proficiency_bonus": 5},
                "spellcasting": {"ability": "charisma", "save_dc": 18},
                "actions": [],
                "legendary_actions": {"uses_per_round": 3, "options": [
                    {"id": "la_cast", "name": "Cast Fireball",
                      "casts": "f_fireball", "cost": 1}]}}
        ms.expand_template(tpl, _registry())
        opt = tpl["legendary_actions"]["options"][0]
        self.assertEqual(opt["type"], "aoe_attack")     # expanded
        self.assertTrue(opt.get("pipeline"))
        self.assertEqual(opt["cost"], 1)                # option fields kept

    def test_casts_in_bonus_actions_expands(self):
        tpl = {"id": "m_b", "name": "B", "abilities": _abil(18),
                "cr": {"proficiency_bonus": 3},
                "spellcasting": {"ability": "intelligence", "save_dc": 15},
                "actions": [],
                "bonus_actions": [
                    {"id": "ba_cast", "name": "Misty Fireball",
                      "casts": "f_fireball"}]}
        ms.expand_template(tpl, _registry())
        self.assertEqual(tpl["bonus_actions"][0]["type"], "aoe_attack")


if __name__ == "__main__":
    unittest.main()
