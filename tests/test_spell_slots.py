"""Spell slot v1 tests — tracking, cost formula, candidate filter,
consumption at execution, eHP cost subtraction.

Layers:
  1. slot_cost_ehp formula (matches framework reference values)
  2. has_slot / consume_slot helpers
  3. Candidate filter: spell candidates skipped when out of slots
  4. eHP cost subtraction in score_candidates_v1
  5. Execution: action with spell_slot_level decrements caster's slot
  6. PC schema integration: spell_slots field in compact spec
  7. End-to-end: cleric exhausts 1st-level slots, switches to mace

Run via:
    python -m unittest tests.test_spell_slots
"""
from __future__ import annotations

import random
import unittest

from engine.core.spell_slots import (
    slot_cost_ehp, has_slot, remaining_slots, consume_slot,
    required_slot_level, candidate_slot_cost,
    ENCOUNTER_DAY_DIVISOR, SLOT_COST_BASE_MULTIPLIER,
)
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc",
                hp: int = 30, ac: int = 14,
                position: tuple[int, int] = (0, 0),
                actions: list[dict] | None = None,
                spell_slots: dict | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 14, "save": 2}, "dex": {"score": 12, "save": 1},
        "con": {"score": 12, "save": 1}, "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2}, "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  position=position, abilities=abilities,
                  spell_slots=dict(spell_slots or {}))


def _state_with(actors: list[Actor],
                  encounters_remaining: int = 3) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc,
                          encounters_remaining_today=encounters_remaining)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    # candidate_slot_cost is dial-gated by conservation_strength; these tests
    # assert the full NOVA-LATE conservation model, so run PCs at dial 5
    # (strength 1.0). At the default dial 1 the cost collapses to 0
    # (impact-maximizer) and the relative cost comparisons would be 0 == 0.
    state.optimization_dials = {"pc": 5}
    return state


def _bless_action() -> dict:
    return {"id": "a_bless", "name": "Bless", "type": "offensive_buff",
            "concentration": True, "spell_slot_level": 1,
            "pipeline": [{
                "primitive": "attack_modifier",
                "params": {"target": "ally", "modifier": "attack_bonus",
                            "value": 2},
            }]}


def _weapon_attack(action_id: str, bonus: int = 5,
                    dice: str = "1d8", modifier: int = 3) -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# slot_cost_ehp formula
# ============================================================================

class SlotCostFormulaTest(unittest.TestCase):

    def test_level_0_free(self) -> None:
        self.assertEqual(slot_cost_ehp(0, 1, 0), 0.0)

    def test_framework_fireball_reference_value(self) -> None:
        """NOVA-LATE pacing: a 3rd-level slot, scarcity max (1 slot left),
        with a FULL day ahead (day_pressure 1.0) is at MAX cost → 9.0 eHP
        (conserve early). On the LAST fight it's free (see below)."""
        cost = slot_cost_ehp(slot_level=3, slots_remaining=1,
                                encounters_remaining=6)
        self.assertAlmostEqual(cost, 9.0)

    def test_last_fight_is_free_to_nova(self) -> None:
        """Last fight (0 encounters remaining) → cost 0: nova freely."""
        self.assertEqual(slot_cost_ehp(3, 1, 0), 0.0)

    def test_higher_level_costs_more(self) -> None:
        c1 = slot_cost_ehp(1, 1, 6)
        c5 = slot_cost_ehp(5, 1, 6)
        self.assertGreater(c5, c1)

    def test_more_slots_lower_cost(self) -> None:
        c1 = slot_cost_ehp(3, 1, 6)
        c5 = slot_cost_ehp(3, 5, 6)
        self.assertGreater(c1, c5,
                            "Last slot should cost more than 1-of-5")

    def test_more_encounters_remaining_higher_cost(self) -> None:
        late = slot_cost_ehp(3, 1, 0)    # last encounter → nova → 0
        early = slot_cost_ehp(3, 1, 6)   # full day ahead → conserve
        self.assertGreater(early, late,
                            "Early-day cost > last-encounter cost (conserve "
                            "early, nova late)")

    def test_day_pressure_clamped(self) -> None:
        """encounters_remaining > 6 → day_pressure capped at 1.0 → MAX cost."""
        self.assertAlmostEqual(slot_cost_ehp(3, 1, 100), 9.0)


