"""Counterspell tests (SRD 5.2.1 / PHB 2024 rewrite).

RAW (2024): Target caster makes a CON save vs counterspeller's
spell save DC. On fail: spell dissipates, slot NOT expended. On
success: spell goes through.

Layers:
  1. spell_cast_initiated event fires for spell-slot actions (not for
     free actions / cantrips)
  2. cast_cancelled flag → pipeline.execute skips the pipeline AND
     refunds the target's slot (SRD 5.2.1: "slot isn't expended")
  3. Counterspell condition: enemy_casting_spell_within_60_ft —
     allies don't counter allies, distance gate, self exclusion
  4. counterspell_resolve primitive: target makes CON save vs
     counterspeller's spell save DC (no level comparison)
  5. End-to-end via pipeline: wizard casts spell, opposing wizard
     counterspells (target fails CON save), spell fizzles, target's
     slot refunded, counterspeller's slot consumed
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, Encounter, CombatState
from engine.core.events import EventBus
from engine.core.reactions import _reaction_condition_satisfied


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, side="pc", hp=30, ac=14, position=(0, 0),
                int_score=10, con_score=10, con_save=0,
                actions=None, spell_slots=None,
                proficiency_bonus=2, spellcasting_ability=None):
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 10, "save": 0},
        "con": {"score": con_score, "save": con_save},
        "int": {"score": int_score, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0,
                         "proficiency_bonus": proficiency_bonus},
                "combat": {
                    "armor_class": ac,
                    "hit_points": {"average": hp, "dice": "5d10",
                                     "con_contribution": 10},
                    "speed": {"walk": 30},
                    "initiative": {"modifier": 0, "score": 10},
                },
                "actions": actions or []}
    if spellcasting_ability:
        template["spellcasting_ability"] = spellcasting_ability
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": 30}, position=position,
                  abilities=abilities,
                  spell_slots=spell_slots or {})


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _counterspell_action() -> dict:
    return {
        "id": "a_counterspell", "name": "Counterspell",
        "type": "hard_control",
        "spell_slot_level": 3,
        "slot": "reaction",
        "trigger": "spell_cast_initiated",
        "condition": "enemy_casting_spell_within_60_ft",
        "named_effect": "counterspell",
        "pipeline": [
            {"primitive": "counterspell_resolve", "params": {}},
        ],
    }


def _target_spell_action(slot_level: int = 3,
                            action_id: str = "a_hypnotic_pattern") -> dict:
    return {
        "id": action_id,
        "name": "Target Spell",
        "type": "hard_control",
        "spell_slot_level": slot_level,
        "concentration": True,
        "pipeline": [
            {"primitive": "damage",
              "params": {"dice": "1d6", "type": "force"}},
        ],
    }


# ============================================================================
# Condition: enemy_casting_spell_within_60_ft
# ============================================================================

class CounterspellConditionTest(unittest.TestCase):

    def test_enemy_caster_in_range_passes(self) -> None:
        counterspeller = _make_actor("cs", side="pc", position=(0, 0))
        enemy = _make_actor("enemy", side="enemy", position=(5, 5))
        state = _state_with([counterspeller, enemy])
        ed = {"caster": enemy, "spell_slot_level": 3, "action": {}}
        self.assertTrue(_reaction_condition_satisfied(
            "enemy_casting_spell_within_60_ft", counterspeller,
            ed, state))

    def test_ally_caster_doesnt_fire(self) -> None:
        counterspeller = _make_actor("cs", side="pc", position=(0, 0))
        ally = _make_actor("ally", side="pc", position=(5, 5))
        state = _state_with([counterspeller, ally])
        ed = {"caster": ally, "spell_slot_level": 3, "action": {}}
        self.assertFalse(_reaction_condition_satisfied(
            "enemy_casting_spell_within_60_ft", counterspeller,
            ed, state))

    def test_self_doesnt_counter_self(self) -> None:
        wizard = _make_actor("wiz", side="pc")
        state = _state_with([wizard])
        ed = {"caster": wizard, "spell_slot_level": 3, "action": {}}
        self.assertFalse(_reaction_condition_satisfied(
            "enemy_casting_spell_within_60_ft", wizard, ed, state))

    def test_out_of_range_doesnt_fire(self) -> None:
        counterspeller = _make_actor("cs", side="pc", position=(0, 0))
        enemy = _make_actor("enemy", side="enemy", position=(13, 13))
        state = _state_with([counterspeller, enemy])
        ed = {"caster": enemy, "spell_slot_level": 3, "action": {}}
        self.assertFalse(_reaction_condition_satisfied(
            "enemy_casting_spell_within_60_ft", counterspeller,
            ed, state))


# ============================================================================
# counterspell_resolve primitive — CON save mechanic
# ============================================================================

class CounterspellResolveTest(unittest.TestCase):

    def _run_resolve(self, counterspeller, target_caster,
                       target_level, seed=1):
        from engine.primitives import _counterspell_resolve
        import engine.primitives as primitives_module
        primitives_module.set_rng(random.Random(seed))
        state = _state_with([counterspeller, target_caster])
        state.cast_cancelled = False
        state.current_attack = {
            "actor": counterspeller, "target": target_caster,
            "action": _counterspell_action(),
            "reaction_event_data": {
                "caster": target_caster,
                "action": {"id": "a_spell"},
                "spell_slot_level": target_level,
            },
        }
        return _counterspell_resolve({}, state, EventBus()), state

    def test_low_con_target_gets_countered(self) -> None:
        # Counterspeller INT 18, PB 3 → DC = 8+4+3 = 15 (INT-based
        # since no spellcasting_ability stamp → falls back to CHA...
        # actually _caster_spell_save_dc falls back to CHA when unstamped).
        # Let's stamp it explicitly.
        cs = _make_actor("cs", int_score=18, proficiency_bonus=3,
                           spellcasting_ability="intelligence")
        # Target CON save +0, needs d20 ≥ 15. Seed 1 → d20 typically < 15.
        target = _make_actor("t", side="enemy", con_save=0)
        result, state = self._run_resolve(cs, target, target_level=3, seed=1)
        self.assertEqual(result["outcome"], "countered")
        self.assertTrue(state.cast_cancelled)
        ev = next(e for e in state.event_log
                    if e.get("event") == "counterspell_resolved")
        self.assertEqual(ev["dc"], 15)

    def test_high_con_target_resists(self) -> None:
        # Counterspeller with low spell DC
        cs = _make_actor("cs", proficiency_bonus=2)
        # Target CON save +10 → total ≥ 11 vs DC 10 (8+0+2). Always passes.
        target = _make_actor("t", side="enemy", con_save=10)
        result, state = self._run_resolve(cs, target, target_level=5)
        self.assertEqual(result["outcome"], "resisted")
        self.assertFalse(state.cast_cancelled)

    def test_works_regardless_of_spell_level(self) -> None:
        # 2024: no auto-cancel for low-level spells. A level-1 spell
        # still requires the target to fail the save.
        cs = _make_actor("cs", proficiency_bonus=2)
        # Target CON save +10 → always passes DC 10.
        target = _make_actor("t", side="enemy", con_save=10)
        result, state = self._run_resolve(cs, target, target_level=1)
        self.assertEqual(result["outcome"], "resisted")
        self.assertFalse(state.cast_cancelled)

    def test_event_log_records_con_save_details(self) -> None:
        cs = _make_actor("cs", int_score=16, proficiency_bonus=4,
                           spellcasting_ability="intelligence")
        target = _make_actor("t", side="enemy", con_save=2)
        result, state = self._run_resolve(cs, target, target_level=4)
        ev = next(e for e in state.event_log
                    if e.get("event") == "counterspell_resolved")
        self.assertEqual(ev["dc"], 15)  # 8 + 3(INT 16) + 4(PB)
        self.assertIn("con_save_bonus", ev)
        self.assertIn("d20", ev)
        self.assertIn("total", ev)


# ============================================================================
# Pipeline: cast_cancelled skips pipeline + refunds slot (2024 RAW)
# ============================================================================

class PipelineCancelFlowTest(unittest.TestCase):

    def test_cast_cancelled_skips_pipeline_and_refunds_slot(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        import engine.primitives as primitives_module

        wizard = _make_actor("wiz", side="pc", spell_slots={3: 1})
        counter_wiz = _make_actor("cw", side="enemy", position=(5, 0),
                                      spell_slots={3: 1},
                                      spellcasting_ability="intelligence",
                                      int_score=20, proficiency_bonus=4,
                                      actions=[_counterspell_action()])
        target_spell = _target_spell_action(slot_level=3)
        state = _state_with([wizard, counter_wiz])
        primitives_module.set_rng(random.Random(1))
        chosen = {"kind": "hard_control", "actor": wizard,
                  "target": counter_wiz, "action": target_spell}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())
        damage_events = [e for e in state.event_log
                          if e.get("event") == "damage_dealt"]
        self.assertEqual(len(damage_events), 0)
        cancel_events = [e for e in state.event_log
                          if e.get("event") == "spell_cancelled"]
        self.assertEqual(len(cancel_events), 1)
        # Target wizard's slot REFUNDED (2024 RAW)
        self.assertEqual(wizard.spell_slots[3], 1)
        # Counter-wizard's slot consumed (Counterspell itself costs a slot)
        self.assertEqual(counter_wiz.spell_slots[3], 0)


# ============================================================================
# End-to-end — wizard mirror match
# ============================================================================

class WizardMirrorMatchTest(unittest.TestCase):

    def test_counterspell_fizzles_hypnotic_pattern(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        import engine.primitives as primitives_module

        target_spell = {
            "id": "a_hypnotic_pattern",
            "name": "Hypnotic Pattern",
            "type": "aoe_attack",
            "spell_slot_level": 3,
            "concentration": True,
            "area": {"shape": "sphere", "radius_ft": 15, "range_ft": 120},
            "pipeline": [
                {"primitive": "forced_save",
                  "params": {
                      "ability": "wisdom", "dc": 15,
                      "affected": "all_creatures_in_area",
                      "on_fail": [{"primitive": "apply_condition",
                                    "params": {
                                        "condition_id": "co_incapacitated",
                                        "duration": "until_spell_ends"}}],
                  }},
            ],
        }
        wiz_a = _make_actor("wiz_a", side="pc", position=(0, 0),
                              spell_slots={3: 1},
                              actions=[target_spell])
        # Counter-wizard: INT 20, PB 4 → DC 8+5+4 = 17. Target CON +0.
        wiz_b = _make_actor("wiz_b", side="enemy", position=(10, 0),
                              int_score=20, proficiency_bonus=4,
                              spellcasting_ability="intelligence",
                              spell_slots={3: 1},
                              actions=[_counterspell_action()])
        state = _state_with([wiz_a, wiz_b])
        primitives_module.set_rng(random.Random(1))
        chosen = {"kind": "aoe_attack", "actor": wiz_a,
                  "target": wiz_a, "action": target_spell,
                  "origin_point": (5, 0)}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())
        cs_fires = [e for e in state.event_log
                     if e.get("event") == "reaction_fired"
                     and e.get("action") == "a_counterspell"]
        self.assertEqual(len(cs_fires), 1)
        cs_resolved = [e for e in state.event_log
                        if e.get("event") == "counterspell_resolved"]
        self.assertEqual(len(cs_resolved), 1)
        self.assertEqual(cs_resolved[0]["outcome"], "countered")
        cancel_events = [e for e in state.event_log
                          if e.get("event") == "spell_cancelled"]
        self.assertEqual(len(cancel_events), 1)
        forced_save = [e for e in state.event_log
                        if e.get("event") == "forced_save"]
        self.assertEqual(len(forced_save), 0)
        # Wiz A's slot REFUNDED (2024)
        self.assertEqual(wiz_a.spell_slots[3], 1)
        # Wiz B's Counterspell slot consumed
        self.assertEqual(wiz_b.spell_slots[3], 0)
        self.assertIsNone(wiz_a.concentration_on)


# ============================================================================
# Cantrips / free actions don't trigger Counterspell
# ============================================================================

class NoTriggerForCantripsTest(unittest.TestCase):

    def test_cantrip_no_slot_no_event(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        import engine.primitives as primitives_module

        wizard = _make_actor("wiz", side="pc")
        counter_wiz = _make_actor("cw", side="enemy", position=(5, 0),
                                      spell_slots={3: 1},
                                      actions=[_counterspell_action()])
        cantrip = {
            "id": "a_fire_bolt", "name": "Fire Bolt",
            "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "ranged", "bonus": 5, "range_ft": 120}},
            ],
        }
        state = _state_with([wizard, counter_wiz])
        primitives_module.set_rng(random.Random(1))
        chosen = {"kind": "weapon_attack", "actor": wizard,
                  "target": counter_wiz, "action": cantrip}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())
        cs_fires = [e for e in state.event_log
                     if e.get("event") == "reaction_fired"
                     and e.get("action") == "a_counterspell"]
        self.assertEqual(len(cs_fires), 0)


if __name__ == "__main__":
    unittest.main()
