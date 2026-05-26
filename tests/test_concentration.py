"""Concentration v1 tests — single-slot, drop-on-new-cast,
CON-save-on-damage, drop-on-caster-death.

Layers:
  1. apply_concentration / end_concentration (pure-data slot mgmt)
  2. CON save mechanics (DC math, pass keeps, fail drops)
  3. Pipeline integration: action with `concentration: true` marks
     caster's slot at execution
  4. Damage hook: damaged caster rolls + may drop
  5. Death hook: dying caster's concentration ends, modifiers removed
     from allies
  6. New-cast-replaces: casting a 2nd concentration spell drops the
     1st automatically

Run via:
    python -m unittest tests.test_concentration
"""
from __future__ import annotations

import random
import unittest

from engine.core.concentration import (
    apply_concentration, end_concentration, attempt_concentration_save,
)
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc",
                hp: int = 30, ac: int = 14,
                position: tuple[int, int] = (0, 0),
                con_save: int = 1,
                template_extras: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 14, "save": 2},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 12, "save": con_save},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": []}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  position=position, abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _bless_action() -> dict:
    return {"id": "a_bless", "name": "Bless",
            "type": "offensive_buff", "concentration": True}


def _hold_person_action() -> dict:
    return {"id": "a_hold_person", "name": "Hold Person",
            "type": "hard_control", "concentration": True}


def _attach_bless_modifier(caster: Actor, ally: Actor,
                            state: CombatState) -> None:
    """Manually attach a Bless-style modifier to ally tagged with the
    concentration source (caster_id + action_id)."""
    ally.active_modifiers.append({
        "primitive": "attack_modifier",
        "params": {"target": "ally", "modifier": "attack_bonus", "value": 2},
        "lifetime": "until_short_rest",
        "source": {"type": "action_buff",
                    "action_id": "a_bless",
                    "caster_id": caster.id},
        "applied_at_round": state.round,
        "owner_id": ally.id,
    })


# ============================================================================
# Slot management
# ============================================================================

class ApplyConcentrationTest(unittest.TestCase):

    def test_apply_sets_slot(self) -> None:
        caster = _make_actor("c")
        state = _state_with([caster])
        self.assertIsNone(caster.concentration_on)
        apply_concentration(caster, _bless_action(), state)
        self.assertIsNotNone(caster.concentration_on)
        self.assertEqual(caster.concentration_on["action_id"], "a_bless")
        self.assertEqual(caster.concentration_on["caster_id"], "c")

    def test_apply_logs_concentration_started(self) -> None:
        caster = _make_actor("c")
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        events = [e["event"] for e in state.event_log]
        self.assertIn("concentration_started", events)


class EndConcentrationTest(unittest.TestCase):

    def test_end_clears_slot_and_logs(self) -> None:
        caster = _make_actor("c")
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        state.event_log.clear()
        removed = end_concentration(caster, state, reason="test")
        self.assertIsNone(caster.concentration_on)
        events = [e for e in state.event_log
                   if e["event"] == "concentration_ended"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reason"], "test")
        self.assertEqual(events[0]["removed_count"], removed)

    def test_end_removes_modifiers_from_all_allies(self) -> None:
        caster = _make_actor("c")
        ally1 = _make_actor("ally1")
        ally2 = _make_actor("ally2")
        state = _state_with([caster, ally1, ally2])
        apply_concentration(caster, _bless_action(), state)
        _attach_bless_modifier(caster, ally1, state)
        _attach_bless_modifier(caster, ally2, state)

        self.assertEqual(len(ally1.active_modifiers), 1)
        self.assertEqual(len(ally2.active_modifiers), 1)

        removed = end_concentration(caster, state, reason="test")
        self.assertEqual(removed, 2)
        self.assertEqual(ally1.active_modifiers, [])
        self.assertEqual(ally2.active_modifiers, [])

    def test_end_when_not_concentrating_is_noop(self) -> None:
        caster = _make_actor("c")
        state = _state_with([caster])
        removed = end_concentration(caster, state)
        self.assertEqual(removed, 0)
        self.assertEqual(state.event_log, [])

    def test_end_leaves_unrelated_modifiers_alone(self) -> None:
        """Modifiers from a different caster or action shouldn't be
        cleaned up by ending this caster's concentration."""
        caster = _make_actor("c")
        other = _make_actor("other", side="pc")
        ally = _make_actor("ally")
        state = _state_with([caster, other, ally])
        apply_concentration(caster, _bless_action(), state)

        # Bless from caster
        _attach_bless_modifier(caster, ally, state)
        # An unrelated modifier from a different caster
        ally.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"value": 1},
            "lifetime": "until_short_rest",
            "source": {"action_id": "a_haste", "caster_id": "other"},
            "applied_at_round": 1, "owner_id": "ally",
        })
        self.assertEqual(len(ally.active_modifiers), 2)

        end_concentration(caster, state, reason="test")
        # The Bless modifier is gone; the Haste modifier from `other`
        # remains
        self.assertEqual(len(ally.active_modifiers), 1)
        self.assertEqual(
            ally.active_modifiers[0]["source"]["caster_id"], "other")


