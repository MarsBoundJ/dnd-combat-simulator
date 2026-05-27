"""Paladin spellcasting v1 tests (PR #82).

Layers:
  1. Feature YAMLs load (f_bless, f_shield_of_faith)
  2. c_paladin L2 row includes f_bless + f_shield_of_faith
  3. pc_schema auto-attaches a_bless action for Paladin L2+
  4. pc_schema auto-attaches a_shield_of_faith for Paladin L2+
  5. Paladin L1 does NOT get either (no slots yet, no features)
  6. Bless candidate generation: emits per-ally offensive_buff
  7. Shield of Faith candidate: emits per-ally defensive_buff (BA)
  8. Bless scoring via offensive_ehp_buff_ally returns positive value
  9. Shield of Faith scoring via defensive_ehp_defensive_buff returns positive
 10. Cross-caster dedup: second cast of Bless on same ally returns 0
 11. End-to-end: Bless application registers attack_modifier on ally;
     ally's next attack gets +2 bonus
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
from engine.ai.ehp_scoring import offensive_ehp_buff_ally
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.modifiers import query_attack_modifiers, query_save_modifiers
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), ac=14,
                  cha_score=14, str_score=14):
    abilities = {
        "str": {"score": str_score, "save": (str_score-10)//2},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 1},
        "cha": {"score": cha_score, "save": (cha_score-10)//2},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [
            {"id": "a_sword", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll",
                    "params": {"kind": "melee", "bonus": 5,
                                 "reach_ft": 5}},
                  {"primitive": "damage",
                    "params": {"dice": "1d8", "modifier": 3,
                                 "type": "slashing"}},
              ]},
        ],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=30, hp_max=30, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _build_paladin(level=5):
    from engine.pc_schema import build_pc_template
    registry = load_content(CONTENT_ROOT, validate=True,
                              schema_root=SCHEMA_ROOT)
    pc_spec = {
        "id": f"paladin{level}",
        "class": "c_paladin",
        "level": level,
        "ability_scores": {"str": 16, "dex": 12, "con": 14,
                             "int": 10, "wis": 12, "cha": 16},
        "weapons": [{"id": "longsword", "name": "Longsword",
                      "damage_dice": "1d8",
                      "damage_type": "slashing",
                      "attack_ability": "str"}],
    }
    return build_pc_template(pc_spec, registry)


# ============================================================================
# Layer 1+2: feature YAML loading + class wiring
# ============================================================================

class FeatureLoadingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_bless_loads(self) -> None:
        feature = self.registry.get("feature", "f_bless")
        self.assertEqual(feature["spell"]["level"], 1)
        self.assertEqual(feature["spell"]["class"], "c_paladin")
        action = feature["action_template"]
        self.assertEqual(action["type"], "offensive_buff")
        self.assertEqual(action["spell_slot_level"], 1)
        self.assertEqual(action["slot"], "action")
        self.assertTrue(action["concentration"])
        self.assertEqual(action["named_effect"], "bless")

    def test_f_shield_of_faith_loads(self) -> None:
        feature = self.registry.get("feature", "f_shield_of_faith")
        action = feature["action_template"]
        self.assertEqual(action["type"], "defensive_buff")
        self.assertEqual(action["spell_slot_level"], 1)
        self.assertEqual(action["slot"], "bonus_action")
        self.assertTrue(action["concentration"])
        self.assertEqual(action["named_effect"], "shield_of_faith")

    def test_c_paladin_l2_lists_spells(self) -> None:
        rogue = self.registry.get("class", "c_paladin")
        l2_row = next(r for r in rogue["level_table"]
                          if r["level"] == 2)
        self.assertIn("f_bless", l2_row["features"])
        self.assertIn("f_shield_of_faith", l2_row["features"])


# ============================================================================
# Layer 3+4+5: pc_schema auto-attach
# ============================================================================

class PcSchemaAutoAttachTest(unittest.TestCase):

    def test_paladin_l2_has_bless_and_shield_of_faith(self) -> None:
        template = _build_paladin(level=2)
        ids = {a.get("id") for a in template["actions"]}
        self.assertIn("a_bless", ids)
        self.assertIn("a_shield_of_faith", ids)

    def test_paladin_l1_does_not_have_them(self) -> None:
        template = _build_paladin(level=1)
        ids = {a.get("id") for a in template["actions"]}
        self.assertNotIn("a_bless", ids)
        self.assertNotIn("a_shield_of_faith", ids)

    def test_bless_action_shape(self) -> None:
        template = _build_paladin(level=5)
        bless = next(a for a in template["actions"]
                          if a.get("id") == "a_bless")
        self.assertEqual(bless["spell_slot_level"], 1)
        self.assertEqual(bless["slot"], "action")
        self.assertEqual(bless["named_effect"], "bless")
        # Pipeline should have attack_modifier + save_modifier
        primitives = {step.get("primitive")
                        for step in bless.get("pipeline") or []}
        self.assertIn("attack_modifier", primitives)
        self.assertIn("save_modifier", primitives)

    def test_shield_of_faith_action_shape(self) -> None:
        template = _build_paladin(level=5)
        sof = next(a for a in template["actions"]
                        if a.get("id") == "a_shield_of_faith")
        self.assertEqual(sof["slot"], "bonus_action")
        self.assertEqual(sof["named_effect"], "shield_of_faith")
        step = sof["pipeline"][0]
        self.assertEqual(step["primitive"], "attack_modifier")
        self.assertEqual(step["params"]["modifier"], "ac_modifier")
        self.assertEqual(step["params"]["value"], 2)


# ============================================================================
# Layer 6+7: candidate generation
# ============================================================================

class CandidateGenerationTest(unittest.TestCase):

    def _make_paladin_actor(self, *, side="pc", position=(0, 0)):
        # Use the registry to get the full action set
        from engine.pc_schema import build_pc_template
        registry = load_content(CONTENT_ROOT, validate=True,
                                  schema_root=SCHEMA_ROOT)
        pc_spec = {
            "class": "c_paladin", "level": 5,
            "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                 "int": 10, "wis": 12, "cha": 16},
            "weapons": [{"id": "longsword", "name": "Longsword",
                          "damage_dice": "1d8",
                          "damage_type": "slashing",
                          "attack_ability": "str"}],
        }
        template = build_pc_template(pc_spec, registry)
        return Actor(
            id="paly", name="paly", template=template, side=side,
            hp_current=40, hp_max=40, ac=18,
            speed={"walk": 30}, position=position,
            abilities=template["abilities"],
            spell_slots=dict(template.get("spell_slots") or {}),
            spell_slots_max=dict(template.get("spell_slots") or {}),
        )

    def test_bless_emits_per_ally_offensive_buff(self) -> None:
        paladin = self._make_paladin_actor()
        ally1 = _make_actor("ally1", position=(1, 0))
        ally2 = _make_actor("ally2", position=(2, 0))
        enemy = _make_actor("enemy", side="enemy", position=(5, 0))
        state = _make_state([paladin, ally1, ally2, enemy])
        candidates = pipeline.generate_candidates(paladin, state,
                                                      slot="action")
        bless_candidates = [c for c in candidates
                              if c.get("action", {}).get("id") == "a_bless"]
        # One per ally (excluding paladin themselves per
        # offensive_buff dedup pattern from PR #44)
        self.assertEqual(len(bless_candidates), 2)

    def test_shield_of_faith_emits_per_ally_defensive_buff(self) -> None:
        paladin = self._make_paladin_actor()
        ally1 = _make_actor("ally1", position=(1, 0))
        ally2 = _make_actor("ally2", position=(2, 0))
        state = _make_state([paladin, ally1, ally2])
        candidates = pipeline.generate_candidates(paladin, state,
                                                      slot="bonus_action")
        sof_candidates = [c for c in candidates
                            if c.get("action", {}).get("id") == "a_shield_of_faith"]
        # defensive_buff per-ally enumeration (paladin counts as
        # ally self-target — 3 total)
        self.assertGreaterEqual(len(sof_candidates), 2)


# ============================================================================
# Layer 8+9: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_bless_scores_positive_value(self) -> None:
        paladin = _make_actor("paly", cha_score=16)
        ally = _make_actor("ally")
        state = _make_state([paladin, ally])
        from engine.loader import load_content
        registry = load_content(CONTENT_ROOT, validate=True,
                                  schema_root=SCHEMA_ROOT)
        bless = dict(registry.get("feature", "f_bless")["action_template"])
        score = offensive_ehp_buff_ally(paladin, ally, bless, state)
        # +2 attack bonus × ally DPR × 2.5 rounds. Should be > 0.
        self.assertGreater(score, 0)

    def test_shield_of_faith_scores_positive_value(self) -> None:
        paladin = _make_actor("paly")
        ally = _make_actor("ally")
        enemy = _make_actor("enemy", side="enemy", position=(1, 0))
        state = _make_state([paladin, ally, enemy])
        registry = load_content(CONTENT_ROOT, validate=True,
                                  schema_root=SCHEMA_ROOT)
        sof = dict(registry.get("feature", "f_shield_of_faith")
                       ["action_template"])
        score = defensive_ehp_defensive_buff(paladin, ally, sof, state)
        # +2 AC → 10% Δmiss × enemy DPR × buff rounds. > 0.
        self.assertGreater(score, 0)


# ============================================================================
# Layer 10: cross-caster dedup
# ============================================================================

class CrossCasterDedupTest(unittest.TestCase):

    def test_bless_dedups_on_already_blessed_ally(self) -> None:
        paladin1 = _make_actor("paly1", cha_score=16)
        paladin2 = _make_actor("paly2", cha_score=16, position=(1, 0))
        ally = _make_actor("ally", position=(2, 0))
        state = _make_state([paladin1, paladin2, ally])
        registry = load_content(CONTENT_ROOT, validate=True,
                                  schema_root=SCHEMA_ROOT)
        bless = dict(registry.get("feature", "f_bless")["action_template"])
        # Pre-apply a Bless from paladin1 to ally
        ally.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "ally", "modifier": "attack_bonus",
                          "value": 2},
            "source": {"type": "action_buff",
                          "action_id": "a_bless",
                          "caster_id": paladin1.id,
                          "named_effect": "bless"},
            "applied_at_round": 1,
            "owner_id": ally.id,
        })
        # Paladin2 trying to re-bless the same ally should score 0
        score = offensive_ehp_buff_ally(paladin2, ally, bless, state)
        self.assertEqual(score, 0)


# ============================================================================
# Layer 11: end-to-end attack modifier application
# ============================================================================

class EndToEndModifierTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_blessed_ally_gets_attack_bonus(self) -> None:
        # Apply Bless's attack_modifier directly to verify the
        # ally's attack roll receives the +2 bonus via query path.
        paladin = _make_actor("paly")
        ally = _make_actor("ally", position=(1, 0))
        enemy = _make_actor("enemy", side="enemy", position=(2, 0))
        state = _make_state([paladin, ally, enemy])
        # Register Bless's attack_modifier on the ally
        ally.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "ally", "when": "attacker_is_self",
                          "modifier": "attack_bonus", "value": 2},
            "source": {"type": "action_buff",
                          "action_id": "a_bless",
                          "caster_id": paladin.id,
                          "named_effect": "bless"},
            "applied_at_round": 1,
            "owner_id": ally.id,
        })
        # Query attack modifiers for ally attacking enemy
        result = query_attack_modifiers(ally, enemy, state)
        self.assertEqual(result.attack_bonus_modifier, 2)

    def test_blessed_ally_save_bonus_via_save_modifier(self) -> None:
        # Bless +2 to saves
        paladin = _make_actor("paly")
        ally = _make_actor("ally", position=(1, 0))
        state = _make_state([paladin, ally])
        ally.active_modifiers.append({
            "primitive": "save_modifier",
            "params": {"target": "ally", "modifier": "flat",
                          "value": 2},
            "source": {"type": "action_buff",
                          "action_id": "a_bless",
                          "caster_id": paladin.id,
                          "named_effect": "bless"},
            "applied_at_round": 1,
            "owner_id": ally.id,
        })
        result = query_save_modifiers(ally, "wisdom", state)
        self.assertEqual(result.save_bonus_modifier, 2)

    def test_shielded_ally_gets_ac_bonus(self) -> None:
        # Shield of Faith +2 AC via attack_modifier with ac_modifier
        paladin = _make_actor("paly")
        ally = _make_actor("ally", position=(1, 0), ac=14)
        enemy = _make_actor("enemy", side="enemy", position=(2, 0))
        state = _make_state([paladin, ally, enemy])
        ally.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "ally", "modifier": "ac_modifier",
                          "value": 2},
            "source": {"type": "action_buff",
                          "action_id": "a_shield_of_faith",
                          "caster_id": paladin.id,
                          "named_effect": "shield_of_faith"},
            "applied_at_round": 1,
            "owner_id": ally.id,
        })
        # Enemy attacking ally — query ally's ac_modifier
        result = query_attack_modifiers(enemy, ally, state)
        self.assertEqual(result.ac_modifier, 2)


if __name__ == "__main__":
    unittest.main()
