"""Shapley eHP attribution (engine/core/attribution.py).

The red-team consensus design: the attacker keeps the attack's BASELINE
expected value; every temporary modifier (advantage from a condition, Bless's
attack bonus) is a contributor credited with its exact Shapley share of the
surplus; realized damage splits proportionally so credited amounts sum exactly
to what happened.

Layers:
  1. d20 probability math (normal / advantage / disadvantage, nat-1/20 clamps)
  2. Shapley properties on the attack value function:
     efficiency (baseline + Σφ = v(N)), symmetry (equal effects equal credit),
     dummy (no-op contributor gets 0), and a hand-computed advantage+Bless case
  3. Realized scaling: shares sum exactly to the damage amount; miss → nothing
  4. Engine integration: a Blessed attack's damage_dealt event carries an
     attribution payload crediting the Bless caster
  5. Condition path: advantage sourced by a Restrained-style modifier credits
     the creature that applied the condition (the Web caster)
  6. Ledger: enablement_ehp / enabled_by_others routing + the closed-ledger
     identity (Σ attributed_offense per side == Σ damage_dealt per side)

Run via:
    python -m unittest tests.test_attribution
"""
from __future__ import annotations

import unittest

import engine.primitives as primitives_module
from engine.core.attribution import (
    attribute_damage_event, build_attack_context, crit_probability,
    dice_mean, expected_attack_value, group_contributions, hit_probability,
    shapley_shares,
)
from engine.core.combat_metrics import build_contribution_ledger
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _attack_roll, _damage


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=50, ac=10):
    abilities = {
        "str": {"score": 16, "save": 3},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _adv(source):
    return {"kind": "advantage", "value": 0, "source": source}


def _bonus(value, source):
    return {"kind": "attack_bonus", "value": value, "source": source}


_BLESS_SRC = {"type": "action_buff", "action_id": "a_bless",
              "caster_id": "cleric", "named_effect": "bless"}
_WEB_SRC = {"type": "condition", "condition_id": "co_restrained",
            "source_creature_id": "wizard"}


# ============================================================================
# Layer 1: probability math
# ============================================================================

class HitProbabilityTest(unittest.TestCase):
    def test_normal(self):
        # need 11+ on the d20 → 10 of 20 faces
        self.assertAlmostEqual(hit_probability(11), 0.5)

    def test_advantage(self):
        self.assertAlmostEqual(hit_probability(11, "advantage"), 0.75)

    def test_disadvantage(self):
        self.assertAlmostEqual(hit_probability(11, "disadvantage"), 0.25)

    def test_nat_20_always_hits(self):
        # Even vs an impossible threshold, nat 20 lands.
        self.assertAlmostEqual(hit_probability(35), 0.05)

    def test_nat_1_always_misses(self):
        # Even vs a trivial threshold, nat 1 whiffs.
        self.assertAlmostEqual(hit_probability(-10), 0.95)

    def test_crit_probability_advantage(self):
        # P(at least one nat 20 of two) = 1 − 0.95² = 0.0975
        self.assertAlmostEqual(crit_probability(20, "advantage"), 0.0975)

    def test_dice_mean(self):
        self.assertAlmostEqual(dice_mean("2d6"), 7.0)
        self.assertAlmostEqual(dice_mean("1d10"), 5.5)
        self.assertAlmostEqual(dice_mean(""), 0.0)
        self.assertAlmostEqual(dice_mean(None), 0.0)


# ============================================================================
# Layer 2: Shapley properties
# ============================================================================

def _value_fn_factory(base_bonus, base_ac):
    def value_fn(effects):
        return expected_attack_value(base_bonus, base_ac, effects,
                                     crit_threshold=20, crit_extra_ratio=0.0)
    return value_fn


class ShapleyPropertyTest(unittest.TestCase):
    def test_efficiency(self):
        """baseline + Σφ equals the full-coalition value exactly."""
        contributors, _ = group_contributions(
            [_adv(_WEB_SRC), _bonus(2, _BLESS_SRC)])
        value_fn = _value_fn_factory(base_bonus=5, base_ac=16)
        baseline, phis = shapley_shares(contributors, value_fn)
        full = value_fn([e for c in contributors for e in c["effects"]])
        self.assertAlmostEqual(baseline + sum(phis), full)

    def test_symmetry(self):
        """Two identical +2 bonuses from different casters get equal credit."""
        src_a = {"type": "action_buff", "action_id": "a_buff_a",
                 "caster_id": "caster_a"}
        src_b = {"type": "action_buff", "action_id": "a_buff_b",
                 "caster_id": "caster_b"}
        contributors, _ = group_contributions(
            [_bonus(2, src_a), _bonus(2, src_b)])
        _, phis = shapley_shares(
            contributors, _value_fn_factory(base_bonus=5, base_ac=16))
        self.assertAlmostEqual(phis[0], phis[1])
        self.assertGreater(phis[0], 0)

    def test_dummy(self):
        """A zero-value contributor earns zero credit."""
        contributors, _ = group_contributions(
            [_bonus(0, _BLESS_SRC), _adv(_WEB_SRC)])
        _, phis = shapley_shares(
            contributors, _value_fn_factory(base_bonus=5, base_ac=16))
        by_id = {c["source_id"]: p for c, p in
                 zip(contributors, phis)}
        self.assertAlmostEqual(by_id["cleric"], 0.0)
        self.assertGreater(by_id["wizard"], 0.0)

    def test_hand_computed_advantage_plus_bless(self):
        """Baseline needs 11 (p=.5). Advantage→.75, +2→.6, both→.84.
        φ_adv = ½[(.75−.5)+(.84−.6)] = .245
        φ_bless = ½[(.6−.5)+(.84−.75)] = .095"""
        contributors, _ = group_contributions(
            [_adv(_WEB_SRC), _bonus(2, _BLESS_SRC)])
        baseline, phis = shapley_shares(
            contributors, _value_fn_factory(base_bonus=5, base_ac=16))
        by_id = {c["source_id"]: p for c, p in zip(contributors, phis)}
        self.assertAlmostEqual(baseline, 0.5)
        self.assertAlmostEqual(by_id["wizard"], 0.245)
        self.assertAlmostEqual(by_id["cleric"], 0.095)

    def test_advantage_disadvantage_cancellation(self):
        """5e cancellation is honored inside coalitions: with the enemy's
        disadvantage ambient-active, an advantage source's value is the
        RESTORATION to normal, not a lift to full advantage."""
        contributors, _ = group_contributions([_adv(_WEB_SRC)])

        def value_fn(effects):
            # Base disadvantage (e.g., attacker poisoned, unattributable)
            return expected_attack_value(5, 16, effects,
                                         base_disadvantage=1)
        baseline, phis = shapley_shares(contributors, value_fn)
        self.assertAlmostEqual(baseline, 0.25)       # disadvantage
        self.assertAlmostEqual(baseline + phis[0], 0.5)   # canceled → normal

    def test_grouping_one_share_per_creature(self):
        """Two modifiers from ONE caster merge into one composite contributor
        (a creature's credit covers everything it contributed)."""
        contributors, ambient = group_contributions([
            _bonus(2, _BLESS_SRC),
            _adv({"type": "condition", "condition_id": "co_prone",
                  "source_creature_id": "cleric"}),
        ])
        self.assertEqual(len(contributors), 1)
        self.assertEqual(contributors[0]["source_id"], "cleric")
        self.assertEqual(len(contributors[0]["effects"]), 2)
        self.assertEqual(ambient, [])

    def test_sourceless_contribution_is_ambient(self):
        contributors, ambient = group_contributions(
            [_adv({"type": "terrain"})])
        self.assertEqual(contributors, [])
        self.assertEqual(len(ambient), 1)


# ============================================================================
# Layer 3: realized scaling
# ============================================================================

class RealizedScalingTest(unittest.TestCase):
    def _ctx(self):
        return build_attack_context(
            [_adv(_WEB_SRC), _bonus(2, _BLESS_SRC)],
            base_bonus=5, base_ac=16, crit_threshold=20,
            attacker_id="fighter")

    def test_shares_sum_to_realized_amount(self):
        attr = attribute_damage_event(self._ctx(), 17.0)
        total = attr["baseline"] + sum(s["amount"] for s in attr["shares"])
        self.assertAlmostEqual(total, 17.0)

    def test_share_proportions_match_expected_values(self):
        # From the hand-computed case: fractions .5/.84, .245/.84, .095/.84
        attr = attribute_damage_event(self._ctx(), 84.0)
        by_id = {s["source_id"]: s["amount"] for s in attr["shares"]}
        self.assertAlmostEqual(attr["baseline"], 50.0)
        self.assertAlmostEqual(by_id["wizard"], 24.5)
        self.assertAlmostEqual(by_id["cleric"], 9.5)

    def test_zero_amount_attributes_nothing(self):
        self.assertIsNone(attribute_damage_event(self._ctx(), 0.0))

    def test_no_contributors_no_context(self):
        ctx = build_attack_context([], base_bonus=5, base_ac=16,
                                   crit_threshold=20, attacker_id="fighter")
        self.assertIsNone(ctx)

    def test_nearly_impossible_without_help_goes_to_contributors(self):
        """When the baseline only hits on a nat 20 (p=.05) and the buff makes
        it near-automatic (p=.95), the enabler owns the lion's share."""
        ctx = build_attack_context(
            [_bonus(30, _BLESS_SRC)],
            base_bonus=0, base_ac=30, crit_threshold=20,
            attacker_id="fighter")
        attr = attribute_damage_event(ctx, 10.0)
        # baseline frac = .05/.95, cleric frac = .90/.95
        total = attr["baseline"] + sum(s["amount"] for s in attr["shares"])
        self.assertAlmostEqual(total, 10.0)
        self.assertAlmostEqual(attr["baseline"], 10.0 * 0.05 / 0.95)
        self.assertGreater(
            sum(s["amount"] for s in attr["shares"]), attr["baseline"])


# ============================================================================
# Layer 4: engine integration — a Blessed attack
# ============================================================================

class EngineIntegrationTest(unittest.TestCase):
    def _run_attack(self, attacker, target, state):
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": {"id": "a_test_swing"},
        }
        bus = EventBus()
        result = _attack_roll({"bonus": 5, "reach_ft": 5}, state, bus)
        if result.get("state") in ("hit", "crit"):
            _damage({"dice": "2d6", "modifier": 3, "type": "slashing"},
                    state, bus)
        return result

    def test_blessed_attack_carries_attribution(self):
        # AC 19 so Bless's +2 has REAL marginal value (vs a trivial AC the
        # dummy property would correctly zero it out).
        fighter = _make_actor("fighter", ac=18)
        cleric = _make_actor("cleric", position=(1, 0))
        dragon = _make_actor("dragon", side="enemy", ac=19, position=(0, 1),
                             hp=2000)
        state = _make_state([fighter, cleric, dragon])
        # Bless-shape modifier on the fighter, sourced by the cleric.
        fighter.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"when": "attacker_is_self",
                       "modifier": "attack_bonus", "value": 2},
            "lifetime": "until_short_rest",
            "source": dict(_BLESS_SRC),
            "applied_at_round": 1,
            "owner_id": "fighter",
        })
        # p(hit) ≈ .45 per swing; retry until one lands.
        for _ in range(200):
            result = self._run_attack(fighter, dragon, state)
            if result.get("state") in ("hit", "crit"):
                break
        dmg_events = [e for e in state.event_log
                      if e.get("event") == "damage_dealt"]
        self.assertTrue(dmg_events)
        attr = dmg_events[-1].get("attribution")
        self.assertIsNotNone(attr)
        self.assertEqual(attr["model"], "shapley_v1")
        by_id = {s["source_id"]: s for s in attr["shares"]}
        self.assertIn("cleric", by_id)
        self.assertGreater(by_id["cleric"]["amount"], 0)
        self.assertIn("bless", by_id["cleric"]["labels"])
        total = attr["baseline"] + sum(s["amount"] for s in attr["shares"])
        self.assertAlmostEqual(total, dmg_events[-1]["amount"], places=5)

    def test_plain_attack_carries_no_attribution(self):
        fighter = _make_actor("fighter", ac=18)
        dragon = _make_actor("dragon", side="enemy", ac=10, position=(0, 1),
                             hp=2000)
        state = _make_state([fighter, dragon])
        for _ in range(200):
            result = self._run_attack(fighter, dragon, state)
            if result.get("state") in ("hit", "crit"):
                break
        dmg_events = [e for e in state.event_log
                      if e.get("event") == "damage_dealt"]
        self.assertTrue(dmg_events)
        self.assertNotIn("attribution", dmg_events[-1])

    def test_restrained_target_credits_web_caster(self):
        """Advantage from a Restrained-style condition (applied by the wizard)
        credits the WIZARD with a share of the fighter's damage."""
        fighter = _make_actor("fighter", ac=18)
        wizard = _make_actor("wizard", position=(2, 0))
        dragon = _make_actor("dragon", side="enemy", ac=19, position=(0, 1),
                             hp=2000)
        state = _make_state([fighter, wizard, dragon])
        # Restrained's attacks-vs-you-advantage modifier ON the dragon,
        # sourced by the wizard (the co_restrained effect shape).
        dragon.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"when": "target_is_self",
                       "modifier": "advantage_for_attacker"},
            "lifetime": "until_condition_ends",
            "source": dict(_WEB_SRC),
            "applied_at_round": 1,
            "owner_id": "dragon",
        })
        for _ in range(200):
            result = self._run_attack(fighter, dragon, state)
            if result.get("state") in ("hit", "crit"):
                break
        dmg_events = [e for e in state.event_log
                      if e.get("event") == "damage_dealt"]
        self.assertTrue(dmg_events)
        attr = dmg_events[-1].get("attribution")
        self.assertIsNotNone(attr)
        by_id = {s["source_id"]: s for s in attr["shares"]}
        self.assertIn("wizard", by_id)
        self.assertGreater(by_id["wizard"]["amount"], 0)
        self.assertIn("co_restrained", by_id["wizard"]["labels"])


