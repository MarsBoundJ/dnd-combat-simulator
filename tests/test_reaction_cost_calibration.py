"""REACTION_SLOT_BASE_COSTS calibration tests (PR #67).

Pins the calibrated base values from PR #67. Future tweaks to the
calibration (e.g., when more Treantmonk videos process) MUST also
update these tests — that's the desired coupling so changes are
intentional and reviewable.

Also covers downstream behavioral effects:
  - L1 spell-slot reactions (Shield / Hellish Rebuke) only fire on
    high-DPR attackers in mid-day setups (cost 10 > weak-attacker
    DPR), but still fire on monsters with meaningful DPR.
  - Counterspell vs L3 spell roughly breaks even (cost 28 ≈ value
    28) — fires when slot scarcity is low, skips when scarce + many
    encounters remain.
  - L9 base cost (100) makes the highest-level slots expensive
    enough to reserve for emergencies.
"""
from __future__ import annotations

import unittest

from engine.ai.reaction_scoring import (
    counterspell_value_ehp, hellish_rebuke_value_ehp, shield_value_ehp,
)
from engine.core.feature_pacing import (
    REACTION_SLOT_BASE_COSTS, reaction_cost_ehp,
)
from engine.core.state import Actor


# ============================================================================
# Pinned calibrated values
# ============================================================================

class CalibratedValuesTest(unittest.TestCase):
    """If any of these change, the rationale block in
    feature_pacing.REACTION_SLOT_BASE_COSTS must also be updated."""

    def test_l1_base(self) -> None:
        # Magic Missile ≈ 10.5 dmg auto-hit; Shield blocks 10-15;
        # Healing Word ≈ 7 hp
        self.assertEqual(REACTION_SLOT_BASE_COSTS[1], 10.0)

    def test_l2_base(self) -> None:
        # Scorching Ray ~12.6; Hold Person ~30+ over duration
        self.assertEqual(REACTION_SLOT_BASE_COSTS[2], 15.0)

    def test_l3_base(self) -> None:
        # Fireball 28 × multi-target; Counterspell; Hypnotic Pattern
        self.assertEqual(REACTION_SLOT_BASE_COSTS[3], 28.0)

    def test_l4_base(self) -> None:
        # Polymorph; Ice Storm; Wall of Fire
        self.assertEqual(REACTION_SLOT_BASE_COSTS[4], 38.0)

    def test_l5_base(self) -> None:
        # Wall of Force; Hold Monster; Animate Objects
        self.assertEqual(REACTION_SLOT_BASE_COSTS[5], 50.0)

    def test_l6_base(self) -> None:
        # Disintegrate (75 nuke); Chain Lightning; Heal
        self.assertEqual(REACTION_SLOT_BASE_COSTS[6], 65.0)

    def test_l7_base(self) -> None:
        # Finger of Death; Forcecage; Plane Shift
        self.assertEqual(REACTION_SLOT_BASE_COSTS[7], 75.0)

    def test_l8_base(self) -> None:
        # Power Word Stun; Sunburst; Maze
        self.assertEqual(REACTION_SLOT_BASE_COSTS[8], 85.0)

    def test_l9_base(self) -> None:
        # Wish; Meteor Swarm; Time Stop; Power Word Kill
        self.assertEqual(REACTION_SLOT_BASE_COSTS[9], 100.0)

    def test_monotonically_non_decreasing(self) -> None:
        """Sanity: higher slots cost at least as much as lower ones."""
        levels = sorted(REACTION_SLOT_BASE_COSTS.keys())
        for prev, curr in zip(levels, levels[1:]):
            self.assertGreaterEqual(
                REACTION_SLOT_BASE_COSTS[curr],
                REACTION_SLOT_BASE_COSTS[prev],
                msg=f"L{curr} cost should be ≥ L{prev}")

    def test_no_huge_jumps(self) -> None:
        """Sanity: no slot-level should cost more than 2× the previous.
        Catches a calibration typo (e.g., L4=100 when meant L4=10)."""
        levels = sorted(REACTION_SLOT_BASE_COSTS.keys())
        for prev, curr in zip(levels, levels[1:]):
            ratio = REACTION_SLOT_BASE_COSTS[curr] / REACTION_SLOT_BASE_COSTS[prev]
            self.assertLessEqual(
                ratio, 2.0,
                msg=f"L{prev}→L{curr} ratio {ratio:.2f} exceeds 2.0")


# ============================================================================
# Downstream behavioral effects
# ============================================================================

