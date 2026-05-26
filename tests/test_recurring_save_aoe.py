"""Per-creature recurring save in AoE control spells (PR #35).

Existing single-target `recurring_save` registration (PR #21 era) only
fired for one target — `state.current_attack.target` was the lone
anchor. PR #24's AoE forced_save loop already swaps
`state.current_attack.target` per-iteration before invoking the on_fail
sub-primitives, so dropping a `recurring_save` into Hypnotic Pattern's
on_fail block automatically registers ONE entry per failed creature
with the correct per-creature target_id. This module pins that
behavior down.

Layers:
  1. Per-iteration target swap: forced_save → recurring_save registers
     one entry per failed creature, each with that creature's id
  2. Runner resolution: each held creature's turn_end rolls its own
     save (other creatures' entries are unaffected)
  3. Save success: ends the condition on THAT creature only; other
     held creatures remain held
  4. Save failure: entry persists for the next turn_end
  5. End-to-end via Hypnotic Pattern fixture path: multiple recurring
     save events land in the log, one per held ogre per round

Run via:
    python -m unittest tests.test_recurring_save_aoe
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy",
                wis_save: int = -2, position: tuple[int, int] = (0, 0),
                actions: list[dict] | None = None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 10, "save": 0},
        "con": {"score": 10, "save": 0},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 7, "save": wis_save},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=30, hp_max=30, ac=14,
                  speed={"walk": 30}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _hp_action() -> dict:
    """Hypnotic-Pattern-shape AoE: WIS save, Incapacitated on fail with
    a recurring WIS save at end of each target's turn."""
    return {
        "id": "a_hp", "name": "Hypnotic Pattern",
        "type": "aoe_attack",
        "spell_slot_level": 3,
        "concentration": True,
        "area": {"shape": "sphere", "radius_ft": 15, "range_ft": 120},
        "pipeline": [
            {"primitive": "forced_save",
              "params": {
                  "ability": "wisdom",
                  "dc": 15,
                  "affected": "all_creatures_in_area",
                  "on_fail": [
                      {"primitive": "apply_condition",
                        "params": {"condition_id": "co_incapacitated",
                                    "duration": "until_spell_ends"}},
                      {"primitive": "recurring_save",
                        "params": {"ability": "wisdom", "dc": 15,
                                    "trigger_event": "target_turn_end",
                                    "on_success": "end_spell_on_target",
                                    "condition_id": "co_incapacitated"}},
                  ],
              }},
        ],
    }


class _MockContentRegistry:
    def __init__(self, conditions: dict) -> None:
        self._conditions = conditions
    def get(self, entity_type: str, entity_id: str) -> dict:
        if entity_type != "condition":
            raise KeyError(entity_type)
        if entity_id not in self._conditions:
            raise KeyError(entity_id)
        return self._conditions[entity_id]


def _condition_registry() -> _MockContentRegistry:
    return _MockContentRegistry({
        "co_incapacitated": {"id": "co_incapacitated", "effects": []},
    })


# ============================================================================
# Per-creature recurring_save registration via forced_save's target loop
# ============================================================================