# ============================================================================
# Layer 5: ledger routing + closed-ledger identity
# ============================================================================

class LedgerAttributionTest(unittest.TestCase):
    def _state_with_log(self, log):
        fighter = _make_actor("fighter")
        cleric = _make_actor("cleric")
        wizard = _make_actor("wizard")
        dragon = _make_actor("dragon", side="enemy", hp=200)
        state = _make_state([fighter, cleric, wizard, dragon])
        state.event_log = log
        return state

    def test_enablement_routed_to_allied_sources(self):
        log = [
            {"event": "turn_start", "round": 1, "actor": "fighter"},
            {"event": "damage_dealt", "actor": "fighter", "target": "dragon",
             "amount": 20.0, "type": "slashing",
             "attribution": {
                 "model": "shapley_v1", "baseline": 12.0,
                 "shares": [
                     {"source_id": "cleric", "labels": ["bless"],
                      "amount": 3.0},
                     {"source_id": "wizard", "labels": ["co_restrained"],
                      "amount": 5.0},
                 ]}},
        ]
        led = build_contribution_ledger(self._state_with_log(log))
        pa = led["per_actor"]
        self.assertAlmostEqual(pa["fighter"]["damage_dealt"], 20.0)
        self.assertAlmostEqual(pa["fighter"]["enabled_by_others"], 8.0)
        self.assertAlmostEqual(pa["fighter"]["attributed_offense"], 12.0)
        self.assertAlmostEqual(pa["cleric"]["enablement_ehp"], 3.0)
        self.assertAlmostEqual(pa["cleric"]["attributed_offense"], 3.0)
        self.assertAlmostEqual(pa["wizard"]["enablement_ehp"], 5.0)

    def test_self_and_enemy_shares_stay_with_executor(self):
        log = [
            {"event": "turn_start", "round": 1, "actor": "fighter"},
            {"event": "damage_dealt", "actor": "fighter", "target": "dragon",
             "amount": 20.0, "type": "slashing",
             "attribution": {
                 "model": "shapley_v1", "baseline": 10.0,
                 "shares": [
                     # Reckless self-advantage: folds back to the fighter.
                     {"source_id": "fighter", "labels": ["reckless_attack"],
                      "amount": 6.0},
                     # The target's own exposure: enemy-side, stays put.
                     {"source_id": "dragon", "labels": ["reckless_attack"],
                      "amount": 4.0},
                 ]}},
        ]
        led = build_contribution_ledger(self._state_with_log(log))
        pa = led["per_actor"]
        self.assertAlmostEqual(pa["fighter"]["enabled_by_others"], 0.0)
        self.assertAlmostEqual(pa["fighter"]["attributed_offense"], 20.0)
        self.assertAlmostEqual(pa["dragon"]["enablement_ehp"], 0.0)

    def test_closed_ledger_identity(self):
        """Σ attributed_offense over a side == Σ damage_dealt over the side —
        attribution moves credit around, never creates or destroys it."""
        log = [
            {"event": "turn_start", "round": 1, "actor": "fighter"},
            {"event": "damage_dealt", "actor": "fighter", "target": "dragon",
             "amount": 20.0, "type": "slashing",
             "attribution": {
                 "model": "shapley_v1", "baseline": 12.0,
                 "shares": [{"source_id": "cleric", "labels": ["bless"],
                             "amount": 8.0}]}},
            {"event": "turn_start", "round": 1, "actor": "wizard"},
            {"event": "damage_dealt", "actor": "wizard", "target": "dragon",
             "amount": 31.0, "type": "force"},
            {"event": "turn_start", "round": 1, "actor": "dragon"},
            {"event": "damage_dealt", "actor": "dragon", "target": "fighter",
             "amount": 26.0, "type": "fire"},
        ]
        led = build_contribution_ledger(self._state_with_log(log))
        pa = led["per_actor"]
        pc_dealt = sum(r["damage_dealt"] for r in pa.values()
                       if r["side"] == "pc")
        pc_attributed = sum(r["attributed_offense"] for r in pa.values()
                            if r["side"] == "pc")
        self.assertAlmostEqual(pc_dealt, pc_attributed)
        self.assertAlmostEqual(pc_dealt, 51.0)


if __name__ == "__main__":
    unittest.main()