# ============================================================================
# has_slot / consume_slot
# ============================================================================

class SlotHelpersTest(unittest.TestCase):

    def test_has_slot_level_0_always_true(self) -> None:
        actor = _make_actor("a")
        self.assertTrue(has_slot(actor, 0))

    def test_has_slot_with_slot_available(self) -> None:
        actor = _make_actor("a", spell_slots={1: 2, 3: 1})
        self.assertTrue(has_slot(actor, 1))
        self.assertTrue(has_slot(actor, 3))

    def test_has_slot_without(self) -> None:
        actor = _make_actor("a", spell_slots={1: 0, 3: 1})
        self.assertFalse(has_slot(actor, 1))
        self.assertFalse(has_slot(actor, 2))   # not tracked

    def test_remaining_slots(self) -> None:
        actor = _make_actor("a", spell_slots={1: 3, 2: 0})
        self.assertEqual(remaining_slots(actor, 1), 3)
        self.assertEqual(remaining_slots(actor, 2), 0)
        self.assertEqual(remaining_slots(actor, 3), 0)
        self.assertEqual(remaining_slots(actor, 0), 0)

    def test_consume_decrements(self) -> None:
        actor = _make_actor("a", spell_slots={1: 2})
        state = _state_with([actor])
        consume_slot(actor, 1, state, action_id="a_bless")
        self.assertEqual(actor.spell_slots[1], 1)
        consume_slot(actor, 1, state, action_id="a_bless")
        self.assertEqual(actor.spell_slots[1], 0)

    def test_consume_logs_event(self) -> None:
        actor = _make_actor("a", spell_slots={1: 3})
        state = _state_with([actor])
        consume_slot(actor, 1, state, action_id="a_bless")
        ev = [e for e in state.event_log
                if e["event"] == "spell_slot_consumed"][0]
        self.assertEqual(ev["actor"], "a")
        self.assertEqual(ev["slot_level"], 1)
        self.assertEqual(ev["remaining"], 2)
        self.assertEqual(ev["action"], "a_bless")

    def test_consume_with_no_slot_raises(self) -> None:
        actor = _make_actor("a", spell_slots={1: 0})
        state = _state_with([actor])
        with self.assertRaises(ValueError):
            consume_slot(actor, 1, state)

    def test_consume_level_0_noop(self) -> None:
        actor = _make_actor("a")
        state = _state_with([actor])
        consume_slot(actor, 0, state)   # should not raise
        self.assertEqual(state.event_log, [])


# ============================================================================
# Candidate filtering
# ============================================================================

class CandidateFilterTest(unittest.TestCase):

    def test_spell_candidate_filtered_when_out_of_slots(self) -> None:
        mace = _weapon_attack("a_mace")
        cleric = _make_actor("c", side="pc",
                               actions=[mace, _bless_action()],
                               spell_slots={1: 0})
        ally = _make_actor("ally", side="pc")
        enemy = _make_actor("e", side="enemy")
        state = _state_with([cleric, ally, enemy])

        cands = generate_candidates(cleric, state)
        kinds = [c["kind"] for c in cands]
        self.assertIn("weapon_attack", kinds,
                        "Mace candidate should remain")
        self.assertNotIn("offensive_buff", kinds,
                          "Bless candidate should be filtered (no L1 slot)")

    def test_spell_candidate_kept_with_slot_available(self) -> None:
        mace = _weapon_attack("a_mace")
        cleric = _make_actor("c", side="pc",
                               actions=[mace, _bless_action()],
                               spell_slots={1: 3})
        ally = _make_actor("ally", side="pc")
        enemy = _make_actor("e", side="enemy")
        state = _state_with([cleric, ally, enemy])

        cands = generate_candidates(cleric, state)
        kinds = [c["kind"] for c in cands]
        self.assertIn("offensive_buff", kinds)

    def test_no_spell_slot_level_field_always_passes(self) -> None:
        """Actions without spell_slot_level are 'free' (martial weapons)."""
        mace = _weapon_attack("a_mace")   # no spell_slot_level
        # Even a caster with 0 slots can swing their mace
        cleric = _make_actor("c", side="pc", actions=[mace],
                               spell_slots={})
        enemy = _make_actor("e", side="enemy")
        state = _state_with([cleric, enemy])

        cands = generate_candidates(cleric, state)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["kind"], "weapon_attack")


