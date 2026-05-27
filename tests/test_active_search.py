"""Active Search action tests (PR #55).

Layers:
  1. Built-in Search emission gates:
     - No hidden enemies → Search NOT emitted
     - Hidden enemy with stealth_total <= passive Perception → NOT emitted
       (PR #51 auto-spot already handles it)
     - Hidden enemy with stealth_total > passive Perception → Search emitted
     - Multiple enemies: emit if ANY meets the gate
     - Explicit search action in template → built-in suppressed
     - Bonus slot → no built-ins
  2. _execute_search:
     - No candidate enemies → logs no_targets, no scrub
     - Failed Perception check → no scrub, search_check logged
     - Successful check → scrubs Hide-source co_invisible, fires
       creature_revealed event
     - Perception proficiency adds PB
     - Only scrubs Hide-source — spell-source Invisible untouched
     - Multiple hidden enemies all rolled against; each independent

Run via:
    python -m unittest tests.test_active_search
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.basic_actions import (
    BUILT_IN_SEARCH, built_in_actions_for,
    _has_unspotted_hidden_enemy,
)
from engine.core.events import EventBus
from engine.core.pipeline import execute as pipeline_execute
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import PrimitiveRegistry


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  passive_perception=10,
                  skill_proficiencies=None,
                  applied_conditions=None,
                  abilities=None) -> Actor:
    abilities = abilities or {k: {"score": 12 if k == "wis" else 10,
                                       "save": 0}
                                 for k in ("str", "dex", "con",
                                            "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 3},
                 # Give every test actor a basic 5-ft melee attack so
                 # `_actor_should_move_instead` doesn't kill the
                 # built-in Search gate (it requires at least one
                 # in-reach attack option to consider Search).
                 "actions": [{
                     "id": "a_punch", "name": "Punch",
                     "type": "weapon_attack",
                     "pipeline": [
                         {"primitive": "attack_roll",
                          "params": {"kind": "melee", "bonus": 0,
                                       "reach_ft": 5}}],
                 }]}
    if skill_proficiencies:
        template["skill_proficiencies"] = list(skill_proficiencies)
    actor = Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=20, hp_max=20, ac=14,
                   speed={"walk": 30}, position=position,
                   abilities=abilities,
                   passive_perception=passive_perception)
    if applied_conditions:
        actor.applied_conditions = list(applied_conditions)
    return actor


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _hide_condition(stealth_total=20):
    return {"condition_id": "co_invisible",
             "source_action_id": "a_hide",
             "stealth_total": stealth_total}


def _spell_invisible():
    return {"condition_id": "co_invisible",
             "source_action_id": "a_invisibility_spell"}


def _search_action():
    return {"id": "_builtin_search", "name": "Search",
             "type": "search", "pipeline": []}


# ============================================================================
# Layer 1: _has_unspotted_hidden_enemy + built-in emission
# ============================================================================

class GateHelperTest(unittest.TestCase):

    def test_no_hidden_enemy_false(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0))
        state = _state_with([observer, enemy])
        self.assertFalse(_has_unspotted_hidden_enemy(observer, state))

    def test_hidden_enemy_above_passive_true(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=15)])
        state = _state_with([observer, enemy])
        self.assertTrue(_has_unspotted_hidden_enemy(observer, state))

    def test_hidden_enemy_at_or_below_passive_false(self) -> None:
        # PR #51's auto-spot already handles passive >= stealth_total.
        observer = _make_actor("obs", passive_perception=20)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=15)])
        state = _state_with([observer, enemy])
        self.assertFalse(_has_unspotted_hidden_enemy(observer, state))

    def test_spell_invisible_does_NOT_qualify(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_spell_invisible()])
        state = _state_with([observer, enemy])
        self.assertFalse(_has_unspotted_hidden_enemy(observer, state))

    def test_dead_enemy_skipped(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=20)])
        enemy.is_dead = True
        state = _state_with([observer, enemy])
        self.assertFalse(_has_unspotted_hidden_enemy(observer, state))

    def test_ally_with_hide_does_NOT_qualify(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        ally = _make_actor("ally", side="pc", position=(2, 0),
                             applied_conditions=[_hide_condition(stealth_total=20)])
        state = _state_with([observer, ally])
        self.assertFalse(_has_unspotted_hidden_enemy(observer, state))

    def test_multiple_enemies_emits_if_ANY(self) -> None:
        observer = _make_actor("obs", passive_perception=15)
        e1 = _make_actor("e1", side="enemy", position=(2, 0),
                            applied_conditions=[_hide_condition(stealth_total=10)])
        # PP 15 >= 10, auto-spotted
        e2 = _make_actor("e2", side="enemy", position=(2, 1),
                            applied_conditions=[_hide_condition(stealth_total=22)])
        # PP 15 < 22, qualifies
        state = _state_with([observer, e1, e2])
        self.assertTrue(_has_unspotted_hidden_enemy(observer, state))


class BuiltInSearchEmissionTest(unittest.TestCase):

    def test_no_hidden_enemy_no_search(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0))
        state = _state_with([observer, enemy])
        builtins = built_in_actions_for(observer, "action", state)
        self.assertNotIn(BUILT_IN_SEARCH, builtins)

    def test_hidden_enemy_above_passive_emits_search(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=18)])
        state = _state_with([observer, enemy])
        builtins = built_in_actions_for(observer, "action", state)
        self.assertIn(BUILT_IN_SEARCH, builtins)

    def test_auto_spot_case_no_search(self) -> None:
        observer = _make_actor("obs", passive_perception=20)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=15)])
        state = _state_with([observer, enemy])
        builtins = built_in_actions_for(observer, "action", state)
        self.assertNotIn(BUILT_IN_SEARCH, builtins)

    def test_bonus_slot_no_search(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=18)])
        state = _state_with([observer, enemy])
        builtins = built_in_actions_for(observer, "bonus_action", state)
        self.assertNotIn(BUILT_IN_SEARCH, builtins)

    def test_explicit_search_suppresses_builtin(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        # Add an explicit search action to template
        observer.template["actions"].append({
            "id": "a_custom_search", "name": "Detective Hunch",
            "type": "search", "pipeline": []})
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=18)])
        state = _state_with([observer, enemy])
        builtins = built_in_actions_for(observer, "action", state)
        self.assertNotIn(BUILT_IN_SEARCH, builtins)


# ============================================================================
# Layer 2: _execute_search semantics
# ============================================================================

class ExecuteSearchTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_no_candidates_logs_no_targets(self) -> None:
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0))
        state = _state_with([observer, enemy])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        events = [e for e in state.event_log
                    if e.get("event") == "search_attempted"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["outcome"], "no_targets")

    def test_failed_check_no_reveal(self) -> None:
        # Set passive low, but the active check ALSO needs to fail.
        # Force a low roll with seed 1 (d20=5 with random.Random(1));
        # observer has no Perception proficiency, WIS 12 (+1) → total 6.
        # Stealth total 25 → fails.
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=25)])
        state = _state_with([observer, enemy])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Hide-source Invisible should still be present
        hide_conds = [c for c in enemy.applied_conditions
                        if c.get("condition_id") == "co_invisible"
                        and c.get("source_action_id") == "a_hide"]
        self.assertEqual(len(hide_conds), 1)
        # search_check event logged with failed outcome
        check_events = [e for e in state.event_log
                          if e.get("event") == "search_check"]
        self.assertEqual(len(check_events), 1)
        self.assertEqual(check_events[0]["outcome"], "failed")

    def test_successful_check_reveals(self) -> None:
        # DC trivially low (5) — observer's d20+1 will beat it on any roll.
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=5)])
        state = _state_with([observer, enemy])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Hide-source Invisible scrubbed
        hide_conds = [c for c in enemy.applied_conditions
                        if c.get("condition_id") == "co_invisible"
                        and c.get("source_action_id") == "a_hide"]
        self.assertEqual(len(hide_conds), 0)
        # creature_revealed event fired
        reveal_events = [e for e in state.event_log
                            if e.get("event") == "creature_revealed"]
        self.assertEqual(len(reveal_events), 1)
        self.assertEqual(reveal_events[0]["target"], enemy.id)

    def test_perception_proficiency_adds_pb(self) -> None:
        # WIS 12 (+1) + PB 3 (template) = +4. DC 4 should pass on
        # d20=1 (1+4=5 >= 4)? Actually 1+4=5 >= 4 yes. Use DC 5 to
        # confirm proficiency helps.
        # Actually, observer with perception prof and total +4 needs
        # d20 >= 1 to pass DC 5. Without prof it needs d20 >= 4.
        # Test that proficiency causes Perception check to include PB.
        observer = _make_actor("obs", passive_perception=14,
                                  skill_proficiencies=["perception"])
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=18)])
        state = _state_with([observer, enemy])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        check_events = [e for e in state.event_log
                          if e.get("event") == "search_check"]
        self.assertEqual(len(check_events), 1)
        # Perception mod should be WIS +1 + PB +3 = 4
        self.assertEqual(check_events[0]["perception_mod"], 4)

    def test_no_proficiency_perception_mod_is_just_ability(self) -> None:
        observer = _make_actor("obs", passive_perception=11)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=15)])
        state = _state_with([observer, enemy])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        check_events = [e for e in state.event_log
                          if e.get("event") == "search_check"]
        self.assertEqual(check_events[0]["perception_mod"], 1)    # WIS 12 +1

    def test_spell_invisible_untouched(self) -> None:
        # Spell-source Invisible should NOT be scrubbed by Search.
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_spell_invisible()])
        state = _state_with([observer, enemy])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # The check shouldn't even fire (no candidates)
        check_events = [e for e in state.event_log
                          if e.get("event") == "search_check"]
        self.assertEqual(len(check_events), 0)
        # Spell-source Invisible still present
        spell_conds = [c for c in enemy.applied_conditions
                          if c.get("condition_id") == "co_invisible"]
        self.assertEqual(len(spell_conds), 1)

    def test_mixed_invisible_only_scrubs_hide_source(self) -> None:
        # Enemy with BOTH Hide AND spell Invisible. Successful Search
        # should scrub the Hide only.
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[
                                  _hide_condition(stealth_total=5),
                                  _spell_invisible(),
                              ])
        state = _state_with([observer, enemy])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        remaining = enemy.applied_conditions
        hide_left = [c for c in remaining
                        if c.get("source_action_id") == "a_hide"]
        spell_left = [c for c in remaining
                         if c.get("source_action_id") == "a_invisibility_spell"]
        self.assertEqual(len(hide_left), 0)
        self.assertEqual(len(spell_left), 1)

    def test_multiple_hidden_enemies_independent(self) -> None:
        # Two hidden enemies — each gets its own check.
        observer = _make_actor("obs", passive_perception=10)
        e1 = _make_actor("e1", side="enemy", position=(2, 0),
                            applied_conditions=[_hide_condition(stealth_total=5)])
        e2 = _make_actor("e2", side="enemy", position=(2, 1),
                            applied_conditions=[_hide_condition(stealth_total=25)])
        state = _state_with([observer, e1, e2])
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        check_events = [e for e in state.event_log
                          if e.get("event") == "search_check"]
        self.assertEqual(len(check_events), 2)
        # e1 (DC 5) revealed; e2 (DC 25) still hidden
        e1_hide = [c for c in e1.applied_conditions
                      if c.get("source_action_id") == "a_hide"]
        e2_hide = [c for c in e2.applied_conditions
                      if c.get("source_action_id") == "a_hide"]
        self.assertEqual(len(e1_hide), 0)
        self.assertEqual(len(e2_hide), 1)


# ============================================================================
# End-to-end: Search makes the revealed enemy visible to can_actor_see
# ============================================================================

class SearchRevealsForVisionTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_revealed_enemy_visible_via_can_actor_see(self) -> None:
        from engine.core.vision import can_actor_see
        observer = _make_actor("obs", passive_perception=10)
        enemy = _make_actor("e", side="enemy", position=(2, 0),
                              applied_conditions=[_hide_condition(stealth_total=5)])
        state = _state_with([observer, enemy])
        # Before Search: enemy is hidden (PP 10 < stealth 5? wait,
        # 10 >= 5 means auto-spotted by passive. Let me bump stealth.
        enemy.applied_conditions = [_hide_condition(stealth_total=15)]
        self.assertFalse(can_actor_see(observer, enemy, state))
        # After successful Search (DC 5 — re-set the condition)
        enemy.applied_conditions = [_hide_condition(stealth_total=5)]
        pipeline_execute({"kind": "search", "actor": observer,
                            "target": observer, "action": _search_action()},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Hide scrubbed → enemy is now visible
        self.assertTrue(can_actor_see(observer, enemy, state))


if __name__ == "__main__":
    unittest.main()
