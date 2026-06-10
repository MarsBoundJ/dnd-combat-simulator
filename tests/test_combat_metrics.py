"""Combat contribution ledger (engine/core/combat_metrics.py).

Pure event-log parser: per-actor damage dealt/taken, real attacks vs
out-of-range auto-misses (the reach-failure signal), heal eHP (attributed to
the turn's actor), and control eHP (denied enemy DPR x denial fraction,
reformed: target-aware AC + lifetime cap).

Run via:
    python -m unittest tests.test_combat_metrics
"""
from __future__ import annotations

import unittest

from engine.core.combat_metrics import (
    build_contribution_ledger, classify_diff,
)
from engine.core.state import Actor, Encounter, CombatState


def _actor(actor_id, side, actions=None, ac=14, hp_max=40):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "cr": {"proficiency_bonus": 2},
                           "actions": actions or []},
                 side=side, hp_current=hp_max, hp_max=hp_max, ac=ac,
                 position=(0, 0), abilities=ab)


# An enemy with a weapon_attack so estimate_dpr() > 0 (for control eHP).
# bonus +6, damage 2d6+3 (mean 10).
_ENEMY_ATTACK = {"id": "a_claw", "type": "weapon_attack", "reach_ft": 5,
                 "pipeline": [{"primitive": "attack_roll",
                               "params": {"bonus": 6}},
                              {"primitive": "damage",
                               "params": {"dice": "2d6", "modifier": 3,
                                          "type": "slashing"}}]}


def _ledger_for(events, pc_ac=14, foe_hp=40):
    pc = _actor("pc", "pc", ac=pc_ac)
    ally = _actor("ally", "pc", ac=pc_ac)
    foe = _actor("foe", "enemy", actions=[_ENEMY_ATTACK], hp_max=foe_hp)
    st = CombatState(encounter=Encounter(id="t", actors=[pc, ally, foe]))
    st.event_log = events
    return build_contribution_ledger(st), foe


class LedgerParseTest(unittest.TestCase):

    def test_damage_and_attacks_and_oor(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "attack_roll", "actor": "pc", "target": "foe",
             "d20": 15, "result": "hit"},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 20},
            {"event": "attack_roll", "actor": "pc", "target": "foe",
             "d20": 4, "result": "miss"},
            # out-of-range auto-miss (no d20):
            {"event": "attack_roll", "actor": "pc", "target": "foe",
             "result": "miss", "reason": "out_of_range"},
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 10},
        ]
        led, _ = _ledger_for(events)
        pc = led["per_actor"]["pc"]
        self.assertEqual(pc["damage_dealt"], 20)
        self.assertEqual(pc["attacks"], 2)        # two real rolls
        self.assertEqual(pc["hits"], 1)
        self.assertEqual(pc["auto_misses"], 1)    # the out-of-range one
        self.assertEqual(pc["damage_taken"], 10)
        self.assertEqual(led["per_actor"]["foe"]["damage_dealt"], 10)

    def test_heal_attributed_to_turn_actor(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "healed", "target": "ally", "amount": 12},
        ]
        led, _ = _ledger_for(events)
        self.assertEqual(led["per_actor"]["pc"]["heal_ehp"], 12)

    def test_control_ehp_uses_party_ac(self):
        # Denial credit uses the party's average AC (14), not AC 15.
        # Foe: bonus +6, damage mean 10.
        # vs AC 14: needed = 8, p_hit = 13/20 = 0.65, DPR = 6.5
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_stunned"},
        ]
        led, foe = _ledger_for(events)
        from engine.ai.defensive_ehp import estimate_dpr_vs_ac
        expected = estimate_dpr_vs_ac(foe, 14)  # party AC = 14
        self.assertGreater(led["per_actor"]["pc"]["control_ehp"], 0)
        self.assertAlmostEqual(led["per_actor"]["pc"]["control_ehp"], expected)

    def test_partial_control_uses_fraction(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_prone"},     # partial control (0.3)
        ]
        led, foe = _ledger_for(events)
        from engine.ai.defensive_ehp import (
            estimate_dpr_vs_ac, PARTIAL_CONTROL_CONDITIONS,
        )
        expected = estimate_dpr_vs_ac(foe, 14) * PARTIAL_CONTROL_CONDITIONS["co_prone"]
        self.assertAlmostEqual(
            led["per_actor"]["pc"]["control_ehp"], expected)

    def test_friendly_fire_not_counted_cross_side(self):
        # damage from pc to ally (same side) is not credited as offense.
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "ally",
             "amount": 8},
        ]
        led, _ = _ledger_for(events)
        self.assertEqual(led["per_actor"].get("pc", {}).get("damage_dealt", 0), 0)

    def test_non_control_condition_scores_zero(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_blessed"},   # not a control condition
        ]
        led, _ = _ledger_for(events)
        self.assertEqual(led["per_actor"].get("pc", {}).get("control_ehp", 0), 0)


