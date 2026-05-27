"""Pace-aware reaction tests (PR #56).

Layers:
  1. reaction_cost_ehp formula: scarcity × urgency × base_cost
  2. Per-reaction value estimators:
     - shield_value_ehp: returns attacker's best weapon DPR; falls
       back to inf when attacker is missing
     - counterspell_value_ehp: uses spell's slot level via
       REACTION_SLOT_BASE_COSTS curve
     - hellish_rebuke_value_ehp: 2d10 fire avg w/ resistance/immunity
  3. estimate_reaction_value_ehp dispatch:
     - known reaction → estimator
     - unknown reaction → inf (forward compat)
  4. try_use_reaction pace gate:
     - cost > value → skip (logs reaction_skipped_pace)
     - cost <= value → fire (logs reaction_fired)
     - signature_reaction: true → bypasses pace gate entirely
     - slot_level == 0 → bypasses pace gate (OA-shape reactions)
     - last encounter of day → cost low → reactions fire freely
     - many encounters left + last slot → cost high → reactions skip

Run via:
    python -m unittest tests.test_pace_aware_reactions
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from engine.ai.reaction_scoring import (
    _dice_avg, _estimate_attack_damage,
    counterspell_value_ehp, estimate_reaction_value_ehp,
    hellish_rebuke_value_ehp, shield_value_ehp,
)
from engine.core.feature_pacing import (
    REACTION_SLOT_BASE_COSTS, reaction_cost_ehp,
)
from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  spell_slots=None, actions=None,
                  damage_resistances=None, damage_immunities=None,
                  damage_vulnerabilities=None) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": actions or []}
    if damage_resistances:
        template["damage_resistances"] = list(damage_resistances)
    if damage_immunities:
        template["damage_immunities"] = list(damage_immunities)
    if damage_vulnerabilities:
        template["damage_vulnerabilities"] = list(damage_vulnerabilities)
    actor = Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=30, hp_max=30, ac=14,
                   speed={"walk": 30}, position=position,
                   abilities=abilities,
                   spell_slots=dict(spell_slots or {}))
    return actor


def _state_with(actors, encounters_remaining=3):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc,
                          encounters_remaining_today=encounters_remaining)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _weapon_attack(name="Greatsword", dice="2d6", modifier=4,
                      damage_type="slashing"):
    return {
        "id": f"a_{name.lower().replace(' ', '_')}", "name": name,
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": damage_type},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# Layer 1: reaction_cost_ehp
# ============================================================================

class ReactionCostFormulaTest(unittest.TestCase):

    def test_zero_slot_level_zero_cost(self) -> None:
        # OA-shape reactions (no slot) have no opportunity cost.
        self.assertEqual(reaction_cost_ehp(0, 5, 3), 0.0)

    def test_zero_slots_remaining_zero_cost(self) -> None:
        # Caller should have already gated; return 0 cleanly.
        self.assertEqual(reaction_cost_ehp(1, 0, 3), 0.0)

    def test_scarcity_higher_cost_with_fewer_slots(self) -> None:
        # 1 slot at level 1 = max scarcity
        cost_one = reaction_cost_ehp(1, 1, 3)
        cost_many = reaction_cost_ehp(1, 4, 3)
        self.assertGreater(cost_one, cost_many)

    def test_urgency_higher_cost_with_more_encounters_left(self) -> None:
        cost_many = reaction_cost_ehp(1, 1, 5)
        cost_few = reaction_cost_ehp(1, 1, 1)
        self.assertGreater(cost_many, cost_few)

    def test_last_encounter_cost_is_low(self) -> None:
        # encounters_remaining=1 → urgency_factor = 1/3 ≈ 0.33
        # cost = REACTION_SLOT_BASE_COSTS[1] * 1 * 0.33 ≈ 3.33
        # (PR #67 calibration bumped L1 base from 4.0 to 10.0)
        cost = reaction_cost_ehp(1, 1, 1)
        self.assertAlmostEqual(cost, REACTION_SLOT_BASE_COSTS[1] / 3.0,
                                  places=2)

    def test_higher_slot_level_higher_base_cost(self) -> None:
        cost_1 = reaction_cost_ehp(1, 1, 3)
        cost_3 = reaction_cost_ehp(3, 1, 3)
        self.assertGreater(cost_3, cost_1)

    def test_custom_base_cost_map_overrides(self) -> None:
        custom = {1: 100.0}
        cost = reaction_cost_ehp(1, 1, 3, base_cost_per_level=custom)
        self.assertEqual(cost, 100.0)

    def test_slot_level_above_table_uses_max(self) -> None:
        # Level 99 isn't in the table; should clamp to max known.
        # Just verify it doesn't crash and returns > 0.
        cost = reaction_cost_ehp(99, 1, 3)
        self.assertGreater(cost, 0.0)


# ============================================================================
# Layer 2a: shield_value_ehp
# ============================================================================

class ShieldValueTest(unittest.TestCase):

    def test_missing_attacker_returns_inf(self) -> None:
        # Defensive: stripped event_data shape
        value = shield_value_ehp({}, {}, MagicMock(), MagicMock())
        self.assertEqual(value, float("inf"))

    def test_attacker_with_no_attacks_returns_inf(self) -> None:
        attacker = _make_actor("a")    # no weapon attacks in template
        ed = {"actor": attacker}
        value = shield_value_ehp({}, ed, MagicMock(), MagicMock())
        self.assertEqual(value, float("inf"))

    def test_attacker_dpr_estimated(self) -> None:
        attacker = _make_actor("ogre",
                                  actions=[_weapon_attack(dice="2d6",
                                                            modifier=4)])
        ed = {"actor": attacker}
        value = shield_value_ehp({}, ed, MagicMock(), MagicMock())
        # 2d6 avg = 7 + 4 = 11
        self.assertEqual(value, 11.0)

    def test_picks_highest_dpr_among_multiple_attacks(self) -> None:
        attacker = _make_actor("multi", actions=[
            _weapon_attack(name="Dagger", dice="1d4", modifier=2),
            _weapon_attack(name="Greatsword", dice="2d6", modifier=4),
        ])
        ed = {"actor": attacker}
        value = shield_value_ehp({}, ed, MagicMock(), MagicMock())
        # Greatsword: 7+4=11 wins over dagger: 2.5+2=4.5
        self.assertEqual(value, 11.0)


# ============================================================================
# Layer 2b: counterspell_value_ehp
# ============================================================================

class CounterspellValueTest(unittest.TestCase):

    def test_spell_slot_level_used(self) -> None:
        ed = {"spell_slot_level": 3}
        value = counterspell_value_ehp({}, ed, MagicMock(), MagicMock())
        self.assertEqual(value, REACTION_SLOT_BASE_COSTS[3])

    def test_fallback_to_spell_level_key(self) -> None:
        # Test event_data shape (some tests use spell_level)
        ed = {"spell_level": 5}
        value = counterspell_value_ehp({}, ed, MagicMock(), MagicMock())
        self.assertEqual(value, REACTION_SLOT_BASE_COSTS[5])

    def test_default_level_when_missing(self) -> None:
        ed = {}
        value = counterspell_value_ehp({}, ed, MagicMock(), MagicMock())
        self.assertEqual(value, REACTION_SLOT_BASE_COSTS[1])

    def test_high_spell_level_clamps_to_max(self) -> None:
        ed = {"spell_slot_level": 99}
        value = counterspell_value_ehp({}, ed, MagicMock(), MagicMock())
        # Should not crash, should return max known
        self.assertEqual(value, REACTION_SLOT_BASE_COSTS[
            max(REACTION_SLOT_BASE_COSTS)])


# ============================================================================
# Layer 2c: hellish_rebuke_value_ehp
# ============================================================================

class HellishRebukeValueTest(unittest.TestCase):

    def test_missing_attacker_returns_inf(self) -> None:
        value = hellish_rebuke_value_ehp({}, {}, MagicMock(), MagicMock())
        self.assertEqual(value, float("inf"))

    def test_default_value_about_8_point_25(self) -> None:
        attacker = _make_actor("ogre")
        ed = {"attacker": attacker}
        value = hellish_rebuke_value_ehp({}, ed, MagicMock(), MagicMock())
        self.assertAlmostEqual(value, 11.0 * 0.5 + 5.5 * 0.5, places=2)

    def test_fire_immunity_zeros_value(self) -> None:
        attacker = _make_actor("fiend", damage_immunities=["fire"])
        ed = {"attacker": attacker}
        value = hellish_rebuke_value_ehp({}, ed, MagicMock(), MagicMock())
        self.assertEqual(value, 0.0)

    def test_fire_resistance_halves_value(self) -> None:
        attacker = _make_actor("dragon", damage_resistances=["fire"])
        ed = {"attacker": attacker}
        value = hellish_rebuke_value_ehp({}, ed, MagicMock(), MagicMock())
        expected = (11.0 * 0.5 + 5.5 * 0.5) / 2.0
        self.assertAlmostEqual(value, expected, places=2)

    def test_fire_vulnerability_doubles_value(self) -> None:
        attacker = _make_actor("ice", damage_vulnerabilities=["fire"])
        ed = {"attacker": attacker}
        value = hellish_rebuke_value_ehp({}, ed, MagicMock(), MagicMock())
        expected = (11.0 * 0.5 + 5.5 * 0.5) * 2.0
        self.assertAlmostEqual(value, expected, places=2)


# ============================================================================
# Layer 3: estimate_reaction_value_ehp dispatch
# ============================================================================

class EstimateDispatchTest(unittest.TestCase):

    def test_unknown_reaction_returns_inf(self) -> None:
        # Preserves v1 always-fire semantics for reactions not yet scored.
        action = {"id": "a_unknown_reaction"}
        value = estimate_reaction_value_ehp(action, {},
                                                MagicMock(), MagicMock())
        self.assertEqual(value, float("inf"))

    def test_shield_dispatches(self) -> None:
        attacker = _make_actor("a",
                                  actions=[_weapon_attack(dice="1d6",
                                                            modifier=3)])
        action = {"id": "a_shield"}
        ed = {"actor": attacker}
        value = estimate_reaction_value_ehp(action, ed,
                                                MagicMock(), MagicMock())
        # 1d6 = 3.5 + 3 = 6.5
        self.assertEqual(value, 6.5)

    def test_counterspell_dispatches(self) -> None:
        action = {"id": "a_counterspell"}
        ed = {"spell_slot_level": 3}
        value = estimate_reaction_value_ehp(action, ed,
                                                MagicMock(), MagicMock())
        self.assertEqual(value, REACTION_SLOT_BASE_COSTS[3])

    def test_hellish_rebuke_dispatches(self) -> None:
        attacker = _make_actor("ogre")
        action = {"id": "a_hellish_rebuke"}
        ed = {"attacker": attacker}
        value = estimate_reaction_value_ehp(action, ed,
                                                MagicMock(), MagicMock())
        self.assertGreater(value, 0.0)


# ============================================================================
# Layer 4: try_use_reaction pace gate
# ============================================================================

def _shield_action(signature=False):
    a = {
        "id": "a_shield", "name": "Shield",
        "type": "defensive_buff", "spell_slot_level": 1,
        "slot": "reaction", "trigger": "attack_roll_pending",
        "condition": "shield_would_help",
        "pipeline": [{"primitive": "attack_modifier",
                       "params": {"target": "self",
                                   "modifier": "ac_modifier",
                                   "value": 5,
                                   "lifetime": "until_actor_next_turn_start"}}],
    }
    if signature:
        a["signature_reaction"] = True
    return a


class TryUseReactionPaceGateTest(unittest.TestCase):

    def test_cost_exceeds_value_skips(self) -> None:
        """Wizard with 1 slot, 3 encounters left, weak attacker.
        Cost (4 × 1 × 1 = 4); value = attacker's tiny DPR (1).
        Cost > value → skip."""
        from engine.core.reactions import try_use_reaction
        weak_attacker = _make_actor("kid",
                                       actions=[_weapon_attack(
                                           dice="1d1", modifier=0)])
        wizard = _make_actor("wiz", spell_slots={1: 1},
                                actions=[_shield_action()])
        state = _state_with([wizard, weak_attacker], encounters_remaining=3)
        ed = {"actor": weak_attacker, "target": wizard,
                "total": 18, "current_ac": 15}
        result = try_use_reaction(
            wizard, _shield_action(), ed, state, bus=None)
        self.assertFalse(result)
        # Slot NOT consumed
        self.assertEqual(wizard.spell_slots[1], 1)
        # Skip event logged
        skip_events = [e for e in state.event_log
                          if e.get("event") == "reaction_skipped_pace"]
        self.assertEqual(len(skip_events), 1)

    def test_value_exceeds_cost_fires(self) -> None:
        """Wizard with 1 slot, 3 encounters left, big attacker.
        Cost (4 × 1 × 1 = 4); value = attacker's big DPR (11).
        Value > cost → fire."""
        from engine.core.reactions import try_use_reaction
        ogre = _make_actor("ogre",
                              actions=[_weapon_attack(dice="2d6",
                                                        modifier=4)])
        wizard = _make_actor("wiz", spell_slots={1: 1},
                                actions=[_shield_action()])
        state = _state_with([wizard, ogre], encounters_remaining=3)
        ed = {"actor": ogre, "target": wizard,
                "total": 18, "current_ac": 15}
        result = try_use_reaction(
            wizard, _shield_action(), ed, state, bus=None)
        self.assertTrue(result)
        self.assertEqual(wizard.spell_slots[1], 0)

    def test_last_encounter_lowers_cost(self) -> None:
        """Same setup but encounters_remaining=1.
        Cost should drop below the weak attacker's value."""
        from engine.core.reactions import try_use_reaction
        attacker = _make_actor("a",
                                  actions=[_weapon_attack(dice="1d6",
                                                            modifier=0)])
        wizard = _make_actor("wiz", spell_slots={1: 1},
                                actions=[_shield_action()])
        state = _state_with([wizard, attacker], encounters_remaining=1)
        ed = {"actor": attacker, "target": wizard,
                "total": 18, "current_ac": 15}
        result = try_use_reaction(
            wizard, _shield_action(), ed, state, bus=None)
        # cost = 4 × 1 × (1/3) = 1.33; value = 1d6 (3.5) + 0 = 3.5
        self.assertTrue(result)

    def test_signature_reaction_bypasses_pace(self) -> None:
        """signature_reaction: true on the action → always fire
        regardless of cost/value comparison."""
        from engine.core.reactions import try_use_reaction
        weak_attacker = _make_actor("kid",
                                       actions=[_weapon_attack(
                                           dice="1d1", modifier=0)])
        wizard = _make_actor("wiz", spell_slots={1: 1},
                                actions=[_shield_action(signature=True)])
        state = _state_with([wizard, weak_attacker], encounters_remaining=3)
        ed = {"actor": weak_attacker, "target": wizard,
                "total": 18, "current_ac": 15}
        result = try_use_reaction(
            wizard, _shield_action(signature=True), ed, state, bus=None)
        self.assertTrue(result)

    def test_many_slots_lowers_cost(self) -> None:
        """6 slots at level 1 vs same big attacker: cost trivial,
        value high → fires easily."""
        from engine.core.reactions import try_use_reaction
        ogre = _make_actor("ogre",
                              actions=[_weapon_attack(dice="2d6",
                                                        modifier=4)])
        wizard = _make_actor("wiz", spell_slots={1: 6},
                                actions=[_shield_action()])
        state = _state_with([wizard, ogre], encounters_remaining=3)
        ed = {"actor": ogre, "target": wizard,
                "total": 18, "current_ac": 15}
        result = try_use_reaction(
            wizard, _shield_action(), ed, state, bus=None)
        self.assertTrue(result)
        self.assertEqual(wizard.spell_slots[1], 5)

    def test_skip_log_has_cost_and_value(self) -> None:
        """The reaction_skipped_pace event should include all the
        relevant diagnostic fields."""
        from engine.core.reactions import try_use_reaction
        kid = _make_actor("kid",
                             actions=[_weapon_attack(dice="1d1", modifier=0)])
        wizard = _make_actor("wiz", spell_slots={1: 1},
                                actions=[_shield_action()])
        state = _state_with([wizard, kid], encounters_remaining=3)
        ed = {"actor": kid, "target": wizard,
                "total": 18, "current_ac": 15}
        try_use_reaction(wizard, _shield_action(), ed, state, bus=None)
        skip_events = [e for e in state.event_log
                          if e.get("event") == "reaction_skipped_pace"]
        self.assertEqual(len(skip_events), 1)
        e = skip_events[0]
        self.assertIn("cost_ehp", e)
        self.assertIn("value_ehp", e)
        self.assertEqual(e["slot_level"], 1)
        self.assertEqual(e["slots_remaining"], 1)
        self.assertEqual(e["encounters_remaining"], 3)


# ============================================================================
# Dice helper
# ============================================================================

class DiceHelperTest(unittest.TestCase):

    def test_d6(self) -> None:
        self.assertEqual(_dice_avg("1d6"), 3.5)
    def test_2d6(self) -> None:
        self.assertEqual(_dice_avg("2d6"), 7.0)
    def test_1d10(self) -> None:
        self.assertEqual(_dice_avg("1d10"), 5.5)
    def test_garbage_returns_zero(self) -> None:
        self.assertEqual(_dice_avg("garbage"), 0.0)
    def test_empty_returns_zero(self) -> None:
        self.assertEqual(_dice_avg(""), 0.0)


if __name__ == "__main__":
    unittest.main()
