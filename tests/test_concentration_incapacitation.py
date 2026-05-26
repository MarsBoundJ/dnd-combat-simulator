"""Incapacitation ending concentration (PR #34).

RAW (PHB 2024 p.243): "If a creature is Incapacitated, it can't
concentrate." Stunned / Paralyzed / Unconscious / Petrified all inherit
Incapacitated and thus also end concentration. Frightened / Charmed /
Poisoned / etc. do NOT.

Layers:
  1. has_incapacitating_condition: detects any of the 5 condition ids
  2. check_incapacitation_breaks_concentration: no-op when not
     concentrating, no-op when not incapacitated, ends concentration
     otherwise
  3. Modifiers from the concentration spell are removed when
     concentration ends via incapacitation (relies on existing
     end_concentration scan)
  4. Non-incapacitating conditions (Frightened, Charmed) do NOT end
     concentration
  5. Integration via _apply_condition: applying Stunned to a
     concentrating caster ends their concentration

Run via:
    python -m unittest tests.test_concentration_incapacitation
"""
from __future__ import annotations

import unittest

from engine.core.concentration import (
    apply_concentration, has_incapacitating_condition,
    check_incapacitation_breaks_concentration,
    INCAPACITATING_CONDITIONS,
)
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str = "c") -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side="pc",
                  hp_current=20, hp_max=20, ac=14,
                  position=(0, 0), abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _bless_action() -> dict:
    return {"id": "a_bless", "name": "Bless",
            "type": "offensive_buff", "concentration": True}


def _attach_bless_modifier_to_ally(caster: Actor, ally: Actor,
                                       state: CombatState) -> None:
    """Tag an attack_modifier on `ally` as sourced from `caster`'s Bless
    so that end_concentration's source-match scan removes it."""
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
# has_incapacitating_condition — detection
# ============================================================================

class HasIncapacitatingConditionTest(unittest.TestCase):

    def test_no_conditions(self) -> None:
        actor = _make_actor()
        self.assertFalse(has_incapacitating_condition(actor))

    def test_only_non_incapacitating(self) -> None:
        """Frightened / Charmed / Poisoned do NOT incapacitate per RAW."""
        actor = _make_actor()
        actor.applied_conditions.append({"condition_id": "co_frightened"})
        actor.applied_conditions.append({"condition_id": "co_charmed"})
        actor.applied_conditions.append({"condition_id": "co_poisoned"})
        self.assertFalse(has_incapacitating_condition(actor))

    def test_each_incapacitating_condition_detected(self) -> None:
        """All five condition ids should trip the check."""
        for cid in INCAPACITATING_CONDITIONS:
            with self.subTest(condition=cid):
                actor = _make_actor()
                actor.applied_conditions.append({"condition_id": cid})
                self.assertTrue(has_incapacitating_condition(actor),
                                  f"{cid} should trip incapacitation check")


# ============================================================================
# check_incapacitation_breaks_concentration — public API
# ============================================================================

class CheckIncapacitationBreaksConcentrationTest(unittest.TestCase):

    def test_noop_when_not_concentrating(self) -> None:
        actor = _make_actor()
        actor.applied_conditions.append({"condition_id": "co_stunned"})
        state = _state_with([actor])
        result = check_incapacitation_breaks_concentration(actor, state)
        self.assertFalse(result)
        # No event logged
        ended_events = [e for e in state.event_log
                         if e.get("event") == "concentration_ended"]
        self.assertEqual(len(ended_events), 0)

    def test_noop_when_not_incapacitated(self) -> None:
        actor = _make_actor()
        state = _state_with([actor])
        apply_concentration(actor, _bless_action(), state)
        # Apply a non-incapacitating condition
        actor.applied_conditions.append({"condition_id": "co_frightened"})
        result = check_incapacitation_breaks_concentration(actor, state)
        self.assertFalse(result)
        self.assertIsNotNone(actor.concentration_on)

    def test_ends_concentration_on_stunned(self) -> None:
        caster = _make_actor("caster")
        ally = _make_actor("ally")
        state = _state_with([caster, ally])
        apply_concentration(caster, _bless_action(), state)
        _attach_bless_modifier_to_ally(caster, ally, state)
        # Stun the caster
        caster.applied_conditions.append({"condition_id": "co_stunned"})
        result = check_incapacitation_breaks_concentration(caster, state)
        self.assertTrue(result)
        self.assertIsNone(caster.concentration_on)
        # Modifier on the ally was scrubbed by end_concentration
        bless_mods = [m for m in ally.active_modifiers
                       if (m.get("source") or {}).get("action_id") == "a_bless"]
        self.assertEqual(len(bless_mods), 0)
        # Event logged with correct reason
        ended = [e for e in state.event_log
                  if e.get("event") == "concentration_ended"
                  and e.get("caster") == "caster"]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0]["reason"], "incapacitated")

    def test_ends_concentration_on_raw_incapacitated(self) -> None:
        caster = _make_actor("caster")
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        caster.applied_conditions.append({"condition_id": "co_incapacitated"})
        check_incapacitation_breaks_concentration(caster, state)
        self.assertIsNone(caster.concentration_on)

    def test_ends_concentration_on_paralyzed(self) -> None:
        caster = _make_actor("caster")
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        # Hold Person applies Paralyzed which inherits Incapacitated;
        # the inheritance logic in primitives adds BOTH entries. Here
        # we simulate the post-inheritance state.
        caster.applied_conditions.append({"condition_id": "co_paralyzed"})
        caster.applied_conditions.append({"condition_id": "co_incapacitated"})
        check_incapacitation_breaks_concentration(caster, state)
        self.assertIsNone(caster.concentration_on)

    def test_ends_concentration_on_unconscious(self) -> None:
        caster = _make_actor("caster")
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        caster.applied_conditions.append({"condition_id": "co_unconscious"})
        caster.applied_conditions.append({"condition_id": "co_incapacitated"})
        caster.applied_conditions.append({"condition_id": "co_prone"})
        check_incapacitation_breaks_concentration(caster, state)
        self.assertIsNone(caster.concentration_on)

    def test_ends_concentration_on_petrified(self) -> None:
        caster = _make_actor("caster")
        state = _state_with([caster])
        apply_concentration(caster, _bless_action(), state)
        caster.applied_conditions.append({"condition_id": "co_petrified"})
        caster.applied_conditions.append({"condition_id": "co_incapacitated"})
        check_incapacitation_breaks_concentration(caster, state)
        self.assertIsNone(caster.concentration_on)


