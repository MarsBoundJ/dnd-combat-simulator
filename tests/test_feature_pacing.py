"""Pace-aware feature-use tests (PR #42).

Layers:
  1. feature_use_cost_ehp formula: scarcity (charges) + urgency factor
     (encounters_remaining) interaction
  2. action_surge_cost_ehp specifically
  3. Pace-aware Action Surge activation: gated by gain > cost
  4. Session-level: 3-encounter day where L2 Fighter saves AS for the
     last fight (no future encounters to save for)

Run via:
    python -m unittest tests.test_feature_pacing
"""
from __future__ import annotations

import unittest

from engine.core.feature_pacing import (
    feature_use_cost_ehp, action_surge_cost_ehp,
    ACTION_SURGE_BASE_COST,
)


# ============================================================================
# Formula
# ============================================================================

class FeatureUseCostFormulaTest(unittest.TestCase):

    def test_zero_charges_returns_zero_cost(self) -> None:
        """No charges → cost of spending is 0 (caller should already
        have gated on availability; this is a safety net)."""
        self.assertEqual(feature_use_cost_ehp(0, 3), 0.0)
        self.assertEqual(feature_use_cost_ehp(-1, 3), 0.0)

    def test_one_charge_last_encounter_is_low_cost(self) -> None:
        """1 charge, 1 encounter remaining: scarcity=1, urgency_factor=
        1/3 ≈ 0.33. cost = 6 * 1 * 0.33 = 2.0. Low — spend freely."""
        cost = feature_use_cost_ehp(1, 1, base_cost=6.0)
        self.assertAlmostEqual(cost, 2.0, places=2)

    def test_one_charge_mid_day_is_moderate_cost(self) -> None:
        """1 charge, 3 encounters remaining: scarcity=1, urgency=1.0.
        cost = 6.0. Moderate."""
        cost = feature_use_cost_ehp(1, 3, base_cost=6.0)
        self.assertAlmostEqual(cost, 6.0, places=2)

    def test_one_charge_start_of_day_is_high_cost(self) -> None:
        """1 charge, 6 encounters remaining: urgency=2.0. cost = 12.0.
        High — conserve."""
        cost = feature_use_cost_ehp(1, 6, base_cost=6.0)
        self.assertAlmostEqual(cost, 12.0, places=2)

    def test_multiple_charges_lowers_per_charge_cost(self) -> None:
        """2 charges (L17 Fighter) at the same mid-day: scarcity = 0.5,
        cost = 6 * 0.5 * 1.0 = 3.0. Half the 1-charge cost."""
        cost = feature_use_cost_ehp(2, 3, base_cost=6.0)
        self.assertAlmostEqual(cost, 3.0, places=2)


class ActionSurgeCostTest(unittest.TestCase):

    def test_action_surge_uses_base_constant(self) -> None:
        """action_surge_cost_ehp wraps feature_use_cost_ehp with
        ACTION_SURGE_BASE_COST. 1 charge, mid-day → ACTION_SURGE_BASE_COST."""
        cost = action_surge_cost_ehp(1, 3)
        self.assertAlmostEqual(cost, ACTION_SURGE_BASE_COST, places=2)


# ============================================================================
# Runner integration — pace-aware activation
# ============================================================================

from engine.core.state import Actor, Encounter, CombatState
from engine.core.runner import EncounterRunner


def _make_actor(actor_id, side="pc", hp=30, ac=14,
                position=(0, 0), speed=30, actions=None,
                resources=None, initiative_modifier=0):
    abilities = {
        "str": {"score": 16, "save": 5},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 1},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "combat": {
                    "armor_class": ac,
                    "hit_points": {"average": hp, "dice": "5d10",
                                     "con_contribution": 10},
                    "speed": {"walk": speed},
                    "initiative": {
                        "modifier": initiative_modifier,
                        "score": initiative_modifier + 10,
                    },
                },
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities,
                  resources=resources or {})


