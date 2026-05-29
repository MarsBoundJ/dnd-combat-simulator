"""Multi-target ordering refinement (PR #105).

`_select_multi_target_group` (PR #97) sorts most-wounded-first. That's
correct for Aid (a heal / max-HP bump), but PR #98's multi-target Bless
inherited it — and Bless is an *attack* buff, whose value scales with
how hard the recipient swings, not how hurt they are. PR #105 makes the
ordering dispatch on `action["type"]`:

  - offensive_buff (Bless) → highest-DPR allies first
  - everything else (Aid / heal / defensive) → most-wounded-first

These tests pin both branches:
  1. offensive_buff picks the party's heavy hitters over a near-dead
     back-line caster
  2. a 0-DPR ally (no weapon) is only picked to fill an empty slot
  3. heal / defensive_buff still picks most-wounded-first (regression)
  4. range filter still applies to both branches
"""
from __future__ import annotations

import unittest

from engine.core import pipeline
from engine.core.state import Actor, CombatState, Encounter


def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30,
                  hp_max=30, ac=14, actions=None):
    abilities = {a: {"score": 12, "save": 1}
                  for a in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": list(actions or []),
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp_max, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _weapon_action(action_id, dice, modifier, bonus=5):
    return {
        "id": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier}},
        ],
    }


def _multiattack(count):
    return {"id": "a_multi", "type": "multiattack", "count": count}


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _bless_action(max_targets=3, range_ft=30):
    return {"id": "a_bless", "name": "Bless", "type": "offensive_buff",
            "max_targets": max_targets, "range_ft": range_ft}


def _aid_action(max_targets=3, range_ft=30):
    return {"id": "a_aid", "name": "Aid", "type": "defensive_buff",
            "max_targets": max_targets, "range_ft": range_ft}


# ============================================================================
# offensive_buff (Bless) → highest-DPR-first
# ============================================================================

class OffensiveBuffOrderingTest(unittest.TestCase):

    def test_picks_highest_dpr_allies(self) -> None:
        caster = _make_actor("caster")
        # Heavy hitter: greatsword + Extra Attack (multiattack 2).
        fighter = _make_actor("fighter", actions=[
            _weapon_action("a_gs", "2d6", 4), _multiattack(2)])
        # Mid: single dagger.
        rogue = _make_actor("rogue", actions=[
            _weapon_action("a_dag", "1d4", 3)])
        # Near-dead back-line caster: NO weapon (DPR 0), badly wounded.
        wizard = _make_actor("wizard", hp=2, hp_max=30, actions=[])
        state = _make_state([caster, fighter, rogue, wizard])
        group = pipeline._select_multi_target_group(
            _bless_action(max_targets=2), [fighter, rogue, wizard],
            caster, state)
        ids = [a.id for a in group]
        # Top-2 by DPR: fighter then rogue. The near-dead wizard is
        # NOT picked despite being most-wounded — Bless is an attack
        # buff, and the wizard can't attack.
        self.assertEqual(ids, ["fighter", "rogue"])

    def test_wounded_does_not_override_dpr(self) -> None:
        caster = _make_actor("caster")
        # Wounded heavy hitter vs healthy weakling.
        fighter = _make_actor("fighter", hp=3, hp_max=40, actions=[
            _weapon_action("a_gs", "2d6", 4), _multiattack(2)])
        weakling = _make_actor("weakling", hp=30, hp_max=30, actions=[
            _weapon_action("a_dag", "1d4", 0)])
        state = _make_state([caster, fighter, weakling])
        group = pipeline._select_multi_target_group(
            _bless_action(max_targets=1), [fighter, weakling],
            caster, state)
        # Highest-DPR wins regardless of HP fraction.
        self.assertEqual([a.id for a in group], ["fighter"])

    def test_zero_dpr_ally_fills_empty_slot(self) -> None:
        caster = _make_actor("caster")
        fighter = _make_actor("fighter", actions=[
            _weapon_action("a_gs", "2d6", 4)])
        wizard = _make_actor("wizard", actions=[])  # DPR 0
        state = _make_state([caster, fighter, wizard])
        # max_targets=3 but only 2 allies → both picked, attacker first.
        group = pipeline._select_multi_target_group(
            _bless_action(max_targets=3), [fighter, wizard],
            caster, state)
        self.assertEqual([a.id for a in group], ["fighter", "wizard"])


# ============================================================================
# heal / defensive_buff (Aid) → most-wounded-first (regression)
# ============================================================================

class DefensiveBuffOrderingTest(unittest.TestCase):

    def test_picks_most_wounded_first(self) -> None:
        caster = _make_actor("caster")
        # DPR is high on the healthy fighter — must NOT influence Aid.
        fighter = _make_actor("fighter", hp=30, hp_max=30, actions=[
            _weapon_action("a_gs", "2d6", 4), _multiattack(2)])
        bloodied = _make_actor("bloodied", hp=5, hp_max=30)   # 17%
        scratched = _make_actor("scratched", hp=25, hp_max=30)  # 83%
        state = _make_state([caster, fighter, bloodied, scratched])
        group = pipeline._select_multi_target_group(
            _aid_action(max_targets=2), [fighter, bloodied, scratched],
            caster, state)
        # Two most-wounded: bloodied (17%) then scratched (83%). The
        # healthy high-DPR fighter is NOT prioritized.
        self.assertEqual([a.id for a in group], ["bloodied", "scratched"])


# ============================================================================
# Range filter applies to both branches
# ============================================================================

class RangeFilterTest(unittest.TestCase):

    def test_offensive_buff_respects_range(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        near = _make_actor("near", position=(1, 0), actions=[
            _weapon_action("a", "1d4", 0)])
        far = _make_actor("far", position=(20, 0), actions=[  # 100 ft
            _weapon_action("a", "2d6", 4), _multiattack(2)])
        state = _make_state([caster, near, far])
        group = pipeline._select_multi_target_group(
            _bless_action(max_targets=3, range_ft=30), [near, far],
            caster, state)
        # `far` is the higher-DPR ally but out of 30 ft range.
        self.assertEqual([a.id for a in group], ["near"])


if __name__ == "__main__":
    unittest.main()
