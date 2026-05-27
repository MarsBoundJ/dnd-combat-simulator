"""SRD races + save-source context tests (PR #75).

Layers:
  1. racial_traits module: has_racial_trait + lucky_d20
  2. Save-source context: build_save_context extracts conditions
  3. racial_save_advantage_for resolution
  4. Halfling Lucky: reroll on natural 1 in _attack_roll
  5. Halfling Lucky: reroll on natural 1 in _forced_save
  6. Halfling Brave: advantage on save vs co_frightened-applying source
  7. Halfling Brave: NO advantage on unrelated save
  8. Elf Fey Ancestry: advantage on save vs co_charmed-applying source
  9. Dwarf Dwarven Resilience: advantage on save vs co_poisoned-applying source
 10. Dwarf Dwarven Resilience: poison damage resistance (template path)
 11. Race YAML loading
 12. pc_schema: race stamps size, speed, darkvision, racial_traits, dmg_resist
 13. pc_schema: Halfling is Small, others Medium
 14. pc_schema: Human Skillful appends extra skill prof
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.racial_traits import (
    SAVE_CONDITION_TRIGGERS,
    has_racial_trait, lucky_d20,
    racial_save_advantage_for,
    build_save_context, build_save_context_for_condition,
    extract_apply_condition_ids,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.core.modifiers import query_save_modifiers
from engine.primitives import _attack_roll, _damage, _forced_save


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0),
                  racial_traits=None, size="medium"):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=30, hp_max=30, ac=14,
        speed={"walk": 30}, position=position,
        abilities=abilities, size=size,
        racial_traits=list(racial_traits or []),
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1: module helpers
# ============================================================================

class RacialTraitModuleTest(unittest.TestCase):

    def test_has_trait_true(self) -> None:
        actor = _make_actor("a", racial_traits=["t_lucky", "t_brave"])
        self.assertTrue(has_racial_trait(actor, "t_lucky"))
        self.assertTrue(has_racial_trait(actor, "t_brave"))

    def test_has_trait_false_when_missing(self) -> None:
        actor = _make_actor("a", racial_traits=["t_lucky"])
        self.assertFalse(has_racial_trait(actor, "t_brave"))

    def test_has_trait_case_insensitive(self) -> None:
        actor = _make_actor("a", racial_traits=["T_Lucky"])
        self.assertTrue(has_racial_trait(actor, "t_lucky"))

    def test_has_trait_handles_no_traits_attr(self) -> None:
        # An object without racial_traits attr (e.g., legacy test
        # actor) should return False, not raise.
        class FakeActor:
            pass
        f = FakeActor()
        self.assertFalse(has_racial_trait(f, "t_lucky"))

    def test_lucky_no_reroll_when_not_lucky(self) -> None:
        actor = _make_actor("a", racial_traits=[])
        rng = random.Random(1)
        result, rerolled = lucky_d20(rng, 1, actor)
        self.assertEqual(result, 1)
        self.assertFalse(rerolled)

    def test_lucky_no_reroll_when_not_1(self) -> None:
        actor = _make_actor("a", racial_traits=["t_lucky"])
        rng = random.Random(1)
        result, rerolled = lucky_d20(rng, 15, actor)
        self.assertEqual(result, 15)
        self.assertFalse(rerolled)

    def test_lucky_rerolls_when_lucky_and_1(self) -> None:
        actor = _make_actor("a", racial_traits=["t_lucky"])
        rng = random.Random(7)   # deterministic seed
        result, rerolled = lucky_d20(rng, 1, actor)
        self.assertNotEqual(result, 1)   # very high probability
        self.assertTrue(rerolled)
        self.assertGreaterEqual(result, 1)
        self.assertLessEqual(result, 20)


# ============================================================================
# Layer 2: save-source context
# ============================================================================

class SaveSourceContextTest(unittest.TestCase):

    def test_extract_conditions_from_on_fail(self) -> None:
        on_fail = [
            {"primitive": "damage", "params": {"dice": "2d6"}},
            {"primitive": "apply_condition",
              "params": {"condition_id": "co_frightened"}},
            {"primitive": "apply_condition",
              "params": {"condition_id": "co_charmed"}},
        ]
        conds = extract_apply_condition_ids(on_fail)
        self.assertEqual(conds, ["co_frightened", "co_charmed"])

    def test_extract_handles_empty(self) -> None:
        self.assertEqual(extract_apply_condition_ids([]), [])
        self.assertEqual(extract_apply_condition_ids(None), [])

    def test_build_save_context(self) -> None:
        params = {
            "ability": "wisdom", "dc": 13,
            "on_fail": [
                {"primitive": "apply_condition",
                  "params": {"condition_id": "co_charmed"}},
            ],
        }
        ctx = build_save_context(params)
        self.assertEqual(ctx["applied_conditions_on_fail"], ["co_charmed"])

    def test_build_save_context_for_condition(self) -> None:
        ctx = build_save_context_for_condition("co_poisoned")
        self.assertEqual(ctx["applied_conditions_on_fail"], ["co_poisoned"])


# ============================================================================
# Layer 3: racial_save_advantage_for resolution
# ============================================================================

class RacialSaveAdvantageResolutionTest(unittest.TestCase):

    def test_brave_triggers_on_frightened(self) -> None:
        actor = _make_actor("a", racial_traits=["t_brave"])
        state = _make_state([actor])
        state.current_save_context = {
            "applied_conditions_on_fail": ["co_frightened"]}
        self.assertEqual(
            racial_save_advantage_for(actor, state), "t_brave")

    def test_brave_does_not_trigger_on_charmed(self) -> None:
        actor = _make_actor("a", racial_traits=["t_brave"])
        state = _make_state([actor])
        state.current_save_context = {
            "applied_conditions_on_fail": ["co_charmed"]}
        self.assertIsNone(racial_save_advantage_for(actor, state))

    def test_fey_ancestry_triggers_on_charmed(self) -> None:
        actor = _make_actor("a", racial_traits=["t_fey_ancestry"])
        state = _make_state([actor])
        state.current_save_context = {
            "applied_conditions_on_fail": ["co_charmed"]}
        self.assertEqual(
            racial_save_advantage_for(actor, state), "t_fey_ancestry")

    def test_dwarven_resilience_triggers_on_poisoned(self) -> None:
        actor = _make_actor("a", racial_traits=["t_dwarven_resilience"])
        state = _make_state([actor])
        state.current_save_context = {
            "applied_conditions_on_fail": ["co_poisoned"]}
        self.assertEqual(
            racial_save_advantage_for(actor, state),
            "t_dwarven_resilience")

    def test_no_context_returns_none(self) -> None:
        actor = _make_actor("a", racial_traits=["t_brave"])
        state = _make_state([actor])
        # No context set
        self.assertIsNone(racial_save_advantage_for(actor, state))

    def test_query_save_modifiers_grants_advantage_via_racial_trait(self) -> None:
        actor = _make_actor("a", racial_traits=["t_brave"])
        state = _make_state([actor])
        state.current_save_context = {
            "applied_conditions_on_fail": ["co_frightened"]}
        result = query_save_modifiers(actor, "wisdom", state)
        self.assertTrue(result.has_advantage)


# ============================================================================
# Layer 4: Lucky in _attack_roll
# ============================================================================

class LuckyAttackRollTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(42))

    def test_lucky_halfling_rerolls_nat_1_attack(self) -> None:
        # Run many attacks with a Halfling rolling. With Lucky, the
        # natural-1 results should be very rare (essentially 1/400
        # = both rolls land on 1).
        attacker = _make_actor("halfling", racial_traits=["t_lucky"])
        attacker.abilities = {"str": {"score": 16, "save": 3}, **{
            k: {"score": 10, "save": 0}
            for k in ("dex", "con", "int", "wis", "cha")}}
        target = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _make_state([attacker, target])
        action = {"id": "a_dagger", "type": "weapon_attack",
                    "pipeline": [{"primitive": "attack_roll",
                                    "params": {"kind": "melee",
                                                 "bonus": 5,
                                                 "reach_ft": 5}}]}
        nat_1_count = 0
        n_trials = 200
        for i in range(n_trials):
            primitives_module.set_rng(random.Random(100 + i))
            state.current_attack = {
                "actor": attacker, "target": target, "action": action,
                "state": None, "had_advantage": False,
                "had_disadvantage": False,
            }
            _attack_roll({"kind": "melee", "bonus": 5, "reach_ft": 5},
                          state, EventBus())
            # Find the latest attack_roll event
            attack_events = [e for e in state.event_log
                              if e.get("event") == "attack_roll"]
            d20 = attack_events[-1]["d20"]
            if d20 == 1:
                nat_1_count += 1
            state.event_log.clear()
        # With Lucky, nat 1 prob is (1/20) × (1/20) = 1/400. In 200
        # trials, expected ~0.5. Allow up to 3.
        self.assertLess(nat_1_count, 4,
                         f"Too many nat 1s with Lucky: {nat_1_count}/{n_trials}")

    def test_non_lucky_actor_keeps_nat_1(self) -> None:
        # Without Lucky, nat 1s land at ~1/20 = 10 per 200 trials.
        attacker = _make_actor("human", racial_traits=[])
        attacker.abilities = {"str": {"score": 16, "save": 3}, **{
            k: {"score": 10, "save": 0}
            for k in ("dex", "con", "int", "wis", "cha")}}
        target = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _make_state([attacker, target])
        action = {"id": "a_dagger", "type": "weapon_attack",
                    "pipeline": [{"primitive": "attack_roll",
                                    "params": {"kind": "melee",
                                                 "bonus": 5,
                                                 "reach_ft": 5}}]}
        nat_1_count = 0
        n_trials = 200
        for i in range(n_trials):
            primitives_module.set_rng(random.Random(100 + i))
            state.current_attack = {
                "actor": attacker, "target": target, "action": action,
                "state": None, "had_advantage": False,
                "had_disadvantage": False,
            }
            _attack_roll({"kind": "melee", "bonus": 5, "reach_ft": 5},
                          state, EventBus())
            attack_events = [e for e in state.event_log
                              if e.get("event") == "attack_roll"]
            d20 = attack_events[-1]["d20"]
            if d20 == 1:
                nat_1_count += 1
            state.event_log.clear()
        # ~10 nat 1s expected; allow 4-20
        self.assertGreaterEqual(nat_1_count, 4)


# ============================================================================
# Layer 5: Lucky in _forced_save
# ============================================================================

class LuckyForcedSaveTest(unittest.TestCase):

    def test_lucky_halfling_rerolls_nat_1_on_save(self) -> None:
        # Use a save with no on_fail effects (just observe the d20)
        target = _make_actor("halfling", racial_traits=["t_lucky"])
        attacker = _make_actor("attacker", side="enemy")
        state = _make_state([attacker, target])
        nat_1_count = 0
        n_trials = 200
        for i in range(n_trials):
            primitives_module.set_rng(random.Random(200 + i))
            state.current_attack = {
                "actor": attacker, "target": target,
                "action": {"id": "a_test"},
                "state": None,
                "had_advantage": False, "had_disadvantage": False,
            }
            state.event_log.clear()
            _forced_save({"ability": "wisdom", "dc": 15,
                            "affected": "current_target",
                            "on_fail": [], "on_success": []},
                          state, EventBus())
            saves = [e for e in state.event_log
                      if e.get("event") == "forced_save"]
            d20 = saves[-1]["d20"]
            if d20 == 1:
                nat_1_count += 1
        # Same statistical expectation as attack rolls: < 4
        self.assertLess(nat_1_count, 4,
                         f"Too many nat 1s with Lucky save: "
                         f"{nat_1_count}/{n_trials}")


# ============================================================================
# Layer 6+7: Brave save advantage via forced_save
# ============================================================================

class BraveSaveAdvantageTest(unittest.TestCase):

    def test_brave_gets_advantage_on_frightened_save(self) -> None:
        # The cleanest test: query_save_modifiers directly with the
        # context set, verify has_advantage is True. The mechanical
        # effect chained through _forced_save is harder to test
        # statistically; the query path is the load-bearing piece.
        target = _make_actor("halfling", racial_traits=["t_brave"])
        state = _make_state([target])
        # Simulate _forced_save setting the context for an attack
        # that would apply Frightened on fail
        state.current_save_context = build_save_context({
            "ability": "wisdom", "dc": 13,
            "on_fail": [{"primitive": "apply_condition",
                           "params": {"condition_id": "co_frightened"}}],
        })
        result = query_save_modifiers(target, "wisdom", state)
        self.assertTrue(result.has_advantage)

    def test_brave_no_advantage_on_unrelated_save(self) -> None:
        target = _make_actor("halfling", racial_traits=["t_brave"])
        state = _make_state([target])
        # Save that would apply paralyzed (not frightened) — Brave
        # should NOT fire.
        state.current_save_context = build_save_context({
            "ability": "constitution", "dc": 13,
            "on_fail": [{"primitive": "apply_condition",
                           "params": {"condition_id": "co_paralyzed"}}],
        })
        result = query_save_modifiers(target, "constitution", state)
        self.assertFalse(result.has_advantage)


# ============================================================================
# Layer 8+9: Fey Ancestry / Dwarven Resilience save advantage
# ============================================================================

class FeyAncestryAndResilienceTest(unittest.TestCase):

    def test_fey_ancestry_advantage_on_charm_save(self) -> None:
        target = _make_actor("elf", racial_traits=["t_fey_ancestry"])
        state = _make_state([target])
        state.current_save_context = build_save_context({
            "ability": "wisdom", "dc": 13,
            "on_fail": [{"primitive": "apply_condition",
                           "params": {"condition_id": "co_charmed"}}],
        })
        result = query_save_modifiers(target, "wisdom", state)
        self.assertTrue(result.has_advantage)

    def test_dwarven_resilience_advantage_on_poison_save(self) -> None:
        target = _make_actor("dwarf",
                                racial_traits=["t_dwarven_resilience"])
        state = _make_state([target])
        state.current_save_context = build_save_context({
            "ability": "constitution", "dc": 13,
            "on_fail": [{"primitive": "apply_condition",
                           "params": {"condition_id": "co_poisoned"}}],
        })
        result = query_save_modifiers(target, "constitution", state)
        self.assertTrue(result.has_advantage)


# ============================================================================
# Layer 10: Dwarf poison damage resistance (template path)
# ============================================================================

class DwarfPoisonResistanceTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(13))

    def test_poison_damage_halved_via_template_resistance(self) -> None:
        target = _make_actor("dwarf",
                                racial_traits=["t_dwarven_resilience"])
        # Bake poison resistance onto the template (PR #75: pc_schema
        # stamps this from the race YAML).
        target.template["damage_resistances"] = ["poison"]
        attacker = _make_actor("orc", side="enemy")
        state = _make_state([attacker, target])
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": {"id": "a_poison", "pipeline": []},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = target.hp_current
        _damage({"dice": "4d4", "modifier": 4, "type": "poison"},
                state, EventBus())
        hp_lost = hp_before - target.hp_current
        # 4d4 + 4 max = 20; halved → 10. Min is (4 + 4) // 2 = 4.
        self.assertLessEqual(hp_lost, 10)
        self.assertGreaterEqual(hp_lost, 4)


# ============================================================================
# Layer 11: race YAML loading
# ============================================================================

class RaceYamlLoadingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from engine.loader import load_content
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_all_four_srd_races_load(self) -> None:
        for race_id in ("r_dwarf", "r_elf", "r_halfling", "r_human"):
            race = self.registry.get("race", race_id)
            self.assertIsNotNone(race)
            self.assertEqual(race["id"], race_id)

    def test_dwarf_has_darkvision_60_and_poison_resistance(self) -> None:
        dwarf = self.registry.get("race", "r_dwarf")
        self.assertEqual(dwarf["darkvision_range_ft"], 60)
        self.assertIn("poison", dwarf["damage_resistances"])
        self.assertIn("t_dwarven_resilience", dwarf["racial_traits"])

    def test_halfling_is_small_with_lucky_and_brave(self) -> None:
        h = self.registry.get("race", "r_halfling")
        self.assertEqual(h["size"], "small")
        self.assertEqual(h["darkvision_range_ft"], 0)
        traits = set(h["racial_traits"])
        self.assertIn("t_lucky", traits)
        self.assertIn("t_brave", traits)

    def test_human_has_extra_skill_slot(self) -> None:
        h = self.registry.get("race", "r_human")
        self.assertEqual(h["extra_skill_proficiency_slots"], 1)


# ============================================================================
# Layer 12+13+14: pc_schema integration
# ============================================================================

class PcSchemaRaceIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from engine.loader import load_content
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def _build(self, race_id, *, class_id="c_fighter", level=1,
                  extra_skill=None):
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": f"pc_{race_id}",
            "class": class_id,
            "level": level,
            "race": race_id,
            "ability_scores": {"str": 14, "dex": 12, "con": 14,
                                 "int": 10, "wis": 12, "cha": 10},
            "weapons": [{"id": "longsword", "name": "Longsword",
                          "damage_dice": "1d8",
                          "damage_type": "slashing",
                          "attack_ability": "str"}],
        }
        if extra_skill:
            pc_spec["extra_skill"] = extra_skill
        return build_pc_template(pc_spec, self.registry)

    def test_halfling_pc_is_small(self) -> None:
        template = self._build("r_halfling")
        self.assertEqual(template["size"], "small")

    def test_dwarf_elf_human_are_medium(self) -> None:
        for race_id in ("r_dwarf", "r_elf", "r_human"):
            template = self._build(race_id)
            self.assertEqual(template["size"], "medium",
                              f"{race_id} should be medium")

    def test_dwarf_pc_has_poison_resistance(self) -> None:
        template = self._build("r_dwarf")
        self.assertIn("poison", template["damage_resistances"])

    def test_elf_pc_has_darkvision_60(self) -> None:
        template = self._build("r_elf")
        self.assertEqual(template["darkvision_range_ft"], 60)

    def test_halfling_pc_has_no_darkvision(self) -> None:
        template = self._build("r_halfling")
        self.assertEqual(template["darkvision_range_ft"], 0)

    def test_halfling_pc_has_lucky_and_brave_traits(self) -> None:
        template = self._build("r_halfling")
        traits = set(template["racial_traits"])
        self.assertIn("t_lucky", traits)
        self.assertIn("t_brave", traits)

    def test_human_pc_skillful_appends_skill_prof(self) -> None:
        template = self._build("r_human", extra_skill="persuasion")
        self.assertIn("persuasion", template["skill_proficiencies"])

    def test_human_pc_without_extra_skill_works(self) -> None:
        # Should NOT raise — extra_skill is optional even with the slot
        template = self._build("r_human")
        self.assertEqual(template["racial_traits"], [])

    def test_no_race_pc_defaults_medium_no_traits(self) -> None:
        # PC without race: size=medium default, no racial traits
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": "pc_classic",
            "class": "c_fighter",
            "level": 1,
            "ability_scores": {"str": 14, "dex": 12, "con": 14,
                                 "int": 10, "wis": 12, "cha": 10},
            "weapons": [{"id": "longsword", "name": "Longsword",
                          "damage_dice": "1d8",
                          "damage_type": "slashing",
                          "attack_ability": "str"}],
        }
        template = build_pc_template(pc_spec, self.registry)
        self.assertEqual(template["size"], "medium")
        self.assertEqual(template["racial_traits"], [])

    def test_invalid_race_raises(self) -> None:
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "class": "c_fighter", "level": 1, "race": "r_nonexistent",
            "ability_scores": {"str": 14, "dex": 12, "con": 14,
                                 "int": 10, "wis": 12, "cha": 10},
            "weapons": [{"id": "longsword", "name": "Longsword",
                          "damage_dice": "1d8",
                          "damage_type": "slashing",
                          "attack_ability": "str"}],
        }
        with self.assertRaises(ValueError):
            build_pc_template(pc_spec, self.registry)


if __name__ == "__main__":
    unittest.main()