def _attacker_with_dpr(dpr: int) -> Actor:
    """Build an attacker with a single weapon attack whose expected
    damage matches the given dpr value (modifier-only for simplicity).
    """
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    actions = [{
        "id": "a_attack", "name": "attack",
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 0, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "", "modifier": dpr,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }]
    template = {"id": "tpl_a", "name": "a",
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": actions}
    return Actor(id="a", name="a", template=template, side="enemy",
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities)


class ShieldFiringThresholdTest(unittest.TestCase):
    """Calibration check: Shield should fire on high-DPR attackers
    in mid-day setups, skip on weak attackers."""

    def _cost(self, slots=1, encounters=3):
        return reaction_cost_ehp(1, slots, encounters)

    def test_shield_skips_low_dpr_attacker_mid_day(self) -> None:
        # 1 slot, 3 encounters → cost 10
        # Attacker DPR 5 < 10 → skip
        cost = self._cost(slots=1, encounters=3)
        attacker = _attacker_with_dpr(5)
        value = shield_value_ehp({}, {"actor": attacker}, None, None)
        self.assertLess(value, cost)

    def test_shield_fires_high_dpr_attacker_mid_day(self) -> None:
        # 1 slot, 3 encounters → cost 10
        # Ogre-like DPR 12 > 10 → fires
        cost = self._cost(slots=1, encounters=3)
        attacker = _attacker_with_dpr(12)
        value = shield_value_ehp({}, {"actor": attacker}, None, None)
        self.assertGreater(value, cost)

    def test_shield_fires_low_dpr_attacker_last_encounter(self) -> None:
        # 1 slot, 1 encounter → cost 10 * 1 * 1/3 ≈ 3.3
        # Even a 5-DPR attacker beats it
        cost = self._cost(slots=1, encounters=1)
        attacker = _attacker_with_dpr(5)
        value = shield_value_ehp({}, {"actor": attacker}, None, None)
        self.assertGreater(value, cost)


class CounterspellFiringThresholdTest(unittest.TestCase):
    """Counterspell value scales with target spell's slot level.
    Confirms calibration makes CS selective."""

    def _cost(self, slots=1, encounters=3):
        return reaction_cost_ehp(3, slots, encounters)

    def test_cs_breaks_even_vs_same_level_spell(self) -> None:
        # Counterspell (L3 slot) vs L3 spell:
        # cost = 28 * 1/1 * 3/3 = 28
        # value = REACTION_SLOT_BASE_COSTS[3] = 28
        # Equal → fires (cost > value is False)
        cost = self._cost(slots=1, encounters=3)
        value = counterspell_value_ehp({}, {"spell_slot_level": 3},
                                            None, None)
        self.assertEqual(value, cost)

    def test_cs_skips_vs_lower_level_spell(self) -> None:
        # CS vs L1 spell: value 10 < cost 28 → skip
        cost = self._cost(slots=1, encounters=3)
        value = counterspell_value_ehp({}, {"spell_slot_level": 1},
                                            None, None)
        self.assertLess(value, cost)

    def test_cs_fires_vs_higher_level_spell(self) -> None:
        # CS vs L7 spell: value 75 >> cost 28 → fires
        cost = self._cost(slots=1, encounters=3)
        value = counterspell_value_ehp({}, {"spell_slot_level": 7},
                                            None, None)
        self.assertGreater(value, cost)


class HellishRebukeFiringThresholdTest(unittest.TestCase):
    """Hellish Rebuke is value ~8.25 (2d10 with 50% save) — should
    skip in mid-day setups, fire when slot abundant or last
    encounter."""

    def _cost(self, slots=1, encounters=3):
        return reaction_cost_ehp(1, slots, encounters)

    def test_hr_skips_mid_day_single_slot(self) -> None:
        # cost 10, value ~8.25 → skip
        cost = self._cost(slots=1, encounters=3)
        attacker = _attacker_with_dpr(10)
        value = hellish_rebuke_value_ehp({}, {"attacker": attacker},
                                              None, None)
        self.assertLess(value, cost)

    def test_hr_fires_with_abundant_slots(self) -> None:
        # 4 slots → cost 10 * 1/4 * 3/3 = 2.5; value 8.25 → fires
        cost = self._cost(slots=4, encounters=3)
        attacker = _attacker_with_dpr(10)
        value = hellish_rebuke_value_ehp({}, {"attacker": attacker},
                                              None, None)
        self.assertGreater(value, cost)

    def test_hr_fires_last_encounter(self) -> None:
        # 1 slot, 1 encounter → cost 3.3; value 8.25 → fires
        cost = self._cost(slots=1, encounters=1)
        attacker = _attacker_with_dpr(10)
        value = hellish_rebuke_value_ehp({}, {"attacker": attacker},
                                              None, None)
        self.assertGreater(value, cost)


if __name__ == "__main__":
    unittest.main()
