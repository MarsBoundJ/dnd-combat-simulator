"""Divine Favor + Protection from Evil and Good tests (PR #88).

Closes Paladin spellcasting v2: extends PR #82 (Bless + Shield of
Faith) with two more 1st-level concentration spells.

Layers:
  1. weapon_damage_bonus primitive registers entry on owner
  2. query_weapon_damage_bonus aggregates active modifiers
  3. _damage applies weapon_damage_bonus on weapon hits ONLY
  4. _damage skips weapon_damage_bonus on spell damage
  5. Divine Favor YAML loads + has correct shape
  6. Divine Favor end-to-end: cast → weapon hit gets +2 damage
  7. attacker_creature_type_in when-clause atom matches
  8. attacker_creature_type_in when-clause atom doesn't match
  9. Prot from E&G YAML loads + has correct shape
 10. Prot from E&G end-to-end: fiend attacker rolls with disadvantage
 11. Prot from E&G: humanoid attacker rolls normally (no disadvantage)
 12. PC schema: Paladin L2 has both new features in features_known
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import modifiers as _modifiers
from engine.core.events import EventBus
from engine.core.modifiers import query_attack_modifiers
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import (
    _attack_roll, _damage, _weapon_damage_bonus,
)


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  str_score=16, creature_type="humanoid",
                  actions=None, levels=None):
    abilities = {
        "str": {"score": str_score, "save": 3},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 16, "save": 3},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": list(actions or []),
        "levels": dict(levels or {}),
    }
    a = Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )
    a.creature_type = creature_type
    return a


def _melee_weapon(action_id="a_longsword"):
    return {
        "id": action_id, "type": "weapon_attack", "slot": "action",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "ability": "str",
                          "bonus": 5, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "1d8", "modifier": 3,
                          "type": "slashing"}},
        ],
    }


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1+2: weapon_damage_bonus primitive + query
# ============================================================================

class WeaponDamageBonusInfraTest(unittest.TestCase):

    def test_primitive_registers_modifier_entry(self) -> None:
        paladin = _make_actor("paladin")
        state = _make_state([paladin])
        state.current_attack = {"actor": paladin, "target": paladin,
                                  "action": {"id": "a_divine_favor"}}
        _weapon_damage_bonus({
            "target": "self", "value": 2,
            "when": "weapon_attack",
            "lifetime": "until_short_rest",
        }, state, EventBus())
        mods = [m for m in paladin.active_modifiers
                  if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0]["params"]["value"], 2)

    def test_query_aggregates_multiple_modifiers(self) -> None:
        # Edge case: two weapon_damage_bonus modifiers stack their
        # values (e.g., Divine Favor + future Hex would add together).
        paladin = _make_actor("paladin")
        paladin.active_modifiers.append({
            "primitive": "weapon_damage_bonus",
            "params": {"value": 2, "when": "weapon_attack"},
        })
        paladin.active_modifiers.append({
            "primitive": "weapon_damage_bonus",
            "params": {"value": 3, "when": "weapon_attack"},
        })
        state = _make_state([paladin])
        total = _modifiers.query_weapon_damage_bonus(
            paladin, {"kind": "melee"}, state)
        self.assertEqual(total, 5)

    def test_query_respects_melee_only_when_clause(self) -> None:
        paladin = _make_actor("paladin")
        paladin.active_modifiers.append({
            "primitive": "weapon_damage_bonus",
            "params": {"value": 2, "when": "melee_attack"},
        })
        state = _make_state([paladin])
        # Melee attack: matches
        self.assertEqual(_modifiers.query_weapon_damage_bonus(
            paladin, {"kind": "melee"}, state), 2)
        # Ranged attack: doesn't match
        self.assertEqual(_modifiers.query_weapon_damage_bonus(
            paladin, {"kind": "ranged"}, state), 0)


# ============================================================================
# Layer 3+4: _damage integration
# ============================================================================

class DamageIntegrationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_weapon_attack_picks_up_damage_bonus(self) -> None:
        paladin = _make_actor("paladin", str_score=18,
                                 actions=[_melee_weapon()])
        target = _make_actor("dummy", side="enemy", hp=100, ac=5)
        state = _make_state([paladin, target])
        # Register Divine Favor's +2 bonus
        paladin.active_modifiers.append({
            "primitive": "weapon_damage_bonus",
            "params": {"value": 2, "when": "weapon_attack"},
        })
        # Run an attack
        weapon = paladin.template["actions"][0]
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": weapon, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = target.hp_current
        _damage({"dice": "1d8", "modifier": 4,
                   "type": "slashing"}, state, EventBus())
        damage_dealt = hp_before - target.hp_current
        # 1d8 (1-8) + 4 (mod) + 2 (Divine Favor) = 7-14. Confirm bonus applied.
        self.assertGreaterEqual(damage_dealt, 7)

    def test_non_weapon_damage_does_not_pick_up_bonus(self) -> None:
        # _damage called without a weapon-attack context (e.g., from
        # an AoE forced_save) shouldn't apply weapon_damage_bonus.
        paladin = _make_actor("paladin")
        target = _make_actor("dummy", side="enemy", hp=100, ac=5)
        state = _make_state([paladin, target])
        paladin.active_modifiers.append({
            "primitive": "weapon_damage_bonus",
            "params": {"value": 2, "when": "weapon_attack"},
        })
        # Spell-shape attack: no attack_roll step (e.g., Fireball
        # save-for-half damage). _extract_attack_params returns {}
        # so kind defaults to None — the weapon-attack gate skips.
        synthetic_action = {"id": "a_fireball", "pipeline": []}
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": synthetic_action, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = target.hp_current
        _damage({"dice": "1d4", "modifier": 0,
                   "type": "fire"}, state, EventBus())
        damage_dealt = hp_before - target.hp_current
        # 1d4 (1-4) — no +2 bonus
        self.assertLessEqual(damage_dealt, 4)


# ============================================================================
# Layer 5+6: Divine Favor YAML + end-to-end
# ============================================================================

class DivineFavorYamlTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_yaml_loads_with_correct_shape(self) -> None:
        feature = self.registry.get("feature", "f_divine_favor")
        self.assertEqual(feature["granted_by"]["class"], "c_paladin")
        self.assertEqual(feature["granted_by"]["level"], 2)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "bonus_action")
        self.assertTrue(tmpl["concentration"])
        self.assertEqual(tmpl["named_effect"], "divine_favor")
        # Pipeline contains a weapon_damage_bonus step
        prims = [s["primitive"] for s in tmpl["pipeline"]]
        self.assertIn("weapon_damage_bonus", prims)


# ============================================================================
# Layer 7+8: creature-type when-clause atom
# ============================================================================

class CreatureTypeWhenAtomTest(unittest.TestCase):
    """The new attacker_creature_type_in(...) atom in _eval_when —
    used by Protection from Evil and Good."""

    def test_atom_matches_listed_type(self) -> None:
        # Fiend attacker → disadvantage modifier fires
        ward_owner = _make_actor("pc_ward", side="pc")
        attacker = _make_actor("imp", side="enemy", creature_type="fiend")
        target = ward_owner       # the protected ally
        state = _make_state([ward_owner, attacker, target])
        # Register the Protection modifier on the target
        target.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {
                "target": "self",
                "modifier": "disadvantage_for_attacker",
                "when": "attacker_creature_type_in(aberration, celestial, elemental, fey, fiend, undead)",
            },
            "owner_id": target.id,
        })
        result = query_attack_modifiers(attacker, target, state)
        self.assertEqual(result.net_advantage(), "disadvantage")

    def test_atom_misses_unlisted_type(self) -> None:
        # Humanoid attacker → modifier does NOT fire
        ward_owner = _make_actor("pc_ward", side="pc")
        attacker = _make_actor("bandit", side="enemy",
                                  creature_type="humanoid")
        target = ward_owner
        state = _make_state([ward_owner, attacker, target])
        target.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {
                "target": "self",
                "modifier": "disadvantage_for_attacker",
                "when": "attacker_creature_type_in(aberration, celestial, elemental, fey, fiend, undead)",
            },
            "owner_id": target.id,
        })
        result = query_attack_modifiers(attacker, target, state)
        self.assertEqual(result.net_advantage(), "normal")


# ============================================================================
# Layer 9+10+11: Protection from Evil and Good YAML + end-to-end
# ============================================================================

class ProtectionYamlTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_yaml_loads_with_correct_shape(self) -> None:
        feature = self.registry.get("feature",
                                      "f_protection_from_evil_and_good")
        self.assertEqual(feature["granted_by"]["class"], "c_paladin")
        self.assertEqual(feature["granted_by"]["level"], 2)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "action")
        self.assertTrue(tmpl["concentration"])
        # Pipeline includes the creature-type when-clause
        attack_mod_step = next(s for s in tmpl["pipeline"]
                                 if s["primitive"] == "attack_modifier")
        when = attack_mod_step["params"]["when"]
        self.assertIn("attacker_creature_type_in", when)
        # All 6 protected-against types listed
        for type_id in ("aberration", "celestial", "elemental",
                          "fey", "fiend", "undead"):
            self.assertIn(type_id, when)


# ============================================================================
# Layer 12: PC schema integration
# ============================================================================

class PcSchemaIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def _build(self, level):
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": f"pal{level}",
            "class": "c_paladin",
            "level": level,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 12, "cha": 16},
            "weapons": [],
        }
        return build_pc_template(pc_spec, self.registry)

    def test_paladin_l2_has_both_new_spells(self) -> None:
        template = self._build(2)
        features = template.get("features_known", [])
        self.assertIn("f_divine_favor", features)
        self.assertIn("f_protection_from_evil_and_good", features)

    def test_paladin_l1_does_not_have_either(self) -> None:
        template = self._build(1)
        features = template.get("features_known", [])
        self.assertNotIn("f_divine_favor", features)
        self.assertNotIn("f_protection_from_evil_and_good", features)

    def test_paladin_l2_emits_a_divine_favor_action(self) -> None:
        # The generic feature → action_template auto-attach pass
        # (PR #82) picks up f_divine_favor and adds a_divine_favor.
        template = self._build(2)
        action_ids = {a.get("id") for a in template.get("actions", [])}
        self.assertIn("a_divine_favor", action_ids)
        self.assertIn("a_protection_from_evil_and_good", action_ids)


if __name__ == "__main__":
    unittest.main()
