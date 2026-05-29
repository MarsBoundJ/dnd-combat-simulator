"""Ensnaring Strike tests (PR #110).

RAW (PHB 2024, 1st-level Ranger spell):
  BA cast, concentration up to 1 minute. The next weapon hit (melee OR
  ranged) forces a STR save; on fail the target is Restrained + takes
  1d6 piercing per turn until the spell ends.

Structural twin of Searing Smite (PR #89), parallel module. Differs:
any weapon kind, no bonus damage, STR save, co_ensnared (Restrained
via inheritance + piercing).

Layers:
  1. co_ensnared loads + inherits co_restrained + has recurring_damage
  2. f_ensnaring_strike YAML loads with correct shape
  3. c_ranger L2 lists f_ensnaring_strike; pc_schema attaches the action
  4. register_armed / find_armed / clear_armed
  5. followup gating: only when armed; melee AND ranged both qualify
  6. followup on fail applies co_ensnared (Restrained + piercing tick),
     no bonus damage, clears the marker
  7. on success: no condition, marker cleared
  8. _caster_spell_save_dc is ability-aware (WIS for Ranger)
  9. end-to-end via _damage: armed Ranger weapon hit → ensnared
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import ensnaring_strike as es
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import (
    _ensnaring_strike_arm, _caster_spell_save_dc, _damage,
    PrimitiveRegistry,
)
from engine.pc_schema import build_pc_template


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _abilities(str_score=14, wis_score=10):
    return {
        "str": {"score": str_score, "save": (str_score - 10) // 2},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": wis_score, "save": (wis_score - 10) // 2},
        "cha": {"score": 10, "save": 0},
    }


def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  str_score=14, wis_score=10, actions=None,
                  template_extra=None):
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": _abilities(str_score, wis_score),
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": list(actions or []),
    }
    if template_extra:
        template.update(template_extra)
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position,
        abilities=_abilities(str_score, wis_score))


def _make_state(actors, registry=None):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    if registry is not None:
        st.content_registry = registry
    return st


_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


# ============================================================================
# Layer 1+2+3: content + class wiring
# ============================================================================

class ContentTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_co_ensnared_loads(self) -> None:
        cond = self.registry.get("condition", "co_ensnared")
        self.assertEqual(cond["scope"], "source_referencing")
        self.assertIn("co_restrained", cond["inherits_conditions"])
        prims = [e["primitive"] for e in cond["effects"]]
        self.assertIn("recurring_damage", prims)

    def test_f_ensnaring_strike_loads(self) -> None:
        feat = self.registry.get("feature", "f_ensnaring_strike")
        self.assertEqual(feat["granted_by"]["class"], "c_ranger")
        tmpl = feat["action_template"]
        self.assertEqual(tmpl["type"], "defensive_buff")
        self.assertEqual(tmpl["slot"], "bonus_action")
        self.assertTrue(tmpl["concentration"])
        self.assertEqual(tmpl["named_effect"], "ensnaring_strike")
        self.assertEqual(tmpl["pipeline"][0]["primitive"],
                            "ensnaring_strike_arm")

    def test_ranger_l2_attaches_action(self) -> None:
        pc_spec = {
            "id": "r2", "class": "c_ranger", "level": 2,
            "ability_scores": {"str": 12, "dex": 16, "con": 14,
                                  "int": 10, "wis": 16, "cha": 8},
            "weapons": [{"id": "longbow", "name": "Longbow",
                          "damage_dice": "1d8", "damage_type": "piercing",
                          "attack_ability": "dex"}],
        }
        template = build_pc_template(pc_spec, self.registry)
        ids = {a.get("id") for a in template["actions"]}
        self.assertIn("a_ensnaring_strike", ids)
        self.assertIn("f_ensnaring_strike",
                        template.get("features_known", []))


# ============================================================================
# Layer 4: armed marker lifecycle
# ============================================================================

class ArmedMarkerTest(unittest.TestCase):

    def test_register_find_clear(self) -> None:
        ranger = _make_actor("ranger")
        state = _make_state([ranger])
        es.register_armed(ranger, spell_save_dc=13,
                            action_id="a_ensnaring_strike", state=state)
        self.assertIsNotNone(es.find_armed_entry(ranger))
        es.clear_armed(ranger)
        self.assertIsNone(es.find_armed_entry(ranger))

    def test_arm_primitive_uses_wis_dc(self) -> None:
        # Ranger WIS 16 (+3), PB 2 → DC 8+3+2 = 13
        ranger = _make_actor(
            "ranger", wis_score=16,
            template_extra={"spellcasting_ability": "wisdom"})
        target = _make_actor("foe", side="enemy")
        state = _make_state([ranger, target])
        state.current_attack = {"actor": ranger, "target": target,
                                  "action": {"id": "a_ensnaring_strike"}}
        _ensnaring_strike_arm({}, state, EventBus())
        entry = es.find_armed_entry(ranger)
        self.assertEqual(entry["params"]["dc"], 13)


# ============================================================================
# Layer 8: ability-aware spell save DC
# ============================================================================

class SpellSaveDcTest(unittest.TestCase):

    def test_dc_uses_wisdom_when_stamped(self) -> None:
        ranger = _make_actor(
            "ranger", wis_score=18,
            template_extra={"spellcasting_ability": "wisdom"})
        # WIS 18 (+4), PB 2 → 8+4+2 = 14
        self.assertEqual(_caster_spell_save_dc(ranger), 14)

    def test_dc_falls_back_to_charisma(self) -> None:
        # No spellcasting_ability stamp → CHA default (CHA 10 → +0)
        ranger = _make_actor("nocaster")
        self.assertEqual(_caster_spell_save_dc(ranger), 10)   # 8+0+2


# ============================================================================
# Layer 5+6+7: followup gating + application
# ============================================================================

class FollowupTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def _armed_ranger_vs_foe(self, dc, *, str_score=8):
        registry = _registry()
        ranger = _make_actor("ranger")
        foe = _make_actor("foe", side="enemy", hp=40, ac=10,
                            str_score=str_score)
        state = _make_state([ranger, foe], registry=registry)
        es.register_armed(ranger, spell_save_dc=dc,
                            action_id="a_ensnaring_strike", state=state)
        return ranger, foe, state

    def test_not_armed_no_op(self) -> None:
        registry = _registry()
        ranger = _make_actor("ranger")
        foe = _make_actor("foe", side="enemy")
        state = _make_state([ranger, foe], registry=registry)
        state.current_attack = {"actor": ranger, "target": foe,
                                  "action": {"id": "a_bow"}, "state": "hit"}
        out = es.try_apply_ensnaring_strike_followup(
            ranger, foe, state, {"kind": "ranged"}, random.Random(1),
            is_crit=False)
        self.assertEqual(out, 0)
        self.assertFalse(any(c.get("condition_id") == "co_ensnared"
                               for c in foe.applied_conditions))

    def test_fail_save_applies_ensnared_no_bonus_damage(self) -> None:
        # High DC → guaranteed save failure → ensnared.
        ranger, foe, state = self._armed_ranger_vs_foe(dc=25)
        state.current_attack = {"actor": ranger, "target": foe,
                                  "action": {"id": "a_scimitar"},
                                  "state": "hit"}
        hp_before = foe.hp_current
        out = es.try_apply_ensnaring_strike_followup(
            ranger, foe, state, {"kind": "melee"}, random.Random(1),
            is_crit=False)
        # No direct bonus damage on the empowering hit
        self.assertEqual(out, 0)
        self.assertEqual(foe.hp_current, hp_before)
        # co_ensnared applied + co_restrained inherited
        cond_ids = {c.get("condition_id") for c in foe.applied_conditions}
        self.assertIn("co_ensnared", cond_ids)
        self.assertIn("co_restrained", cond_ids)
        # Recurring piercing tick registered
        ticks = [r for r in state.recurring_damage
                   if r.get("condition_id") == "co_ensnared"]
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0]["damage_type"], "piercing")
        # Marker consumed
        self.assertIsNone(es.find_armed_entry(ranger))

    def test_ranged_hit_also_triggers(self) -> None:
        # Unlike Searing Smite (melee only), Ensnaring fires on ranged.
        ranger, foe, state = self._armed_ranger_vs_foe(dc=25)
        state.current_attack = {"actor": ranger, "target": foe,
                                  "action": {"id": "a_longbow"},
                                  "state": "hit"}
        es.try_apply_ensnaring_strike_followup(
            ranger, foe, state, {"kind": "ranged"}, random.Random(1),
            is_crit=False)
        self.assertTrue(any(c.get("condition_id") == "co_ensnared"
                              for c in foe.applied_conditions))

    def test_success_save_no_condition(self) -> None:
        # DC 1 → guaranteed save success → no ensnare, marker cleared.
        ranger, foe, state = self._armed_ranger_vs_foe(dc=1, str_score=16)
        state.current_attack = {"actor": ranger, "target": foe,
                                  "action": {"id": "a_scimitar"},
                                  "state": "hit"}
        es.try_apply_ensnaring_strike_followup(
            ranger, foe, state, {"kind": "melee"}, random.Random(1),
            is_crit=False)
        self.assertFalse(any(c.get("condition_id") == "co_ensnared"
                               for c in foe.applied_conditions))
        self.assertIsNone(es.find_armed_entry(ranger))


# ============================================================================
# Layer 9: end-to-end via _damage
# ============================================================================

class EndToEndTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_damage_hook_fires_ensnare(self) -> None:
        registry = _registry()
        ranger = _make_actor("ranger", actions=[{
            "id": "a_scimitar", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "1d6", "modifier": 3,
                              "type": "slashing"}}]}])
        foe = _make_actor("foe", side="enemy", hp=50, ac=10, str_score=6)
        state = _make_state([ranger, foe], registry=registry)
        es.register_armed(ranger, spell_save_dc=25,
                            action_id="a_ensnaring_strike", state=state)
        state.current_attack = {
            "actor": ranger, "target": foe,
            "action": ranger.template["actions"][0], "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        _damage({"dice": "1d6", "modifier": 3, "type": "slashing"},
                state, EventBus())
        self.assertTrue(any(c.get("condition_id") == "co_ensnared"
                              for c in foe.applied_conditions))


if __name__ == "__main__":
    unittest.main()