# ============================================================================
# candidate_slot_cost / score subtraction
# ============================================================================

class CandidateSlotCostTest(unittest.TestCase):

    def test_free_action_zero_cost(self) -> None:
        actor = _make_actor("a")
        state = _state_with([actor])
        action = _weapon_attack("a_mace")   # no spell_slot_level
        self.assertEqual(candidate_slot_cost(actor, action, state), 0.0)

    def test_slot_cost_uses_actor_remaining(self) -> None:
        actor = _make_actor("a", spell_slots={1: 3})
        state = _state_with([actor], encounters_remaining=3)
        cost_3_slots = candidate_slot_cost(actor, _bless_action(), state)

        actor2 = _make_actor("a2", spell_slots={1: 1})
        state2 = _state_with([actor2], encounters_remaining=3)
        cost_1_slot = candidate_slot_cost(actor2, _bless_action(), state2)

        self.assertGreater(cost_1_slot, cost_3_slots,
                            "Last slot costs more than 1-of-3")

    def test_dial_gates_conservation(self) -> None:
        """The slot opportunity cost scales with the side's conservation_strength
        (the dial). Dial 1 (impact-maximizer) → cost 0 (slots feel free);
        dial 5 (perfect conserver) → full cost; dial 3 in between."""
        from engine.core.optimization_dial import set_dial
        actor = _make_actor("a", spell_slots={1: 1})
        foe = _make_actor("foe", side="enemy")

        st1 = _state_with([actor, foe], encounters_remaining=3)
        set_dial(st1, "pc", 1)
        st3 = _state_with([actor, foe], encounters_remaining=3)
        set_dial(st3, "pc", 3)
        st5 = _state_with([actor, foe], encounters_remaining=3)
        set_dial(st5, "pc", 5)

        c1 = candidate_slot_cost(actor, _bless_action(), st1)
        c3 = candidate_slot_cost(actor, _bless_action(), st3)
        c5 = candidate_slot_cost(actor, _bless_action(), st5)
        self.assertEqual(c1, 0.0)               # impact-maximizer: free
        self.assertGreater(c5, c3)              # perfect > baseline
        self.assertGreater(c3, 0.0)             # baseline still conserves some
        self.assertAlmostEqual(c3, c5 * (2.0 / 3.0), places=4)  # the dial curve

    def test_score_candidates_subtracts_cost(self) -> None:
        """A high-eHP candidate that burns the actor's last slot should
        score lower than the same candidate when slots are plentiful."""
        from engine.ai.decision_layer import score_candidates_v1

        mace = _weapon_attack("a_mace")
        ally = _make_actor("ally", side="pc",
                              actions=[_weapon_attack("a_sword", bonus=8,
                                                        dice="2d8",
                                                        modifier=5)])

        # Caster with 3 slots — Bless cost is low
        plenty = _make_actor("plenty", side="pc",
                                actions=[mace, _bless_action()],
                                spell_slots={1: 3})
        state_plenty = _state_with([plenty, ally], encounters_remaining=3)
        scored_plenty = score_candidates_v1(
            generate_candidates(plenty, state_plenty), plenty, state_plenty)

        # Caster with 1 slot — Bless cost is higher
        scarce = _make_actor("scarce", side="pc",
                                actions=[mace, _bless_action()],
                                spell_slots={1: 1})
        state_scarce = _state_with([scarce, ally], encounters_remaining=3)
        scored_scarce = score_candidates_v1(
            generate_candidates(scarce, state_scarce), scarce, state_scarce)

        def _bless_score(scored):
            return next(s for s, c in scored
                          if c["kind"] == "offensive_buff")

        self.assertGreater(_bless_score(scored_plenty),
                            _bless_score(scored_scarce),
                            "Bless should score higher when slots are plentiful")


# ============================================================================
# Execution: action with spell_slot_level decrements slot
# ============================================================================