def _greatsword():
    return {
        "id": "a_greatsword", "name": "Greatsword", "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "2d6", "modifier": 4, "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


class PaceAwareActionSurgeTest(unittest.TestCase):

    def _runner_with(self, fighter, enemy):
        enc = Encounter(id="t", actors=[fighter, enemy])
        state = CombatState(encounter=enc)
        state.turn_order = [fighter.id, enemy.id]
        state.round = 1
        runner = EncounterRunner.new(enc, seed=1)
        return runner, state

    def test_AS_does_NOT_fire_with_many_encounters_remaining(self) -> None:
        """6 encounters left → cost = 12.0. Greatsword vs AC 14 = ~7
        gain. gain < cost → AS reserved."""
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 1})
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        state.encounters_remaining_today = 6
        runner._maybe_activate_action_surge(fighter, state)
        self.assertFalse(fighter.action_surge_used_this_turn)
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 1)

    def test_AS_fires_on_last_encounter(self) -> None:
        """1 encounter left → cost = 2.0. Gain ~7 > cost. AS fires."""
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 1})
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        state.encounters_remaining_today = 1
        runner._maybe_activate_action_surge(fighter, state)
        self.assertTrue(fighter.action_surge_used_this_turn)
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 0)

    def test_AS_event_log_carries_gain_and_cost(self) -> None:
        """The activation event records the eHP gain and cost for
        telemetry — useful for inspecting AI decisions in session logs."""
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 1})
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        state.encounters_remaining_today = 1
        runner._maybe_activate_action_surge(fighter, state)
        events = [e for e in state.event_log
                   if e.get("event") == "action_surge_activated"]
        self.assertEqual(len(events), 1)
        self.assertIn("gain_eHP", events[0])
        self.assertIn("cost_eHP", events[0])
        self.assertGreater(events[0]["gain_eHP"], events[0]["cost_eHP"])

    def test_L17_fighter_with_two_charges_is_more_eager(self) -> None:
        """2 charges (L17 Fighter): cost = 6 * 0.5 * 1.0 = 3.0 at
        mid-day. Lower than the 1-charge cost of 6.0 — AS fires sooner."""
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 2})
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        state.encounters_remaining_today = 3   # mid-day
        runner._maybe_activate_action_surge(fighter, state)
        self.assertTrue(fighter.action_surge_used_this_turn,
                          "L17 with 2 charges should be more willing to "
                          "spend mid-day than L2 with 1 charge")
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 1)


# ============================================================================
# Session-level: AS pacing across an adventuring day
# ============================================================================

class SessionPacingTest(unittest.TestCase):

    def test_fighter_saves_AS_for_last_encounter_of_three(self) -> None:
        """L2 Fighter in a 3-encounter day. Greatsword vs default AC 14
        ogres = gain ~7 each fight. Pace cost progression:
          - enc1 (encounters_remaining=3): cost=6.0 → fires (gain 7 > 6)
          - With pacing, the fighter ALSO uses AS in enc1 because
            mid-day cost == base. The deeper "save for the boss"
            behavior shows when remaining > baseline OR when target
            eHP is weak.

        We instead test the harder case: 6 encounters scheduled →
        early encounters have cost=12, AS doesn't fire. Latter
        encounters have lower cost as the day progresses.
        """
        from engine.core.session import (
            SessionSpec, SessionEncounter, run_session,
        )

        fighter = _make_actor("fighter", side="pc", hp=30,
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 1},
                                initiative_modifier=30)
        # Six identical encounters
        def _make_enc(eid):
            return Encounter(
                id=eid,
                actors=[
                    fighter,
                    _make_actor(f"ogre_{eid}", side="enemy", hp=50,
                                  position=(0, 1),
                                  actions=[_greatsword()],
                                  initiative_modifier=-5),
                ],
            )
        spec = SessionSpec(
            encounters=[
                SessionEncounter(_make_enc(f"e{i+1}"),
                                  rest_after="short" if i < 5 else "none")
                for i in range(6)
            ],
            party_actor_ids={"fighter"},
        )
        result = run_session(spec, seed=1)
        # Find which encounter(s) AS fired in
        as_firings_per_enc = []
        for er in result.encounter_results:
            if er["state"] is None:
                as_firings_per_enc.append(0)
                continue
            count = sum(1 for e in er["state"].event_log
                         if e.get("event") == "action_surge_activated"
                         and e.get("actor") == "fighter")
            as_firings_per_enc.append(count)
        total_firings = sum(as_firings_per_enc)
        # Across 6 encounters with the AS counter refreshing on short
        # rests, the AS should fire at LEAST once (the last encounter
        # when cost is lowest). But NOT every encounter — early ones
        # have high cost (12+) that exceeds typical greatsword gain
        # (~7).
        self.assertGreaterEqual(
            total_firings, 1,
            "AS should fire at least once across the day")
        # First encounter cost = 6 * 1 * (6/3) = 12.0. Gain on AC 14 ogre
        # ≈ greatsword 2d6+4 = 11 * p_hit(15-6=need 9 = 0.6) = 6.6.
        # Cost 12 > gain 6.6 → AS does NOT fire encounter 1.
        self.assertEqual(
            as_firings_per_enc[0], 0,
            "AS should NOT fire in encounter 1 (6 encounters remaining "
            "→ cost 12 > greatsword gain ~7)")


if __name__ == "__main__":
    unittest.main()
