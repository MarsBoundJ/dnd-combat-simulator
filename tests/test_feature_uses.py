"""Feature-use gate + consumption tests (PR #33).

Tests the generic feature_uses infrastructure independent of any
specific feature. Second Wind end-to-end coverage lives in
`test_pc_schema_features.py` and `test_second_wind.py`.

Layers:
  1. required_feature_use detects the `feature_use` action field
  2. has_use: True iff actor.resources[key] > 0
  3. consume_use: decrements + logs + raises on empty
  4. pipeline.generate_candidates filters depleted-resource actions
  5. pipeline.execute decrements after primitive run

Run via:
    python -m unittest tests.test_feature_uses
"""
from __future__ import annotations

import unittest

from engine.core.feature_uses import (
    required_feature_use, has_use, remaining_uses, consume_use,
)
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str = "a", side: str = "pc",
                resources: dict | None = None) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities,
                  resources=resources or {})


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Unit tests
# ============================================================================

class RequiredFeatureUseTest(unittest.TestCase):

    def test_returns_key_when_present(self) -> None:
        action = {"id": "a", "feature_use": "second_wind_uses_remaining"}
        self.assertEqual(required_feature_use(action),
                          "second_wind_uses_remaining")

    def test_returns_none_when_missing(self) -> None:
        action = {"id": "a"}
        self.assertIsNone(required_feature_use(action))

    def test_returns_none_when_empty(self) -> None:
        action = {"id": "a", "feature_use": ""}
        self.assertIsNone(required_feature_use(action))


class HasUseTest(unittest.TestCase):

    def test_true_when_charges_present(self) -> None:
        actor = _make_actor(resources={"sw_uses": 2})
        self.assertTrue(has_use(actor, "sw_uses"))

    def test_false_when_zero(self) -> None:
        actor = _make_actor(resources={"sw_uses": 0})
        self.assertFalse(has_use(actor, "sw_uses"))

    def test_false_when_missing_key(self) -> None:
        actor = _make_actor(resources={})
        self.assertFalse(has_use(actor, "sw_uses"))

    def test_true_when_key_is_none(self) -> None:
        """None key means 'not gated' → always available."""
        actor = _make_actor(resources={})
        self.assertTrue(has_use(actor, None))


class ConsumeUseTest(unittest.TestCase):

    def test_decrements_and_logs(self) -> None:
        actor = _make_actor(resources={"sw_uses": 2})
        state = _state_with([actor])
        consume_use(actor, "sw_uses", state, action_id="a_second_wind")
        self.assertEqual(actor.resources["sw_uses"], 1)
        events = [e for e in state.event_log
                   if e.get("event") == "feature_use_consumed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["resource"], "sw_uses")
        self.assertEqual(events[0]["remaining"], 1)
        self.assertEqual(events[0]["action"], "a_second_wind")

    def test_raises_when_no_charges(self) -> None:
        actor = _make_actor(resources={"sw_uses": 0})
        state = _state_with([actor])
        with self.assertRaises(ValueError):
            consume_use(actor, "sw_uses", state)

    def test_raises_when_key_missing(self) -> None:
        actor = _make_actor(resources={})
        state = _state_with([actor])
        with self.assertRaises(ValueError):
            consume_use(actor, "sw_uses", state)


class RemainingUsesTest(unittest.TestCase):

    def test_returns_count(self) -> None:
        actor = _make_actor(resources={"sw_uses": 3})
        self.assertEqual(remaining_uses(actor, "sw_uses"), 3)

    def test_zero_when_missing(self) -> None:
        actor = _make_actor(resources={})
        self.assertEqual(remaining_uses(actor, "sw_uses"), 0)


# ============================================================================
# Pipeline integration — candidate filter + execution consumption
# ============================================================================

def _second_wind_action(level: int = 2) -> dict:
    """Hand-built Second Wind action (mirrors the auto-generated one)."""
    return {
        "id": "a_second_wind",
        "name": "Second Wind",
        "type": "heal",
        "slot": "bonus_action",
        "feature_use": "second_wind_uses_remaining",
        "pipeline": [
            {"primitive": "heal",
              "params": {"target": "self", "dice": "1d10",
                          "fixed": level}},
        ],
    }


class PipelineCandidateFilterTest(unittest.TestCase):

    def test_action_in_candidates_when_use_available(self) -> None:
        from engine.core.pipeline import generate_candidates
        actor = _make_actor(resources={"second_wind_uses_remaining": 1})
        actor.template["actions"] = [_second_wind_action()]
        state = _state_with([actor])
        cands = generate_candidates(actor, state, slot="bonus_action")
        sw_cands = [c for c in cands
                     if c["action"]["id"] == "a_second_wind"]
        self.assertEqual(len(sw_cands), 1)

    def test_action_filtered_out_when_use_depleted(self) -> None:
        from engine.core.pipeline import generate_candidates
        actor = _make_actor(resources={"second_wind_uses_remaining": 0})
        actor.template["actions"] = [_second_wind_action()]
        state = _state_with([actor])
        cands = generate_candidates(actor, state, slot="bonus_action")
        sw_cands = [c for c in cands
                     if c["action"]["id"] == "a_second_wind"]
        self.assertEqual(len(sw_cands), 0)

    def test_action_filtered_out_when_resource_key_missing(self) -> None:
        """No `resources` entry at all → treated as depleted."""
        from engine.core.pipeline import generate_candidates
        actor = _make_actor(resources={})
        actor.template["actions"] = [_second_wind_action()]
        state = _state_with([actor])
        cands = generate_candidates(actor, state, slot="bonus_action")
        sw_cands = [c for c in cands
                     if c["action"]["id"] == "a_second_wind"]
        self.assertEqual(len(sw_cands), 0)


class PipelineExecutionConsumptionTest(unittest.TestCase):

    def test_execution_decrements_resource(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus
        import engine.primitives as primitives_module
        import random as _random

        actor = _make_actor(resources={"second_wind_uses_remaining": 2})
        actor.hp_current = 5    # wounded so the heal has an effect
        state = _state_with([actor])
        primitives_module.set_rng(_random.Random(1))
        chosen = {"kind": "heal", "actor": actor, "target": actor,
                  "action": _second_wind_action()}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())

        # Resource decremented
        self.assertEqual(actor.resources["second_wind_uses_remaining"], 1)
        # feature_use_consumed event logged
        events = [e for e in state.event_log
                   if e.get("event") == "feature_use_consumed"]
        self.assertEqual(len(events), 1)
        # Heal actually fired (HP went up)
        self.assertGreater(actor.hp_current, 5)


if __name__ == "__main__":
    unittest.main()