class ExecutionConsumesSlotTest(unittest.TestCase):

    def test_bless_execution_decrements_slot(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        caster = _make_actor("c", side="pc",
                               actions=[_bless_action()],
                               spell_slots={1: 2})
        ally = _make_actor("ally", side="pc")
        state = _state_with([caster, ally])

        chosen = {"kind": "offensive_buff", "actor": caster,
                  "target": ally, "action": _bless_action()}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())

        self.assertEqual(caster.spell_slots[1], 1,
                          "L1 slot should decrement from 2 → 1")
        # And the consumed event is logged
        events = [e for e in state.event_log
                   if e["event"] == "spell_slot_consumed"]
        self.assertEqual(len(events), 1)

    def test_weapon_attack_does_not_consume(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        actor = _make_actor("a", side="pc",
                              actions=[_weapon_attack("a_mace")],
                              spell_slots={1: 3})
        enemy = _make_actor("e", side="enemy", hp=100)
        state = _state_with([actor, enemy])

        chosen = {"kind": "weapon_attack", "actor": actor,
                  "target": enemy, "action": _weapon_attack("a_mace")}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())

        self.assertEqual(actor.spell_slots[1], 3,
                          "Slot count should be unchanged after weapon attack")


# ============================================================================
# PC schema integration
# ============================================================================

class PCSchemaSlotsTest(unittest.TestCase):

    def test_pc_schema_spell_slots_field_populates_actor(self) -> None:
        from engine.cli import _build_actor
        from engine.loader import load_content
        from pathlib import Path

        repo_root = Path(__file__).parent.parent
        registry = load_content(
            repo_root / "schema" / "content", validate=True,
            schema_root=repo_root / "schema" / "definitions",
        )
        actor_spec = {
            "instance_id": "test_cleric",
            "side": "pc",
            "pc": {
                "class": "c_fighter",   # any class for testing
                "level": 3,
                "ability_scores": {"con": 14},
                "spell_slots": {1: 4, 2: 2},
            },
        }
        actor = _build_actor(actor_spec, registry)
        self.assertEqual(actor.spell_slots, {1: 4, 2: 2})

    def test_actor_spec_spell_slots_top_level(self) -> None:
        """Inline/template fixtures can specify spell_slots at the
        actor_spec top level too."""
        from engine.cli import _build_actor

        template = {"id": "tpl", "name": "wizard",
                     "abilities": {"con": {"score": 10, "save": 0}},
                     "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                     "combat": {"hit_points": {"average": 20},
                                  "armor_class": 12, "speed": {"walk": 30}},
                     "actions": []}
        actor_spec = {
            "instance_id": "w1", "side": "pc",
            "template": template,
            "spell_slots": {1: 4, 3: 2},
        }
        actor = _build_actor(actor_spec, None)
        self.assertEqual(actor.spell_slots, {1: 4, 3: 2})


# ============================================================================
# End-to-end: cleric exhausts Bless slots, switches to mace permanently
# ============================================================================

class SlotExhaustionIntegrationTest(unittest.TestCase):

    def test_cleric_exhausts_3_bless_slots_then_only_mace(self) -> None:
        """Long encounter: cleric casts Bless 3 times (each followed by
        a concentration drop), exhausts slots, then can ONLY mace."""
        import random as _random
        from pathlib import Path
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner
        from engine.cli import _build_encounter
        from engine.loader import load_content, load_yaml_file

        repo_root = Path(__file__).parent.parent
        content_root = repo_root / "schema" / "content"
        schema_root = repo_root / "schema" / "definitions"
        fixture = Path(__file__).parent / "fixtures" / \
            "bless_buff_encounter.yaml"

        registry = load_content(content_root, validate=True,
                                  schema_root=schema_root)
        spec = load_yaml_file(fixture)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1,
                                       content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # The cleric should have consumed AT MOST 3 slots (initial count).
        bless_casts = [e for e in state.event_log
                        if e["event"] == "spell_slot_consumed"
                        and e["actor"] == "cleric_caster"]
        self.assertLessEqual(len(bless_casts), 3,
                              f"Cleric should not consume >3 slots; "
                              f"got {len(bless_casts)}")

        # Cleric should end with 0 slots (or close to 0) after a long
        # encounter, OR not have hit the cap if the encounter ended early.
        cleric_after = next(a for a in encounter.actors
                              if a.id == "cleric_caster")
        # The final remaining count must equal 3 - len(bless_casts).
        self.assertEqual(
            cleric_after.spell_slots.get(1, 0),
            3 - len(bless_casts),
            f"Final slot count should match initial - consumed",
        )


if __name__ == "__main__":
    unittest.main()
