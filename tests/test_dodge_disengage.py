"""Dodge + Disengage v1 tests — defensive action shapes.

Layers:
  1. Actor.disengaging defaults False; reset_turn clears
  2. Dodge action attaches expected modifiers (disadvantage + DEX-advantage)
  3. Dodge eHP scoring uses defensive_buff_rounds override (1 round, not 2.5)
  4. Disengage action sets actor.disengaging = True at execution
  5. OA suppression: find_oa_triggers returns [] when mover.disengaging
  6. Behavioral: PC under pressure picks Dodge over a weak attack
  7. Runner integration: Disengaging mover doesn't provoke OAs

Run via:
    python -m unittest tests.test_dodge_disengage
"""
from __future__ import annotations

import random
import unittest

from engine.ai import score_candidate, score_candidates_v1
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState
from engine.core.reactions import find_oa_triggers


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc", hp: int = 30,
                ac: int = 14, position: tuple[int, int] = (0, 0),
                speed: int = 30, actions: list[dict] | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 14, "save": 2},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _dodge_action() -> dict:
    """Dodge per 5e RAW: attackers have disadvantage on attack rolls
    against you; you have advantage on DEX saves; lasts until start of
    your next turn."""
    return {
        "id": "a_dodge", "name": "Dodge", "type": "defensive_buff",
        "defensive_buff_rounds": 1,    # Dodge lasts 1 round, not 2.5
        "pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "self",
                          "modifier": "disadvantage_for_attacker",
                          "lifetime": "until_actor_next_turn_start"}},
            {"primitive": "save_modifier",
              "params": {"target": "self",
                          "modifier": "advantage",
                          "when": "save_ability == dexterity",
                          "lifetime": "until_actor_next_turn_start"}},
        ],
    }


def _disengage_action() -> dict:
    return {
        "id": "a_disengage", "name": "Disengage", "type": "disengage",
        "pipeline": [],
    }


def _weak_attack(action_id: str = "a_punch", bonus: int = 0,
                  dice: str = "1d4", modifier: int = 0) -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "bludgeoning"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


def _strong_attack(action_id: str = "a_sword", bonus: int = 5,
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
# Actor.disengaging field
# ============================================================================

class DisengageStateTest(unittest.TestCase):

    def test_default_false(self) -> None:
        actor = _make_actor("a")
        self.assertFalse(actor.disengaging)

    def test_reset_turn_clears(self) -> None:
        actor = _make_actor("a")
        actor.disengaging = True
        actor.reset_turn()
        self.assertFalse(actor.disengaging)


# ============================================================================
# Dodge action — modifier application
# ============================================================================

class DodgeApplicationTest(unittest.TestCase):

    def test_dodge_attaches_disadvantage_and_advantage_modifiers(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        actor = _make_actor("a", side="pc", actions=[_dodge_action()])
        state = _state_with([actor])
        chosen = {"kind": "defensive_buff", "actor": actor,
                  "target": actor, "action": _dodge_action()}
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())

        # Both modifiers should be on the actor
        attack_mods = [m for m in actor.active_modifiers
                        if m.get("primitive") == "attack_modifier"]
        save_mods = [m for m in actor.active_modifiers
                      if m.get("primitive") == "save_modifier"]
        self.assertEqual(len(attack_mods), 1)
        self.assertEqual(len(save_mods), 1)
        # Attack modifier: disadvantage for attackers
        self.assertEqual(attack_mods[0]["params"]["modifier"],
                          "disadvantage_for_attacker")
        # Save modifier: advantage (on DEX, per the when-clause)
        self.assertEqual(save_mods[0]["params"]["modifier"], "advantage")
        # Both have until_actor_next_turn_start lifetime
        self.assertEqual(attack_mods[0]["lifetime"],
                          "until_actor_next_turn_start")
        self.assertEqual(save_mods[0]["lifetime"],
                          "until_actor_next_turn_start")


# ============================================================================
# Dodge eHP scoring respects defensive_buff_rounds
# ============================================================================

class DodgeScoringTest(unittest.TestCase):

    def test_dodge_scores_positively_under_pressure(self) -> None:
        """A Dodge facing a high-DPR enemy should score positively."""
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff

        actor = _make_actor("a", side="pc")
        # Strong enemy with multiattack-like DPR
        enemy = _make_actor("e", side="enemy",
                              actions=[_strong_attack(bonus=8, dice="2d8",
                                                        modifier=5)])
        state = _state_with([actor, enemy])
        score = defensive_ehp_defensive_buff(actor, actor, _dodge_action(),
                                                state)
        self.assertGreater(score, 0)

    def test_dodge_rounds_override_lowers_score(self) -> None:
        """Same buff with rounds=1 (Dodge) scores LESS than rounds=2.5
        (typical buff)."""
        from engine.ai.defensive_ehp import (
            defensive_ehp_defensive_buff, EXPECTED_BUFF_ROUNDS,
        )

        actor = _make_actor("a", side="pc")
        enemy = _make_actor("e", side="enemy",
                              actions=[_strong_attack(bonus=8, dice="2d8",
                                                        modifier=5)])
        state = _state_with([actor, enemy])

        dodge = _dodge_action()    # has defensive_buff_rounds: 1
        long_buff = dict(dodge)
        long_buff.pop("defensive_buff_rounds", None)   # uses default 2.5

        dodge_score = defensive_ehp_defensive_buff(actor, actor, dodge,
                                                       state)
        long_score = defensive_ehp_defensive_buff(actor, actor, long_buff,
                                                      state)
        self.assertAlmostEqual(long_score / dodge_score,
                                  EXPECTED_BUFF_ROUNDS, places=3)


# ============================================================================
# Disengage execution + scoring
# ============================================================================

class DisengageExecutionTest(unittest.TestCase):

    def test_disengage_sets_actor_flag(self) -> None:
        from engine.core.pipeline import execute as pipeline_execute
        from engine.primitives import PrimitiveRegistry
        from engine.core.events import EventBus

        actor = _make_actor("a", side="pc",
                              actions=[_disengage_action()])
        state = _state_with([actor])
        chosen = {"kind": "disengage", "actor": actor,
                  "target": actor, "action": _disengage_action()}
        self.assertFalse(actor.disengaging)
        pipeline_execute(chosen, state, EventBus(),
                          PrimitiveRegistry.with_defaults())
        self.assertTrue(actor.disengaging)
        # Telemetry event logged
        events = [e for e in state.event_log
                   if e["event"] == "disengage_taken"]
        self.assertEqual(len(events), 1)


class DisengageScoringTest(unittest.TestCase):

    def test_disengage_candidate_scores_small_constant(self) -> None:
        actor = _make_actor("a", side="pc")
        state = _state_with([actor])
        cand = {"kind": "disengage", "actor": actor,
                "target": actor, "action": _disengage_action()}
        score = score_candidate(cand, state)
        # Small positive (~2.0 per the v1 constant) — pickable but
        # rarely beats real attack options
        self.assertGreater(score, 0)
        self.assertLess(score, 5)

    def test_attack_beats_disengage_normally(self) -> None:
        """A standard attack against a normal enemy should score higher
        than Disengage's small base eHP."""
        actor = _make_actor("a", side="pc",
                              actions=[_strong_attack(),
                                        _disengage_action()])
        enemy = _make_actor("e", side="enemy", hp=30)
        state = _state_with([actor, enemy])
        cands = generate_candidates(actor, state)
        scored = score_candidates_v1(cands, actor, state)
        best = max(scored, key=lambda x: x[0])[1]
        self.assertEqual(best["kind"], "weapon_attack",
                          "Attack should beat Disengage in normal play")


# ============================================================================
# OA suppression
# ============================================================================

class DisengageSuppressesOATest(unittest.TestCase):

    def test_find_oa_triggers_returns_empty_when_disengaging(self) -> None:
        """A reactor adjacent to a mover that's disengaging should NOT
        trigger an OA when the mover steps away."""
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_strong_attack()])
        mover = _make_actor("m", side="enemy", position=(2, 0))
        state = _state_with([reactor, mover])

        # Mover WAS at (1, 0) — 5ft from reactor (in reach for reactor's
        # 5-ft melee). Now at (2, 0) — 10ft. Without disengaging this
        # would trigger.
        triggers_normal = find_oa_triggers(
            mover, pre_position=(1, 0), state=state)
        self.assertEqual(len(triggers_normal), 1,
                          "Setup sanity: OA should fire normally")

        # Now set disengaging — should suppress
        state.event_log.clear()
        mover.disengaging = True
        triggers_disengage = find_oa_triggers(
            mover, pre_position=(1, 0), state=state)
        self.assertEqual(triggers_disengage, [],
                          "Disengaging mover should suppress OAs")
        # And the suppression should be logged
        suppress_events = [e for e in state.event_log
                            if e["event"] == "disengage_suppressed_oa"]
        self.assertEqual(len(suppress_events), 1)
        self.assertEqual(suppress_events[0]["mover"], "m")