# ============================================================================
# Integration via _apply_condition — real condition application path
# ============================================================================

class ApplyConditionEndsConcentrationTest(unittest.TestCase):
    """Verifies the hook in primitives._apply_condition: when a condition
    is applied through the normal primitive path, the incapacitation
    check fires and concentration ends if appropriate."""

    def _build_registry_with_paralyzed(self):
        """Minimal condition registry — co_paralyzed inheriting
        co_incapacitated. Mirrors `schema/content/conditions/`."""
        return _MockContentRegistry({
            "co_incapacitated": {
                "id": "co_incapacitated",
                "effects": [],
            },
            "co_paralyzed": {
                "id": "co_paralyzed",
                "inherits_conditions": ["co_incapacitated"],
                "effects": [],
            },
            "co_frightened": {
                "id": "co_frightened",
                "effects": [],
            },
        })

    def test_applying_paralyzed_ends_concentration(self) -> None:
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        caster = _make_actor("caster")
        ally = _make_actor("ally")
        state = _state_with([caster, ally])
        state.content_registry = self._build_registry_with_paralyzed()
        apply_concentration(caster, _bless_action(), state)
        _attach_bless_modifier_to_ally(caster, ally, state)

        # Set up state.current_attack so apply_condition can resolve
        # actor + target (Hold Person's typical path).
        state.current_attack = {"actor": caster, "target": caster,
                                  "action": {"id": "a_hold_person"},
                                  "state": None,
                                  "had_advantage": False,
                                  "had_disadvantage": False,
                                  "area_origin": None, "area_direction": None}
        primitives = PrimitiveRegistry.with_defaults()
        primitives.invoke("apply_condition",
                            {"condition_id": "co_paralyzed"},
                            state, EventBus())

        # Concentration ended via the hook
        self.assertIsNone(caster.concentration_on)
        # Bless modifier scrubbed from ally
        bless_mods = [m for m in ally.active_modifiers
                       if (m.get("source") or {}).get("action_id") == "a_bless"]
        self.assertEqual(len(bless_mods), 0)
        # Event log shows incapacitated reason
        ended = [e for e in state.event_log
                  if e.get("event") == "concentration_ended"
                  and e.get("reason") == "incapacitated"]
        self.assertEqual(len(ended), 1)

    def test_applying_frightened_does_NOT_end_concentration(self) -> None:
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        caster = _make_actor("caster")
        state = _state_with([caster])
        state.content_registry = self._build_registry_with_paralyzed()
        apply_concentration(caster, _bless_action(), state)

        state.current_attack = {"actor": caster, "target": caster,
                                  "action": {"id": "a_fear"},
                                  "state": None,
                                  "had_advantage": False,
                                  "had_disadvantage": False,
                                  "area_origin": None, "area_direction": None}
        primitives = PrimitiveRegistry.with_defaults()
        primitives.invoke("apply_condition",
                            {"condition_id": "co_frightened"},
                            state, EventBus())

        # Concentration preserved
        self.assertIsNotNone(caster.concentration_on)


class _MockContentRegistry:
    """Stand-in for ContentRegistry that returns canned condition defs."""

    def __init__(self, conditions: dict) -> None:
        self._conditions = conditions

    def get(self, entity_type: str, entity_id: str) -> dict:
        if entity_type != "condition":
            raise KeyError(entity_type)
        if entity_id not in self._conditions:
            raise KeyError(entity_id)
        return self._conditions[entity_id]


if __name__ == "__main__":
    unittest.main()
