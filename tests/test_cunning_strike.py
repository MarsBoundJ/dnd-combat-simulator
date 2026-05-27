"""Cunning Strike tests (PR #81).

Layers:
  1. cunning_strike_dc formula: 8 + DEX_mod + PB
  2. qualifies_for_cunning_strike: Rogue L5+
  3. CUNNING_STRIKE_OPTIONS registry shape (poison, trip, withdraw)
  4. AI: skips effect when value < cost
  5. AI: picks Trip when adjacent ally amplifies value
  6. AI: picks Withdraw when adjacent to multiple enemies
  7. Effect application: Trip on fail → Prone applied
  8. Effect application: Trip size-gate (Huge target → no_effect_size_immune)
  9. Effect application: Withdraw sets actor.disengaging
 10. Effect application: Poison on fail → Poisoned applied
 11. Integration: SA dice reduced when CS effect chosen
 12. Integration: SA event includes cunning_strike fields
 13. Level gate: L4 Rogue doesn't trigger CS even when SA fires
 14. f_cunning_strike YAML loads + c_rogue L5 wires it
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.cunning_strike import (
    CUNNING_STRIKE_OPTIONS,
    MIN_ROGUE_LEVEL,
    cunning_strike_dc,
    qualifies_for_cunning_strike,
    pick_cunning_strike_effect,
    apply_cunning_strike_effect,
)
from engine.core.events import EventBus
from engine.core.sneak_attack import try_apply_sneak_attack
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_rogue(actor_id="rogue", *, level=5, position=(0, 0),
                  dex_score=18):
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": dex_score,
                  "save": (dex_score - 10) // 2 + 3},
        "con": {"score": 14, "save": 2},
        "int": {"score": 12, "save": 1},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0,
                "proficiency_bonus": 3 if level >= 5 else 2},
        "actions": [
            {"id": "a_rapier", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll",
                    "params": {"kind": "melee", "ability": "dex",
                                 "bonus": 7, "reach_ft": 5,
                                 "finesse": True}},
                  {"primitive": "damage",
                    "params": {"dice": "1d8", "modifier": 4,
                                 "type": "piercing"}},
              ]},
        ],
        "levels": {"rogue": level},
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side="pc",
        hp_current=35, hp_max=35, ac=15,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_fighter_ally(actor_id="ally", *, position=(0, 0)):
    """Multi-attack Fighter-shape ally. Two attacks per turn ramps
    the estimate_dpr value so Trip's party-coordination math
    crosses the 3.5 eHP cost threshold with reasonable numbers
    of allies. Mirrors PHB 2024 Fighter L5 with Extra Attack."""
    abilities = {k: {"score": 16 if k == "str" else 10,
                       "save": 3 if k == "str" else 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 3},
        "actions": [
            {"id": "a_sword", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll",
                    "params": {"kind": "melee", "bonus": 7,
                                 "reach_ft": 5}},
                  {"primitive": "damage",
                    "params": {"dice": "1d10", "modifier": 4,
                                 "type": "slashing"}},
              ]},
            # Multiattack: 2 swings per turn (Fighter L5 Extra Attack)
            {"id": "a_extra_attack", "type": "multiattack",
              "count": 2, "sub_actions": ["a_sword", "a_sword"]},
        ],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side="pc",
        hp_current=40, hp_max=40, ac=18,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_target(actor_id="dummy", *, position=(1, 0), side="enemy",
                   hp=80, size="medium", dex_save=0, con_save=0,
                   ac=14):
    abilities = {k: {"score": 12 if k == "str" else 10,
                       "save": (con_save if k == "con"
                                  else dex_save if k == "dex"
                                  else 1)}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 1, "xp": 200, "proficiency_bonus": 2},
        "actions": [
            {"id": "a_swing", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll",
                    "params": {"kind": "melee", "bonus": 4,
                                 "reach_ft": 5}},
                  {"primitive": "damage",
                    "params": {"dice": "1d8", "modifier": 2,
                                 "type": "slashing"}},
              ]},
        ],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
        size=size,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _set_attack_context(state, attacker, target, *, finesse=True,
                              had_advantage=True):
    state.current_attack = {
        "actor": attacker, "target": target,
        "action": attacker.template["actions"][0],
        "state": "hit",
        "had_advantage": had_advantage,
        "had_disadvantage": False,
    }


# ============================================================================
# Layer 1: DC formula
# ============================================================================

class CunningStrikeDcTest(unittest.TestCase):

    def test_dc_formula_dex_18_pb_3(self) -> None:
        # 8 + DEX_mod(18→+4) + PB(3) = 15
        actor = _make_rogue(level=5, dex_score=18)
        self.assertEqual(cunning_strike_dc(actor), 15)

    def test_dc_formula_dex_16_pb_2(self) -> None:
        # 8 + DEX_mod(16→+3) + PB(2) = 13
        actor = _make_rogue(level=2, dex_score=16)
        self.assertEqual(cunning_strike_dc(actor), 13)


# ============================================================================
# Layer 2: qualification
# ============================================================================

class QualificationTest(unittest.TestCase):

    def test_l5_qualifies(self) -> None:
        self.assertTrue(qualifies_for_cunning_strike(
            _make_rogue(level=5)))

    def test_l4_does_not_qualify(self) -> None:
        self.assertFalse(qualifies_for_cunning_strike(
            _make_rogue(level=4)))

    def test_l11_still_qualifies(self) -> None:
        self.assertTrue(qualifies_for_cunning_strike(
            _make_rogue(level=11)))


# ============================================================================
# Layer 3: registry shape
# ============================================================================

class RegistryShapeTest(unittest.TestCase):

    def test_three_options(self) -> None:
        self.assertIn("poison", CUNNING_STRIKE_OPTIONS)
        self.assertIn("trip", CUNNING_STRIKE_OPTIONS)
        self.assertIn("withdraw", CUNNING_STRIKE_OPTIONS)

    def test_each_costs_1d6_in_v1(self) -> None:
        for opt in CUNNING_STRIKE_OPTIONS.values():
            self.assertEqual(opt["cost_dice"], 1)

    def test_trip_has_size_gate(self) -> None:
        self.assertEqual(CUNNING_STRIKE_OPTIONS["trip"]["size_gate"],
                          "large")

    def test_withdraw_has_no_save(self) -> None:
        self.assertIsNone(
            CUNNING_STRIKE_OPTIONS["withdraw"]["save_ability"])


# ============================================================================
# Layer 4-6: AI heuristic
# ============================================================================

class AiHeuristicTest(unittest.TestCase):

    def test_skips_effect_when_no_value(self) -> None:
        # Rogue alone with a Huge target — Trip size-gated to 0,
        # Poison/Withdraw value low (no allies adjacent, no
        # adjacent enemies). Should pick None (full damage).
        attacker = _make_rogue()
        target = _make_target(position=(15, 0), size="huge",
                                 dex_save=10, con_save=10)
        state = _make_state([attacker, target])
        choice = pick_cunning_strike_effect(attacker, target, state)
        self.assertIsNone(choice)

    def test_solo_rogue_does_not_pick_trip(self) -> None:
        # Per Phil's note: Trip is a party-coordination move.
        # Solo Rogue gets zero value because the target stands up
        # before the Rogue's next turn — no ally to capitalize.
        attacker = _make_rogue(position=(0, 0))
        target = _make_target(position=(1, 0), size="medium",
                                 dex_save=-2)
        state = _make_state([attacker, target])
        choice = pick_cunning_strike_effect(attacker, target, state)
        self.assertNotEqual(choice, "trip")

    def test_picks_trip_when_party_can_capitalize(self) -> None:
        # Three-actor party with the right initiative order:
        # attacker (Rogue) goes first, then two multi-attack
        # Fighter allies (Extra Attack = 2 swings each), then the
        # target. Each Fighter's 2 swings at advantage against the
        # prone target produces enough eHP to beat the 1d6 cost.
        # (Single-attack allies wouldn't be worth it — Trip is a
        # multi-attack-amplified party-coordination move.)
        attacker = _make_rogue("attacker", position=(0, 0))
        ally1 = _make_fighter_ally("ally1", position=(1, 1))
        ally2 = _make_fighter_ally("ally2", position=(0, 1))
        target = _make_target("target", position=(1, 0),
                                  size="medium", dex_save=-2)
        state = _make_state([attacker, ally1, ally2, target])
        # turn_order: attacker → ally1 → ally2 → target
        state.current_turn_idx = 0
        choice = pick_cunning_strike_effect(attacker, target, state)
        self.assertEqual(choice, "trip")

    def test_picks_withdraw_when_surrounded(self) -> None:
        # Rogue with 3 adjacent enemies (target + 2 more nearby).
        # Withdraw value scales with adjacent enemy DPR.
        attacker = _make_rogue(position=(0, 0))
        target = _make_target("t", position=(1, 0), size="huge",
                                 dex_save=10, con_save=10)
        # Two more adjacent enemies to amplify Withdraw value
        e2 = _make_target("e2", position=(0, 1), size="huge",
                            dex_save=10, con_save=10)
        e3 = _make_target("e3", position=(1, 1), size="huge",
                            dex_save=10, con_save=10)
        state = _make_state([attacker, target, e2, e3])
        choice = pick_cunning_strike_effect(attacker, target, state)
        self.assertEqual(choice, "withdraw")

    def test_l4_rogue_returns_none(self) -> None:
        attacker = _make_rogue(level=4, position=(0, 0))
        target = _make_target(position=(1, 0), size="medium",
                                 dex_save=-2)
        state = _make_state([attacker, target])
        choice = pick_cunning_strike_effect(attacker, target, state)
        self.assertIsNone(choice)


# ============================================================================
# Layer 7+8+9+10: effect application
# ============================================================================

class EffectApplicationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_trip_applies_prone_on_fail(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(1, 0), size="medium",
                                 dex_save=-10)   # guaranteed fail
        # Need content_registry for apply_condition to fire effects
        state = _make_state([attacker, target])
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": {"id": "a_rapier"}, "state": "hit",
            "had_advantage": True, "had_disadvantage": False,
        }
        rng = random.Random(1)
        result = apply_cunning_strike_effect("trip", attacker, target,
                                                  state, rng)
        self.assertEqual(result["outcome"], "fail")
        applied = [c["condition_id"]
                    for c in target.applied_conditions]
        self.assertIn("co_prone", applied)

    def test_trip_size_gate_blocks_huge(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(1, 0), size="huge",
                                 dex_save=-10)
        state = _make_state([attacker, target])
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": {"id": "a_rapier"}, "state": "hit",
            "had_advantage": True, "had_disadvantage": False,
        }
        rng = random.Random(1)
        result = apply_cunning_strike_effect("trip", attacker, target,
                                                  state, rng)
        self.assertEqual(result["outcome"], "no_effect_size_immune")

    def test_withdraw_sets_disengaging(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(1, 0))
        state = _make_state([attacker, target])
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": {"id": "a_rapier"}, "state": "hit",
            "had_advantage": True, "had_disadvantage": False,
        }
        rng = random.Random(1)
        result = apply_cunning_strike_effect("withdraw", attacker,
                                                  target, state, rng)
        self.assertEqual(result["outcome"], "applied")
        self.assertTrue(attacker.disengaging)

    def test_poison_applies_on_fail(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(1, 0), size="medium",
                                 con_save=-10)
        state = _make_state([attacker, target])
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": {"id": "a_rapier"}, "state": "hit",
            "had_advantage": True, "had_disadvantage": False,
        }
        rng = random.Random(1)
        result = apply_cunning_strike_effect("poison", attacker, target,
                                                  state, rng)
        self.assertEqual(result["outcome"], "fail")
        applied = [c["condition_id"]
                    for c in target.applied_conditions]
        self.assertIn("co_poisoned", applied)


# ============================================================================
# Layer 11+12: SA integration
# ============================================================================

class SneakAttackIntegrationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_sa_dice_reduced_when_cs_picks_effect(self) -> None:
        # Setup: L5 Rogue (3d6 SA) + 2 multi-attack Fighter allies
        # in initiative window before the prone target. CS picks
        # Trip (1d6 cost) → SA rolls 2d6. Multi-attack allies amplify
        # the value beyond the 3.5 cost threshold; single-attack
        # allies wouldn't be enough.
        attacker = _make_rogue(level=5, position=(0, 0))
        ally1 = _make_fighter_ally("ally1", position=(1, 1))
        ally2 = _make_fighter_ally("ally2", position=(0, 1))
        target = _make_target(position=(1, 0), size="medium",
                                 dex_save=-10)
        state = _make_state([attacker, ally1, ally2, target])
        state.current_turn_idx = 0
        _set_attack_context(state, attacker, target)
        rng = random.Random(1)
        attack_params = {"kind": "melee", "ability": "dex",
                           "finesse": True, "bonus": 7,
                           "reach_ft": 5}
        # Apply SA — CS heuristic should pick Trip
        total = try_apply_sneak_attack(attacker, target, state,
                                            attack_params, rng,
                                            is_crit=False)
        # Find the SA event
        sa_events = [e for e in state.event_log
                       if e.get("event") == "sneak_attack_applied"]
        self.assertEqual(len(sa_events), 1)
        sa = sa_events[0]
        # Dice count after CS cost: 3 - 1 = 2
        self.assertEqual(sa["dice_count"], 2)
        self.assertEqual(sa["cunning_strike"], "trip")
        self.assertEqual(sa["cunning_strike_cost_dice"], 1)
        # Total damage in range [2, 12] for 2d6
        self.assertGreaterEqual(total, 2)
        self.assertLessEqual(total, 12)

    def test_sa_full_dice_when_cs_skips(self) -> None:
        # L5 Rogue (3d6 SA), Huge target with high saves — CS
        # heuristic returns None; full 3d6 rolled.
        attacker = _make_rogue(level=5, position=(0, 0))
        target = _make_target(position=(15, 0), size="huge",
                                 dex_save=10, con_save=10)
        state = _make_state([attacker, target])
        _set_attack_context(state, attacker, target)
        rng = random.Random(1)
        attack_params = {"kind": "ranged", "ability": "dex",
                           "bonus": 7, "range_ft": 80}
        try_apply_sneak_attack(attacker, target, state,
                                  attack_params, rng, is_crit=False)
        sa = [e for e in state.event_log
                if e.get("event") == "sneak_attack_applied"][0]
        self.assertEqual(sa["dice_count"], 3)
        self.assertNotIn("cunning_strike", sa)

    def test_l4_rogue_full_dice_no_cs(self) -> None:
        # L4 Rogue (2d6 SA) doesn't have Cunning Strike yet
        attacker = _make_rogue(level=4, position=(0, 0))
        target = _make_target(position=(1, 0), size="medium",
                                 dex_save=-10)
        state = _make_state([attacker, target])
        _set_attack_context(state, attacker, target)
        rng = random.Random(1)
        attack_params = {"kind": "melee", "ability": "dex",
                           "finesse": True, "bonus": 6,
                           "reach_ft": 5}
        try_apply_sneak_attack(attacker, target, state,
                                  attack_params, rng, is_crit=False)
        sa = [e for e in state.event_log
                if e.get("event") == "sneak_attack_applied"][0]
        self.assertEqual(sa["dice_count"], 2)
        self.assertNotIn("cunning_strike", sa)


# ============================================================================
# Layer 14: YAML wiring
# ============================================================================

class FeatureYamlTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_cunning_strike_loads(self) -> None:
        feature = self.registry.get("feature", "f_cunning_strike")
        self.assertEqual(feature["granted_by"]["class"], "c_rogue")
        self.assertEqual(feature["granted_by"]["level"], 5)

    def test_c_rogue_l5_has_cunning_strike(self) -> None:
        rogue = self.registry.get("class", "c_rogue")
        # Walk the level_table for L5 row
        l5_row = next(r for r in rogue["level_table"]
                          if r["level"] == 5)
        self.assertIn("f_cunning_strike", l5_row["features"])

    def test_min_rogue_level_constant(self) -> None:
        self.assertEqual(MIN_ROGUE_LEVEL, 5)


if __name__ == "__main__":
    unittest.main()