class NewCastReplacesTest(unittest.TestCase):

    def test_apply_drops_prior_concentration(self) -> None:
        caster = _make_actor("c")
        ally = _make_actor("ally")
        state = _state_with([caster, ally])

        apply_concentration(caster, _bless_action(), state)
        _attach_bless_modifier(caster, ally, state)
        self.assertEqual(len(ally.active_modifiers), 1)

        # Cast a new concentration spell (Hold Person) — should drop Bless
        apply_concentration(caster, _hold_person_action(), state)

        # Bless modifier removed
        self.assertEqual(ally.active_modifiers, [])
        # Caster's slot now points to Hold Person
        self.assertEqual(
            caster.concentration_on["action_id"], "a_hold_person")
        # Two concentration_ended + concentration_started events fired
        events = [e["event"] for e in state.event_log]
        self.assertIn("concentration_ended", events)
        self.assertGreaterEqual(events.count("concentration_started"), 2)
        ended = [e for e in state.event_log
                  if e["event"] == "concentration_ended"]
        self.assertEqual(ended[0]["reason"], "new_cast_replaced")


# ============================================================================
# CON save mechanics
# ============================================================================

class ConcentrationSaveTest(unittest.TestCase):

    def test_dc_floor_at_10(self) -> None:
        """1 damage taken → DC max(10, 1) = 10."""
        caster = _make_actor("c", con_save=20)   # auto-pass
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        state.event_log.clear()
        attempt_concentration_save(caster, damage_taken=1, state=state,
                                     rng=random.Random(0))
        save = [e for e in state.event_log
                 if e["event"] == "concentration_save"][0]
        self.assertEqual(save["dc"], 10)

    def test_dc_half_damage_above_20(self) -> None:
        """50 damage taken → DC = 25 (ceil(50/2))."""
        caster = _make_actor("c", con_save=20)
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        state.event_log.clear()
        attempt_concentration_save(caster, damage_taken=50, state=state,
                                     rng=random.Random(0))
        save = [e for e in state.event_log
                 if e["event"] == "concentration_save"][0]
        self.assertEqual(save["dc"], 25)

    def test_pass_keeps_concentration(self) -> None:
        caster = _make_actor("c", con_save=20)   # +20 = auto-pass
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        kept = attempt_concentration_save(caster, damage_taken=10,
                                            state=state, rng=random.Random(0))
        self.assertTrue(kept)
        self.assertIsNotNone(caster.concentration_on)

    def test_fail_drops_concentration(self) -> None:
        caster = _make_actor("c", con_save=-20)   # auto-fail
        ally = _make_actor("ally")
        state = _state_with([caster, ally])
        apply_concentration(caster, _bless_action(), state)
        _attach_bless_modifier(caster, ally, state)

        kept = attempt_concentration_save(caster, damage_taken=10,
                                            state=state, rng=random.Random(0))
        self.assertFalse(kept)
        self.assertIsNone(caster.concentration_on)
        # Bless modifier removed from ally
        self.assertEqual(ally.active_modifiers, [])

    def test_zero_damage_no_save(self) -> None:
        caster = _make_actor("c", con_save=1)
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        kept = attempt_concentration_save(caster, damage_taken=0,
                                            state=state, rng=random.Random(0))
        self.assertTrue(kept)
        # No save event logged
        saves = [e for e in state.event_log
                  if e["event"] == "concentration_save"]
        self.assertEqual(saves, [])

    def test_not_concentrating_returns_true(self) -> None:
        caster = _make_actor("c")
        state = _state_with([caster])
        # No concentration_on set
        self.assertTrue(attempt_concentration_save(
            caster, damage_taken=10, state=state, rng=random.Random(0)))


# ============================================================================
# Pipeline integration — concentration flag on action
# ============================================================================

