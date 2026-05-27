"""Cleave reach passthrough tests (PR #66).

Layers:
  1. _build_weapon_action bakes reach_ft into mastery params
     - Default weapon (no explicit reach) → 5
     - Reach 10 weapon (glaive) → 10
     - Reach 15 weapon (whip variant) → 15
  2. _mastery_cleave honors the baked reach_ft for the attacker-
     reach constraint
     - 5 ft reach: second target out at 10 ft → no_second_target
     - 10 ft reach: same second target → fires (in reach)
     - The 5 ft primary-to-secondary distance is INVARIANT (does
       not scale with attacker reach)
     - 10 ft reach: secondary at 10 ft from primary → still
       no_second_target (RAW: secondary within 5 ft of primary)
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.core.weapon_masteries import apply_mastery_effects
from engine.pc_schema import _build_weapon_action


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  hp=30, weapon_masteries=None,
                  actions=None) -> Actor:
    abilities = {k: {"score": 14 if k == "str" else 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=14,
                  speed={"walk": 30}, position=position,
                  abilities=abilities,
                  weapon_masteries=list(weapon_masteries or []))


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _cleave_action(reach_ft=5):
    """A cleave-mastery weapon action with `reach_ft` baked into the
    attack_roll params and the mastery sub-dict (mimics what
    _build_weapon_action produces)."""
    return {
        "id": f"a_weapon_r{reach_ft}",
        "name": f"Weapon R{reach_ft}",
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 6,
                          "reach_ft": reach_ft,
                          "mastery": {
                              "id": "cleave", "ability_mod": 3,
                              "damage_type": "slashing",
                              "save_dc": 13,
                              "reach_ft": reach_ft,
                          }}},
            {"primitive": "damage",
              "params": {"dice": "2d6", "modifier": 3,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# Layer 1: _build_weapon_action bakes reach_ft into mastery params
# ============================================================================

class BuildWeaponActionReachTest(unittest.TestCase):

    def _build(self, weapon):
        return _build_weapon_action(
            weapon,
            ability_scores={"str": {"score": 16}, "dex": {"score": 14}},
            proficiency_bonus=2,
        )

    def test_default_reach_5_baked(self) -> None:
        weapon = {"id": "a_gs", "name": "Greatsword",
                    "attack_ability": "str", "damage_dice": "2d6",
                    "damage_type": "slashing", "reach_ft": 5,
                    "two_handed": True, "heavy": True,
                    "mastery": "cleave"}
        action = self._build(weapon)
        mastery = action["pipeline"][0]["params"]["mastery"]
        self.assertEqual(mastery["reach_ft"], 5)

    def test_reach_10_baked(self) -> None:
        # Glaive is heavy + two-handed + reach 10
        weapon = {"id": "a_glaive", "name": "Glaive",
                    "attack_ability": "str", "damage_dice": "1d10",
                    "damage_type": "slashing", "reach_ft": 10,
                    "two_handed": True, "heavy": True,
                    "mastery": "cleave"}
        action = self._build(weapon)
        mastery = action["pipeline"][0]["params"]["mastery"]
        self.assertEqual(mastery["reach_ft"], 10)

    def test_reach_omitted_defaults_to_5(self) -> None:
        # If the spec doesn't include reach_ft, _build_weapon_action
        # falls back to 5 (existing behavior for the attack_roll
        # reach param too).
        weapon = {"id": "a_gs", "name": "Greatsword",
                    "attack_ability": "str", "damage_dice": "2d6",
                    "damage_type": "slashing",
                    # no reach_ft
                    "two_handed": True, "heavy": True,
                    "mastery": "cleave"}
        action = self._build(weapon)
        mastery = action["pipeline"][0]["params"]["mastery"]
        self.assertEqual(mastery["reach_ft"], 5)


# ============================================================================
# Layer 2: _mastery_cleave honors reach_ft
# ============================================================================

class CleaveReachRuntimeTest(unittest.TestCase):

    def setUp(self) -> None:
        # Deterministic RNG for the sub-attack
        primitives_module.set_rng(random.Random(2))

    def _cleave_params(self, reach_ft=5):
        return {"id": "cleave", "ability_mod": 3,
                "damage_type": "slashing", "save_dc": 13,
                "reach_ft": reach_ft}

    def test_reach_5_misses_far_second_target(self) -> None:
        # Attacker at (0, 0); primary at (1, 0) (5 ft away, in reach);
        # candidate second target at (2, 0) — 10 ft from attacker,
        # but only 5 ft from primary. With reach=5, attacker can't
        # reach the second target.
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_action(5)],
                                  position=(0, 0))
        primary = _make_actor("p", side="enemy", position=(1, 0))
        second = _make_actor("s", side="enemy", position=(2, 0))
        state = _state_with([attacker, primary, second])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        apply_mastery_effects(self._cleave_params(reach_ft=5),
                                 attacker, primary, "hit", state)
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"
                    and e.get("mastery") == "cleave"]
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]["reason"], "no_second_target")

    def test_reach_10_hits_same_far_second_target(self) -> None:
        # Same setup as above, but attacker has reach 10. Now the
        # second target at (2, 0) IS in reach.
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_action(10)],
                                  position=(0, 0))
        primary = _make_actor("p", side="enemy", position=(1, 0))
        second = _make_actor("s", side="enemy", position=(2, 0))
        state = _state_with([attacker, primary, second])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        apply_mastery_effects(self._cleave_params(reach_ft=10),
                                 attacker, primary, "hit", state)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "cleave"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["second_target"], second.id)

    def test_5ft_primary_to_secondary_invariant_with_reach_10(self) -> None:
        # Reach 10 attacker still can't Cleave to a target that's
        # > 5 ft from primary. RAW: the 5 ft is between the two
        # targets, not from the attacker.
        # Attacker at (0, 0); primary at (1, 0); secondary at (3, 0)
        # — 10 ft from primary (too far), 15 ft from attacker (in
        # reach 10? Actually 15 ft is OUT of reach 10. Let me pick
        # better: secondary at (2, 1) = max(1, 1)=1 square from
        # primary = 5 ft. That's IN. Pick (3, 0) = 2 squares from
        # primary = 10 ft. That's OUT. And 3 squares from attacker
        # = 15 ft, also OUT.
        # Need a position 10+ ft from primary but in attacker reach 10.
        # Attacker at (0, 0); primary at (2, 0) = 10 ft (reach 10);
        # secondary at (2, 2) = max(0, 2)=2 squares from primary
        # = 10 ft, NOT within 5 ft of primary.
        # Secondary at (2, 2): from attacker = max(2, 2)=2 squares
        # = 10 ft (in attacker reach). From primary = max(0, 2)
        # = 10 ft. So secondary IS in attacker reach but NOT within
        # 5 ft of primary → should skip.
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_action(10)],
                                  position=(0, 0))
        primary = _make_actor("p", side="enemy", position=(2, 0))
        secondary = _make_actor("s", side="enemy", position=(2, 2))
        state = _state_with([attacker, primary, secondary])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        apply_mastery_effects(self._cleave_params(reach_ft=10),
                                 attacker, primary, "hit", state)
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"
                    and e.get("mastery") == "cleave"]
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]["reason"], "no_second_target")

    def test_default_reach_5_when_param_missing(self) -> None:
        # Defensive: mastery_params without reach_ft falls back to 5.
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_action(5)],
                                  position=(0, 0))
        primary = _make_actor("p", side="enemy", position=(1, 0))
        # secondary at (1, 1) — within 5 ft of both primary AND attacker
        secondary = _make_actor("s", side="enemy", position=(1, 1))
        state = _state_with([attacker, primary, secondary])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        # Pass mastery params WITHOUT reach_ft
        apply_mastery_effects(
            {"id": "cleave", "ability_mod": 3,
              "damage_type": "slashing", "save_dc": 13},
            attacker, primary, "hit", state)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "cleave"]
        # Fires because secondary is within both default 5 ft windows
        self.assertEqual(len(applied), 1)


if __name__ == "__main__":
    unittest.main()