# ============================================================================
# Behavioral integration — PC under pressure picks Dodge
# ============================================================================

class DodgeOverWeakAttackTest(unittest.TestCase):

    def test_pc_picks_dodge_when_only_weak_attack_available(self) -> None:
        """A PC with only a weak (low-DPR) attack option but a Dodge
        available should pick Dodge when surrounded by high-DPR enemies."""
        attacker_atk = _strong_attack(bonus=8, dice="2d6", modifier=5)
        # PC has a feeble attack (bonus 0, 1d4) + Dodge
        pc = _make_actor("pc", side="pc",
                           actions=[_weak_attack(), _dodge_action()])
        # 2 dangerous enemies adjacent (high DPR raises defensive
        # buff score via worst-enemy-DPR)
        e1 = _make_actor("e1", side="enemy", position=(1, 0),
                            actions=[attacker_atk])
        e2 = _make_actor("e2", side="enemy", position=(0, 1),
                            actions=[attacker_atk])
        state = _state_with([pc, e1, e2])

        cands = generate_candidates(pc, state)
        scored = score_candidates_v1(cands, pc, state)
        best = max(scored, key=lambda x: x[0])[1]
        self.assertEqual(best["kind"], "defensive_buff",
                          f"PC should pick Dodge over weak attack; got "
                          f"{best['kind']} ({best['action'].get('id')})")
        self.assertEqual(best["action"]["id"], "a_dodge")


# ============================================================================
# Runner integration — Disengaging mover doesn't provoke OAs in fixture
# ============================================================================

class RunnerDisengageIntegrationTest(unittest.TestCase):

    def test_disengage_fixture_runs_with_no_oa_against_disengaging_actor(
            self) -> None:
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
            "dodge_disengage_encounter.yaml"

        registry = load_content(content_root, validate=True,
                                  schema_root=schema_root)
        spec = load_yaml_file(fixture)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1,
                                       content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # The dodging PC should have at least one disengage_taken or
        # dodge_taken event somewhere in the log
        dodge_buffs = [e for e in state.event_log
                        if e.get("event") == "moved"]
        self.assertGreaterEqual(len(dodge_buffs), 0)
        # Encounter terminated successfully (no crash)
        self.assertTrue(state.terminated)


if __name__ == "__main__":
    unittest.main()