class PipelineConcentrationTest(unittest.TestCase):

    def test_pipeline_marks_concentration_when_action_has_flag(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        caster = _make_actor("c", side="pc")
        ally = _make_actor("ally", side="pc")
        state = _state_with([caster, ally])

        action = {
            "id": "a_bless", "type": "offensive_buff",
            "concentration": True,
            "pipeline": [{
                "primitive": "attack_modifier",
                "params": {"target": "ally", "modifier": "attack_bonus",
                            "value": 2},
            }],
        }
        chosen = {"kind": "offensive_buff", "actor": caster,
                  "target": ally, "action": action}

        primitives = PrimitiveRegistry.with_defaults()
        bus = EventBus()
        pipeline_execute(chosen, state, bus, primitives)

        # Caster now concentrating on Bless
        self.assertIsNotNone(caster.concentration_on)
        self.assertEqual(caster.concentration_on["action_id"], "a_bless")
        # Ally has the modifier
        self.assertEqual(len(ally.active_modifiers), 1)

    def test_no_concentration_flag_no_slot_marked(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        caster = _make_actor("c", side="pc")
        ally = _make_actor("ally", side="pc")
        state = _state_with([caster, ally])

        action = {
            "id": "a_aid", "type": "offensive_buff",
            # NO concentration flag
            "pipeline": [{
                "primitive": "attack_modifier",
                "params": {"target": "ally", "modifier": "attack_bonus",
                            "value": 1},
            }],
        }
        chosen = {"kind": "offensive_buff", "actor": caster,
                  "target": ally, "action": action}

        primitives = PrimitiveRegistry.with_defaults()
        pipeline_execute(chosen, state, PrimitiveRegistry.with_defaults(),
                          primitives)

        # Modifier still attaches, but concentration_on stays None
        self.assertIsNone(caster.concentration_on)


# ============================================================================
# Damage hook + death hook
# ============================================================================

class DamageHookTest(unittest.TestCase):

    def test_damage_triggers_concentration_save_via_primitive(self) -> None:
        """The _damage primitive should auto-trigger a CON save when
        the damaged target is concentrating."""
        from engine import primitives as primitives_module
        from engine.core.events import EventBus

        primitives_module.set_rng(random.Random(1))
        caster = _make_actor("c", side="pc", hp=50, con_save=-20)
        attacker = _make_actor("a", side="enemy")
        ally = _make_actor("ally", side="pc")
        state = _state_with([caster, attacker, ally])

        apply_concentration(caster, _bless_action(), state)
        _attach_bless_modifier(caster, ally, state)
        state.event_log.clear()

        state.current_attack = {
            "actor": attacker, "target": caster,
            "action": {}, "state": "hit",
        }
        primitives_module._damage(
            {"dice": "4d6", "modifier": 0, "type": "fire"},
            state, EventBus(),
        )

        # CON save event should be logged
        save_events = [e for e in state.event_log
                        if e["event"] == "concentration_save"]
        self.assertEqual(len(save_events), 1)
        # With con_save=-20, save auto-fails → concentration drops
        self.assertIsNone(caster.concentration_on)
        self.assertEqual(ally.active_modifiers, [])


class DeathHookTest(unittest.TestCase):

    def test_caster_death_ends_concentration_and_removes_ally_modifier(
            self) -> None:
        from engine import primitives as primitives_module
        from engine.core.events import EventBus

        primitives_module.set_rng(random.Random(1))
        # Squishy caster (will die in one hit) + ally with Bless
        caster = _make_actor("c", side="pc", hp=1, con_save=10)
        attacker = _make_actor("a", side="enemy")
        ally = _make_actor("ally", side="pc")
        state = _state_with([caster, attacker, ally])

        apply_concentration(caster, _bless_action(), state)
        _attach_bless_modifier(caster, ally, state)
        state.event_log.clear()

        state.current_attack = {
            "actor": attacker, "target": caster,
            "action": {}, "state": "hit",
        }
        primitives_module._damage(
            {"dice": "10d6", "modifier": 0, "type": "fire"},
            state, EventBus(),
        )

        self.assertTrue(caster.is_dead)
        # Even if CON save SOMEHOW passed, death-cleanup must have run
        self.assertIsNone(caster.concentration_on)
        # And ally's Bless modifier is gone
        self.assertEqual(ally.active_modifiers, [])


# ============================================================================
# End-to-end via runner — Bless dropped by goblin damage
# ============================================================================

class BlessFixtureConcentrationTest(unittest.TestCase):

    def test_bless_concentration_drops_on_failed_save(self) -> None:
        """Run the bless_buff fixture; verify the cleric eventually
        drops concentration via a failed CON save and the event log
        captures the chain."""
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

        # Verify the full concentration lifecycle in the log
        started = [e for e in state.event_log
                    if e["event"] == "concentration_started"]
        save_events = [e for e in state.event_log
                        if e["event"] == "concentration_save"]
        ended = [e for e in state.event_log
                  if e["event"] == "concentration_ended"]

        self.assertGreater(len(started), 0,
                            "Cleric should have started concentration on Bless")
        self.assertGreater(len(save_events), 0,
                            "Cleric should have rolled at least one CON save")
        # At least one save should have failed (encounter is long enough)
        failed_saves = [s for s in save_events if s["outcome"] == "fail"]
        self.assertGreater(len(failed_saves), 0,
                            "Cleric should have failed at least one CON save "
                            "over a long encounter")
        # And concentration ended events should accompany those failures
        failed_endings = [e for e in ended
                            if e["reason"] == "failed_con_save"]
        self.assertGreater(len(failed_endings), 0)


if __name__ == "__main__":
    unittest.main()