class DenialReformTest(unittest.TestCase):
    """Denial credit reform: target-aware AC + lifetime cap."""

    def test_higher_party_ac_reduces_denial(self):
        # Party AC 18 → foe needs 18-6=12, p_hit = 9/20 = 0.45, DPR = 4.5
        # Party AC 10 → foe needs 10-6=4, p_hit = 17/20 = 0.85, DPR = 8.5
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_stunned"},
        ]
        led_high, _ = _ledger_for(events, pc_ac=18)
        led_low, _ = _ledger_for(events, pc_ac=10)
        self.assertGreater(led_low["per_actor"]["pc"]["control_ehp"],
                           led_high["per_actor"]["pc"]["control_ehp"])

    def test_lifetime_cap_near_death(self):
        # Foe hp_max=40. Deal 36 damage in round 1, then stun in round 2.
        # At condition time: cur_round=2, total_dmg=36, hp_rem=4.
        # incoming_dpr = 36/2 = 18. remaining = 4/18 ≈ 0.222.
        # Full DPR vs AC 14 = 6.5. Capped = 6.5 * 0.222 ≈ 1.44.
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 36},
            {"event": "turn_start", "actor": "pc", "round": 2},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_stunned"},
        ]
        led, foe = _ledger_for(events, foe_hp=40)
        from engine.ai.defensive_ehp import estimate_dpr_vs_ac
        full_denied = estimate_dpr_vs_ac(foe, 14)
        credit = led["per_actor"]["pc"]["control_ehp"]
        # lifetime_factor ≈ 0.222 — credit is ~22% of uncapped
        self.assertLess(credit, full_denied * 0.25)
        self.assertGreater(credit, 0)

    def test_no_lifetime_cap_early_combat(self):
        # No damage dealt yet → lifetime_factor = 1.0 (no data to cap with).
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_stunned"},
        ]
        led, foe = _ledger_for(events)
        from engine.ai.defensive_ehp import estimate_dpr_vs_ac
        expected = estimate_dpr_vs_ac(foe, 14)
        self.assertAlmostEqual(
            led["per_actor"]["pc"]["control_ehp"], expected)

    def test_lifetime_cap_half_dead(self):
        # Foe hp_max=100. Deal 50 damage in round 1, stun in round 2.
        # hp_remaining = 50. incoming_dpr = 50/1 = 50.
        # remaining_rounds = 50/50 = 1.0. lifetime_factor = 1.0.
        # At exactly half health with 1-round DPR matching remaining HP,
        # no cap applies.
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 50},
            {"event": "turn_start", "actor": "pc", "round": 2},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_stunned"},
        ]
        led, foe = _ledger_for(events, foe_hp=100)
        from engine.ai.defensive_ehp import estimate_dpr_vs_ac
        expected = estimate_dpr_vs_ac(foe, 14)
        self.assertAlmostEqual(
            led["per_actor"]["pc"]["control_ehp"], expected)

    def test_lifetime_cap_overkill_floor(self):
        # Foe hp_max=40. Deal 39 damage over 1 round, stun in round 2.
        # hp_remaining = max(1, 40-39) = 1. incoming_dpr = 39/2 = 19.5.
        # remaining_rounds = 1/19.5 ≈ 0.051. lifetime_factor ≈ 0.051.
        # Credit ≈ 6.5 * 0.051 ≈ 0.33 — nearly zero.
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 39},
            {"event": "turn_start", "actor": "pc", "round": 2},
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_stunned"},
        ]
        led, foe = _ledger_for(events, foe_hp=40)
        from engine.ai.defensive_ehp import estimate_dpr_vs_ac
        full_denied = estimate_dpr_vs_ac(foe, 14)
        credit = led["per_actor"]["pc"]["control_ehp"]
        # lifetime_factor ≈ 0.051 — credit is ~5% of uncapped
        self.assertLess(credit, full_denied * 0.1)
        self.assertGreater(credit, 0)


class DiffMetricTest(unittest.TestCase):
    """Empirical Dunn d_iff = gross damage PCs took / party total max HP."""

    def test_diff_is_damage_taken_over_party_hp(self):
        # 2 PCs at hp_max 40 → party HP 80. Foe deals 24 to pc → d_iff 0.30.
        events = [
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 24},
        ]
        led, _ = _ledger_for(events)
        self.assertEqual(led["pc_total_hp"], 80)
        self.assertEqual(led["pc_damage_taken"], 24)
        self.assertAlmostEqual(led["d_iff"], 24 / 80)         # 0.30
        self.assertEqual(led["difficulty_band"], "Medium")    # 0.30 → Medium

    def test_diff_spreads_across_pcs(self):
        events = [
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 20},
            {"event": "damage_dealt", "actor": "foe", "target": "ally",
             "amount": 16},
        ]
        led, _ = _ledger_for(events)
        self.assertAlmostEqual(led["d_iff"], 36 / 80)         # 0.45
        self.assertEqual(led["difficulty_band"], "Hard")      # 0.45 → Hard

    def test_overkill_above_party_hp_is_tpk_band(self):
        events = [
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 50},
            {"event": "damage_dealt", "actor": "foe", "target": "ally",
             "amount": 40},
        ]
        led, _ = _ledger_for(events)
        self.assertGreaterEqual(led["d_iff"], 1.0)            # 90/80
        self.assertEqual(led["difficulty_band"], "TPK")

    def test_classify_diff_bands(self):
        self.assertEqual(classify_diff(0.0), "Trivial")
        self.assertEqual(classify_diff(0.14), "Trivial")
        self.assertEqual(classify_diff(0.15), "Easy")
        self.assertEqual(classify_diff(0.30), "Medium")
        self.assertEqual(classify_diff(0.45), "Hard")
        self.assertEqual(classify_diff(0.70), "Deadly")
        self.assertEqual(classify_diff(1.0), "TPK")
        self.assertEqual(classify_diff(2.5), "TPK")


if __name__ == "__main__":
    unittest.main()