class PerCreatureRegistrationTest(unittest.TestCase):

    def test_one_recurring_save_entry_per_failed_creature(self) -> None:
        """3 creatures fail the initial save → 3 recurring_save entries,
        each with the correct target_id."""
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus
        import engine.primitives as primitives_module

        wizard = _make_actor("wizard", side="pc",
                              actions=[_hp_action()])
        # Three low-WIS ogres in a tight cluster
        ogres = [_make_actor(f"ogre_{i}", side="enemy", wis_save=-2,
                              position=(10 + i, 0))
                  for i in range(3)]
        state = _state_with([wizard] + ogres)
        state.content_registry = _condition_registry()
        # Seed the RNG so all 3 fail (low rolls)
        primitives_module.set_rng(random.Random(2))
        state.current_attack = {
            "actor": wizard, "target": ogres[0],
            "action": _hp_action(), "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": ogres[0].position,
            "area_direction": None,
        }

        primitives = PrimitiveRegistry.with_defaults()
        # Run the forced_save step from HP's pipeline
        hp_step = _hp_action()["pipeline"][0]
        primitives.invoke("forced_save", hp_step["params"],
                            state, EventBus())

        # Each failed ogre should have its OWN recurring_save entry
        failed_ids = {o.id for o in ogres
                       if any(c.get("condition_id") == "co_incapacitated"
                                for c in o.applied_conditions)}
        self.assertGreater(len(failed_ids), 0,
                            "Test setup expects at least one ogre to fail")
        entry_target_ids = {e["target_id"] for e in state.recurring_saves}
        self.assertEqual(entry_target_ids, failed_ids,
                          "recurring_save entries should be registered for "
                          "exactly the creatures that failed the initial "
                          "save (one entry per failed creature)")

    def test_passing_creature_gets_no_recurring_save(self) -> None:
        """A creature that succeeds the initial save → no entry."""
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus
        import engine.primitives as primitives_module

        wizard = _make_actor("wizard", side="pc",
                              actions=[_hp_action()])
        # One high-save ogre (auto-success via large positive save)
        winner = _make_actor("winner", side="enemy", wis_save=30,
                              position=(10, 0))
        # One low-save ogre (likely to fail)
        loser = _make_actor("loser", side="enemy", wis_save=-5,
                              position=(11, 0))
        state = _state_with([wizard, winner, loser])
        state.content_registry = _condition_registry()
        primitives_module.set_rng(random.Random(2))
        state.current_attack = {
            "actor": wizard, "target": winner,
            "action": _hp_action(), "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": winner.position, "area_direction": None,
        }
        primitives = PrimitiveRegistry.with_defaults()
        hp_step = _hp_action()["pipeline"][0]
        primitives.invoke("forced_save", hp_step["params"],
                            state, EventBus())

        target_ids = {e["target_id"] for e in state.recurring_saves}
        self.assertNotIn("winner", target_ids)


# ============================================================================
# Runner resolution — each turn_end fires only that creature's save
# ============================================================================

