"""Compelled Duel tests (PR #104).

Paladin 1st-level hard-control spell: WIS save or the target has
disadvantage on attacks against anyone other than the caster. First
use of source-aware when-evaluation (the condition must know who cast
it). Also fixes spell-save-DC to use the caster's actual spellcasting
ability (CHA for Paladin, was hardcoded INT).

Layers:
  1. attack_target_is_not_source atom: True when attacking non-source
  2. ...False when attacking the source (caster) itself
  3. ...defaults True when no source recorded
  4. co_compelled_duel applies disadvantage vs non-caster, NOT vs caster
  5. _resolve_dc uses spellcasting_ability (CHA) not INT
  6. f_compelled_duel + co_compelled_duel YAML load
  7. Paladin L2 has f_compelled_duel + a_compelled_duel action
  8. hard_control scoring picks up co_compelled_duel
  9. End-to-end: cast → fail save → marked → disadvantage vs other foe
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import modifiers as _mod
from engine.core.events import EventBus
from engine.core.modifiers import query_attack_modifiers
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _make_actor(actor_id, *, side="enemy", position=(0, 0), hp=30, ac=14,
                  abilities=None, template_extra=None):
    abs_default = {a: {"score": 12, "save": 1}
                     for a in ("str", "dex", "con", "int", "wis", "cha")}
    if abilities:
        abs_default.update(abilities)
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abs_default,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    if template_extra:
        template.update(template_extra)
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abs_default)


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _compelled_duel_mod(caster_id):
    """An attack_modifier entry shaped like co_compelled_duel's effect
    after instantiation (source.source_creature_id = caster)."""
    return {
        "primitive": "attack_modifier",
        "params": {"when": "attacker_is_self AND attack_target_is_not_source",
                     "modifier": "disadvantage_for_self"},
        "source": {"type": "condition",
                     "condition_id": "co_compelled_duel",
                     "source_creature_id": caster_id},
        "owner_id": None,
    }


# ============================================================================
# Layers 1-3: attack_target_is_not_source atom
# ============================================================================

class WhenAtomTest(unittest.TestCase):

    def test_true_when_attacking_non_source(self) -> None:
        marked = _make_actor("marked", side="enemy")
        paladin = _make_actor("paladin", side="pc")
        other = _make_actor("other_pc", side="pc")
        state = _make_state([marked, paladin, other])
        mod = _compelled_duel_mod("paladin")
        # marked attacks other_pc (NOT the source paladin) → atom True
        result = _mod._eval_when(
            "attack_target_is_not_source",
            owner=marked, attacker=marked, target=other,
            state=state, mod=mod)
        self.assertTrue(result)

    def test_false_when_attacking_source(self) -> None:
        marked = _make_actor("marked", side="enemy")
        paladin = _make_actor("paladin", side="pc")
        state = _make_state([marked, paladin])
        mod = _compelled_duel_mod("paladin")
        # marked attacks the paladin (the source) → atom False
        result = _mod._eval_when(
            "attack_target_is_not_source",
            owner=marked, attacker=marked, target=paladin,
            state=state, mod=mod)
        self.assertFalse(result)

    def test_defaults_true_when_no_source(self) -> None:
        marked = _make_actor("marked")
        target = _make_actor("t", side="pc")
        state = _make_state([marked, target])
        result = _mod._eval_when(
            "attack_target_is_not_source",
            owner=marked, attacker=marked, target=target,
            state=state, mod=None)
        self.assertTrue(result)


# ============================================================================
# Layer 4: disadvantage application via query_attack_modifiers
# ============================================================================

class DisadvantageApplicationTest(unittest.TestCase):

    def test_disadvantage_attacking_other_pc(self) -> None:
        marked = _make_actor("marked", side="enemy")
        paladin = _make_actor("paladin", side="pc")
        other = _make_actor("other_pc", side="pc", position=(1, 0))
        marked.active_modifiers.append(_compelled_duel_mod("paladin"))
        state = _make_state([marked, paladin, other])
        result = query_attack_modifiers(marked, other, state)
        self.assertEqual(result.net_advantage(), "disadvantage")

    def test_no_disadvantage_attacking_the_caster(self) -> None:
        marked = _make_actor("marked", side="enemy")
        paladin = _make_actor("paladin", side="pc")
        marked.active_modifiers.append(_compelled_duel_mod("paladin"))
        state = _make_state([marked, paladin])
        result = query_attack_modifiers(marked, paladin, state)
        # Attacking the Paladin who dueled them: no disadvantage (the
        # duel "works as intended" — they fight the Paladin freely).
        self.assertEqual(result.net_advantage(), "normal")


# ============================================================================
# Layer 5: spell save DC uses CHA
# ============================================================================

class SaveDcAbilityTest(unittest.TestCase):

    def test_dc_uses_spellcasting_ability_cha(self) -> None:
        from engine.primitives import _resolve_dc
        # Paladin: CHA 18 (+4), INT 8 (-1), PB 3. CHA-based DC = 8+4+3
        # = 15. If it wrongly used INT it'd be 8-1+3 = 10.
        paladin = _make_actor(
            "paladin", side="pc",
            abilities={"cha": {"score": 18}, "int": {"score": 8}},
            template_extra={
                "spellcasting_ability": "charisma",
                "cr": {"proficiency_bonus": 3}})
        target = _make_actor("foe", side="enemy")
        state = _make_state([paladin, target])
        state.current_attack = {"actor": paladin, "target": target}
        dc = _resolve_dc({"dc_source": "caster_spell_save_dc"}, state)
        self.assertEqual(dc, 15)

    def test_dc_falls_back_to_int_without_stamp(self) -> None:
        from engine.primitives import _resolve_dc
        # Legacy fixture with no spellcasting_ability → INT default.
        wiz = _make_actor(
            "wiz", side="pc",
            abilities={"int": {"score": 14}},
            template_extra={"cr": {"proficiency_bonus": 3}})
        target = _make_actor("foe", side="enemy")
        state = _make_state([wiz, target])
        state.current_attack = {"actor": wiz, "target": target}
        dc = _resolve_dc({"dc_source": "caster_spell_save_dc"}, state)
        self.assertEqual(dc, 13)   # 8 + 2 (INT +2) + 3 (PB)


# ============================================================================
# Layers 6+7+8: content + schema integration
# ============================================================================

class ContentIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_yaml_load(self) -> None:
        feat = self.registry.get("feature", "f_compelled_duel")
        self.assertEqual(feat["granted_by"]["class"], "c_paladin")
        tmpl = feat["action_template"]
        self.assertEqual(tmpl["type"], "hard_control")
        self.assertTrue(tmpl["concentration"])
        self.assertEqual(tmpl["slot"], "bonus_action")
        cond = self.registry.get("condition", "co_compelled_duel")
        self.assertEqual(cond["scope"], "source_referencing")

    def test_paladin_l2_has_compelled_duel(self) -> None:
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 10, "cha": 16},
            "weapons": [],
        }
        template = build_pc_template(pc_spec, self.registry)
        self.assertIn("f_compelled_duel",
                        template.get("features_known", []))
        action_ids = {a.get("id") for a in template.get("actions", [])}
        self.assertIn("a_compelled_duel", action_ids)
        # PR #104: spellcasting_ability stamped from class block
        self.assertEqual(template.get("spellcasting_ability"),
                            "charisma")

    def test_hard_control_scoring_nonzero(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_hard_control
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 10, "cha": 16},
            "weapons": [],
        }
        template = build_pc_template(pc_spec, self.registry)
        paladin = Actor(id="pal", name="pal", template=template, side="pc",
                          hp_current=40, hp_max=40, ac=18, position=(0, 0),
                          abilities=template["abilities"])
        goblin = _make_actor("goblin", side="enemy", position=(1, 0),
                               template_extra={"actions": [{
                                   "id": "a", "type": "weapon_attack",
                                   "pipeline": [
                                       {"primitive": "attack_roll",
                                         "params": {"kind": "melee",
                                                      "bonus": 4}},
                                       {"primitive": "damage",
                                         "params": {"dice": "1d6",
                                                      "modifier": 2}}]}]})
        state = _make_state([paladin, goblin])
        cd = next(a for a in template["actions"]
                    if a.get("id") == "a_compelled_duel")
        score = defensive_ehp_hard_control(paladin, goblin, cd, state)
        self.assertGreater(score, 0)


# ============================================================================
# Layer 9: end-to-end
# ============================================================================

class EndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_cast_then_disadvantage(self) -> None:
        from engine.core import pipeline
        from engine.pc_schema import build_pc_template
        from engine.primitives import PrimitiveRegistry
        pc_spec = {
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 10, "cha": 20},
            "weapons": [],
        }
        template = build_pc_template(pc_spec, self.registry)
        paladin = Actor(id="pal", name="pal", template=template, side="pc",
                          hp_current=40, hp_max=40, ac=18, position=(0, 0),
                          abilities=template["abilities"],
                          spell_slots=dict(template.get("spell_slots") or {}),
                          spell_slots_max=dict(template.get("spell_slots") or {}))
        # Low-WIS goblin so it fails the save (CHA-20 Paladin DC = 16)
        goblin = _make_actor("goblin", side="enemy", position=(1, 0),
                               abilities={"wis": {"score": 6, "save": -2}})
        other_pc = _make_actor("ally", side="pc", position=(1, 0))
        state = _make_state([paladin, goblin, other_pc])
        state.content_registry = self.registry
        cd = next(a for a in template["actions"]
                    if a.get("id") == "a_compelled_duel")
        chosen = {"kind": "hard_control", "action": cd,
                    "target": goblin, "actor": paladin}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Goblin should be marked (co_compelled_duel applied on fail)
        marked = any(c.get("condition_id") == "co_compelled_duel"
                       for c in goblin.applied_conditions)
        self.assertTrue(marked)
        # Goblin attacking the OTHER pc → disadvantage
        result = query_attack_modifiers(goblin, other_pc, state)
        self.assertEqual(result.net_advantage(), "disadvantage")


if __name__ == "__main__":
    unittest.main()