class RunnerResolutionTest(unittest.TestCase):

    def test_each_creatures_turn_end_resolves_only_their_save(self) -> None:
        """At ogre_a's turn_end, ONLY ogre_a's recurring save fires.
        Other ogres' entries are untouched."""
        from engine.core.runner import EncounterRunner

        wizard = _make_actor("wizard", side="pc")
        ogres = [_make_actor(f"ogre_{i}", side="enemy") for i in range(3)]
        enc = Encounter(id="t", actors=[wizard] + ogres)
        state = CombatState(encounter=enc)
        state.turn_order = [wizard.id] + [o.id for o in ogres]
        state.round = 1
        # Manually register one recurring_save per ogre
        for o in ogres:
            state.recurring_saves.append({
                "target_id": o.id,
                "source_id": "wizard",
                "ability": "wisdom",
                "dc": 15,
                "trigger_event": "target_turn_end",
                "on_success": "end_spell_on_target",
                "condition_id": "co_incapacitated",
                "applied_at_round": 1,
            })
        runner = EncounterRunner.new(enc, seed=1)
        runner._resolve_recurring_saves(ogres[0], state)
        # Exactly ONE recurring_save event for ogre_0
        events = [e for e in state.event_log
                   if e.get("event") == "recurring_save"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target"], "ogre_0")
        # Entries for ogre_1 / ogre_2 untouched
        remaining_targets = {e["target_id"] for e in state.recurring_saves}
        # ogre_0's entry was kept (save failed at DC 15 with -2 WIS save —
        # very low odds of beating). Both ogre_1 and ogre_2 still queued.
        self.assertIn("ogre_1", remaining_targets)
        self.assertIn("ogre_2", remaining_targets)

    def test_save_success_removes_condition_only_from_that_creature(self) -> None:
        """When ogre_0 makes its save, the condition lifts from ogre_0
        only — ogre_1 stays Incapacitated."""
        from engine.core.runner import EncounterRunner

        wizard = _make_actor("wizard", side="pc")
        ogre_0 = _make_actor("ogre_0", side="enemy", wis_save=20)  # auto-pass
        ogre_1 = _make_actor("ogre_1", side="enemy", wis_save=-5)  # stays
        # Both have the condition active
        for o in (ogre_0, ogre_1):
            o.applied_conditions.append({
                "condition_id": "co_incapacitated",
                "source_id": "wizard",
                "applied_at_round": 1,
            })
        enc = Encounter(id="t", actors=[wizard, ogre_0, ogre_1])
        state = CombatState(encounter=enc)
        state.turn_order = [wizard.id, ogre_0.id, ogre_1.id]
        state.round = 1
        # Both ogres have a recurring_save queued
        for o in (ogre_0, ogre_1):
            state.recurring_saves.append({
                "target_id": o.id, "source_id": "wizard",
                "ability": "wisdom", "dc": 15,
                "trigger_event": "target_turn_end",
                "on_success": "end_spell_on_target",
                "condition_id": "co_incapacitated",
                "applied_at_round": 1,
            })
        runner = EncounterRunner.new(enc, seed=1)
        runner._resolve_recurring_saves(ogre_0, state)
        # ogre_0's condition removed
        ogre_0_conds = [c.get("condition_id") for c in ogre_0.applied_conditions]
        self.assertNotIn("co_incapacitated", ogre_0_conds)
        # ogre_1's condition preserved
        ogre_1_conds = [c.get("condition_id") for c in ogre_1.applied_conditions]
        self.assertIn("co_incapacitated", ogre_1_conds)
        # ogre_0's recurring_save entry was consumed (spell ended on it),
        # ogre_1's entry still queued
        remaining_targets = {e["target_id"] for e in state.recurring_saves}
        self.assertNotIn("ogre_0", remaining_targets)
        self.assertIn("ogre_1", remaining_targets)

    def test_save_failure_keeps_entry_for_next_turn(self) -> None:
        """A failed save → entry persists, will fire again next turn_end."""
        from engine.core.runner import EncounterRunner

        ogre = _make_actor("ogre", side="enemy", wis_save=-5)
        ogre.applied_conditions.append({
            "condition_id": "co_incapacitated",
            "source_id": "wizard",
            "applied_at_round": 1,
        })
        enc = Encounter(id="t", actors=[ogre])
        state = CombatState(encounter=enc)
        state.turn_order = [ogre.id]
        state.round = 1
        state.recurring_saves.append({
            "target_id": ogre.id, "source_id": "wizard",
            "ability": "wisdom", "dc": 25,    # nearly impossible
            "trigger_event": "target_turn_end",
            "on_success": "end_spell_on_target",
            "condition_id": "co_incapacitated",
            "applied_at_round": 1,
        })
        runner = EncounterRunner.new(enc, seed=1)
        runner._resolve_recurring_saves(ogre, state)
        # Entry persists (likely failed at DC 25)
        self.assertEqual(len(state.recurring_saves), 1)
        # Condition still active
        cond_ids = [c.get("condition_id") for c in ogre.applied_conditions]
        self.assertIn("co_incapacitated", cond_ids)


# ============================================================================
# End-to-end via the actual Hypnotic Pattern fixture
# ============================================================================

class HypnoticPatternFixtureRecurringSaveTest(unittest.TestCase):
    """Loads the live `hypnotic_pattern_vs_fireball_encounter.yaml` fixture
    (post-PR #35 with `recurring_save` wired into HP's on_fail) and
    verifies recurring_save events fire at the held ogres' turn_ends."""

    def test_recurring_save_events_fire_for_held_ogres(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        from engine.cli import _build_actor
        from engine.core.runner import EncounterRunner
        from engine.core.state import Encounter
        import engine.primitives as primitives_module
        import yaml

        # Find the repo root by walking up from this test file
        here = Path(__file__).resolve()
        repo = here.parent.parent
        content_root = repo / "schema" / "content"
        fixture_path = (repo / "tests" / "fixtures"
                          / "hypnotic_pattern_vs_fireball_encounter.yaml")
        registry = load_content(content_root, validate=False)
        with open(fixture_path, "r", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)

        actors = [_build_actor(spec, registry)
                   for spec in fixture["actors"]]
        enc = Encounter(id=fixture["id"], actors=actors)
        runner = EncounterRunner.new(enc, seed=1, content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # recurring_save events should land for held ogres
        rs_events = [e for e in state.event_log
                      if e.get("event") == "recurring_save"
                      and e.get("for_condition") == "co_incapacitated"]
        self.assertGreater(len(rs_events), 0,
                            "Expected recurring_save events for held ogres "
                            "after PR #35 wired the per-creature breakout")
        # Targets should include at least one ogre id
        ogre_targets = {e.get("target") for e in rs_events
                         if e.get("target", "").startswith("ogre_")}
        self.assertGreater(len(ogre_targets), 0)


if __name__ == "__main__":
    unittest.main()
