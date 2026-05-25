"""Action Economy dial v1 tests.

Three layers:
  1. Pure data — preset table correctness, tier-shift, percentage lookup
  2. Per-slot logic — main-slot miss → default action; bonus-slot gating
  3. Behavioral — Optimal preset never misses; Reactive_only misses often;
     bonus slot fires for signature actions, gated for tactical; play_context
     solo shifts preset down one tier; default action found correctly

Run via:
    python -m unittest tests.test_action_economy
"""
from __future__ import annotations

import random
import unittest

from engine.ai import (
    ACTION_ECONOMY_PRESETS,
    get_action_economy_percentages,
    resolve_action_economy_percentages,
    resolve_action_economy_preset_with_shift,
    find_default_action,
    action_slot,
    is_signature,
    resolve_main_slot,
    should_use_bonus_action,
)
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Test helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy", hp: int = 50,
                ac: int = 15, abilities: dict | None = None,
                actions: list[dict] | None = None,
                archetype: str | None = None,
                presets: dict | None = None,
                play_context: str | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = abilities or {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 1},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    bp: dict = {}
    if archetype:
        bp["archetype"] = archetype
    if presets:
        bp["presets"] = presets
    if play_context:
        bp["play_context"] = play_context
    if bp:
        template["behavior_profile"] = bp
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac, abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _weapon_attack(action_id: str, bonus: int = 3, dice: str = "1d6",
                    modifier: int = 0, slot: str = "action",
                    is_sig: bool = False) -> dict:
    action: dict = {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier, "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }
    if slot != "action":
        action["slot"] = slot
    if is_sig:
        action["is_signature"] = True
    return action


# ============================================================================
# Preset table correctness
# ============================================================================

class PresetTableTest(unittest.TestCase):

    def test_all_five_presets_defined(self) -> None:
        self.assertEqual(set(ACTION_ECONOMY_PRESETS),
                          {"optimal", "skilled", "average", "casual",
                           "reactive_only"})

    def test_optimal_is_100_pct_everywhere(self) -> None:
        pcts = get_action_economy_percentages("optimal")
        for key in ("main_optimality", "signature_bonus", "tactical_bonus",
                     "oa_reaction", "sophisticated_reaction"):
            self.assertEqual(pcts[key], 1.0, f"optimal.{key} should be 1.0")

    def test_reactive_only_has_zero_tactical(self) -> None:
        pcts = get_action_economy_percentages("reactive_only")
        self.assertEqual(pcts["tactical_bonus"], 0.0)
        self.assertEqual(pcts["sophisticated_reaction"], 0.0)

    def test_main_optimality_monotonic_across_presets(self) -> None:
        """Higher presets should have higher main_optimality."""
        order = ["reactive_only", "casual", "average", "skilled", "optimal"]
        values = [get_action_economy_percentages(p)["main_optimality"]
                   for p in order]
        self.assertEqual(values, sorted(values),
                          "main_optimality should rise monotonically")

    def test_unknown_preset_falls_back_to_average(self) -> None:
        pcts = get_action_economy_percentages("bogus_preset")
        avg = get_action_economy_percentages("average")
        self.assertEqual(pcts, avg)


# ============================================================================
# Resolve preset for actor (with archetype + play_context shift)
# ============================================================================

class ResolvePresetTest(unittest.TestCase):

    def test_explicit_preset_wins(self) -> None:
        a = _make_actor("a", presets={"action_economy": "optimal"})
        self.assertEqual(resolve_action_economy_preset_with_shift(a),
                          "optimal")

    def test_archetype_default(self) -> None:
        # apex_predator → 'skilled' per behavior_profile defaults
        a = _make_actor("a", archetype="apex_predator")
        self.assertEqual(resolve_action_economy_preset_with_shift(a),
                          "skilled")

    def test_no_archetype_falls_back_to_average(self) -> None:
        a = _make_actor("a")
        self.assertEqual(resolve_action_economy_preset_with_shift(a),
                          "average")

    def test_solo_play_context_shifts_one_tier_down(self) -> None:
        a = _make_actor("a", presets={"action_economy": "skilled"},
                         play_context="solo")
        self.assertEqual(resolve_action_economy_preset_with_shift(a),
                          "average")

    def test_solo_at_floor_stays_at_floor(self) -> None:
        a = _make_actor("a", presets={"action_economy": "reactive_only"},
                         play_context="solo")
        self.assertEqual(resolve_action_economy_preset_with_shift(a),
                          "reactive_only")

    def test_group_play_context_no_shift(self) -> None:
        a = _make_actor("a", presets={"action_economy": "skilled"},
                         play_context="group")
        self.assertEqual(resolve_action_economy_preset_with_shift(a),
                          "skilled")


# ============================================================================
# Default action lookup
# ============================================================================

class DefaultActionTest(unittest.TestCase):

    def test_first_weapon_attack_is_default(self) -> None:
        a = _make_actor("a", actions=[
            _weapon_attack("a_dagger", bonus=3, dice="1d4"),
            _weapon_attack("a_sword", bonus=5, dice="1d8"),
        ])
        default = find_default_action(a)
        self.assertEqual(default["id"], "a_dagger")

    def test_skips_multiattack(self) -> None:
        a = _make_actor("a", actions=[
            {"id": "a_multi", "type": "multiattack",
              "count": 2, "sub_actions": ["a_basic"]},
            _weapon_attack("a_basic", bonus=3, dice="1d6"),
        ])
        default = find_default_action(a)
        self.assertEqual(default["id"], "a_basic",
                          "Default should skip multiattack and pick a weapon_attack")

    def test_no_weapon_attack_returns_none(self) -> None:
        a = _make_actor("a", actions=[
            {"id": "a_spell", "type": "spellcasting"},
        ])
        self.assertIsNone(find_default_action(a))


# ============================================================================
# Slot + signature tag readers
# ============================================================================

class TagReadersTest(unittest.TestCase):

    def test_action_slot_default(self) -> None:
        self.assertEqual(action_slot({}), "action")

    def test_action_slot_bonus(self) -> None:
        self.assertEqual(action_slot({"slot": "bonus_action"}),
                          "bonus_action")

    def test_signature_default_false(self) -> None:
        self.assertFalse(is_signature({}))

    def test_signature_true(self) -> None:
        self.assertTrue(is_signature({"is_signature": True}))


# ============================================================================
# resolve_main_slot — the heart of step 7
# ============================================================================

class MainSlotOptimalityTest(unittest.TestCase):

    def test_none_chosen_returns_none(self) -> None:
        a = _make_actor("a")
        state = _state_with([a])
        self.assertIsNone(resolve_main_slot(a, None, state, random.Random(0)))

    def test_optimal_preset_always_keeps_chosen(self) -> None:
        """Optimal = 100% main_optimality, no roll ever misses."""
        dagger = _weapon_attack("a_dagger", bonus=3, dice="1d4")
        sword = _weapon_attack("a_sword", bonus=5, dice="1d8")
        a = _make_actor("a", actions=[dagger, sword],
                         presets={"action_economy": "optimal"})
        target = _make_actor("t", side="pc")
        state = _state_with([a, target])
        chosen = {"kind": "weapon_attack", "action": sword,
                   "target": target, "actor": a}
        # Try many seeds — should always keep `sword`
        for s in range(20):
            result = resolve_main_slot(a, chosen, state, random.Random(s))
            self.assertEqual(result["action"]["id"], "a_sword",
                              f"Optimal should never downgrade (seed {s})")
            self.assertNotIn("downgraded_from", result)

    def test_reactive_only_misses_often(self) -> None:
        """Reactive_only = 65% main_optimality; over 200 rolls expect ~35% misses."""
        dagger = _weapon_attack("a_dagger", bonus=3, dice="1d4")
        sword = _weapon_attack("a_sword", bonus=5, dice="1d8")
        a = _make_actor("a", actions=[dagger, sword],
                         presets={"action_economy": "reactive_only"})
        target = _make_actor("t", side="pc")
        state = _state_with([a, target])
        chosen = {"kind": "weapon_attack", "action": sword,
                   "target": target, "actor": a}

        rng = random.Random(42)
        misses = 0
        trials = 200
        for _ in range(trials):
            result = resolve_main_slot(a, chosen, state, rng)
            if result["action"]["id"] == "a_dagger":
                misses += 1
        # Expected ~35% misses. Allow wide tolerance (±10pp).
        miss_rate = misses / trials
        self.assertGreater(miss_rate, 0.20,
                            f"Reactive_only should miss often; got {miss_rate}")
        self.assertLess(miss_rate, 0.50,
                          f"Reactive_only miss rate {miss_rate} too high")

    def test_miss_falls_back_to_first_weapon_attack(self) -> None:
        dagger = _weapon_attack("a_dagger", bonus=3, dice="1d4")
        multi = {"id": "a_multi", "type": "multiattack",
                  "count": 2, "sub_actions": ["a_dagger"]}
        a = _make_actor("a", actions=[multi, dagger],   # multiattack listed FIRST
                         presets={"action_economy": "reactive_only"})
        target = _make_actor("t", side="pc")
        state = _state_with([a, target])
        chosen = {"kind": "multiattack", "action": multi,
                   "target": target, "actor": a}

        # Force a miss by using a seed that rolls > 0.65
        # (random.random() returns [0,1); we just iterate until we see one)
        rng = random.Random(0)
        found_miss = False
        for _ in range(50):
            result = resolve_main_slot(a, chosen, state, rng)
            if result.get("downgraded_from"):
                self.assertEqual(result["action"]["id"], "a_dagger",
                                  "On miss, should fall back to default weapon_attack")
                self.assertEqual(result["downgraded_from"], "a_multi")
                self.assertEqual(result["target"].id, "t",
                                  "Target should be preserved on miss")
                found_miss = True
                break
        self.assertTrue(found_miss, "Should have rolled a miss in 50 tries")

    def test_no_default_keeps_chosen(self) -> None:
        """If there's no fallback weapon_attack distinct from chosen,
        the chosen candidate is kept even on a 'miss' roll."""
        sword = _weapon_attack("a_sword", bonus=5, dice="1d8")
        # Only one weapon_attack in the action list AND it's the chosen one
        a = _make_actor("a", actions=[sword],
                         presets={"action_economy": "reactive_only"})
        target = _make_actor("t", side="pc")
        state = _state_with([a, target])
        chosen = {"kind": "weapon_attack", "action": sword,
                   "target": target, "actor": a}

        # All rolls should preserve sword (default == chosen).
        for s in range(20):
            result = resolve_main_slot(a, chosen, state, random.Random(s))
            self.assertEqual(result["action"]["id"], "a_sword")


# ============================================================================
# should_use_bonus_action — slot gating
# ============================================================================

class BonusActionGatingTest(unittest.TestCase):

    def test_signature_high_rate_under_optimal(self) -> None:
        """Optimal preset: signature bonus actions used 100% of the time."""
        a = _make_actor("a", presets={"action_economy": "optimal"})
        bonus = _weapon_attack("a_bonus", slot="bonus_action", is_sig=True)
        for s in range(20):
            self.assertTrue(
                should_use_bonus_action(a, bonus, random.Random(s)),
                f"Optimal signature bonus should always fire (seed {s})"
            )

    def test_reactive_only_zero_tactical(self) -> None:
        """Reactive_only: tactical_bonus = 0%; bonus never fires for
        non-signature actions."""
        a = _make_actor("a", presets={"action_economy": "reactive_only"})
        bonus = _weapon_attack("a_bonus", slot="bonus_action", is_sig=False)
        for s in range(20):
            self.assertFalse(
                should_use_bonus_action(a, bonus, random.Random(s)),
                f"Reactive_only tactical bonus should never fire (seed {s})"
            )

    def test_reactive_only_still_fires_signature_often(self) -> None:
        """Even Reactive_only fires signature bonus actions at 80%."""
        a = _make_actor("a", presets={"action_economy": "reactive_only"})
        sig_bonus = _weapon_attack("a_sig", slot="bonus_action", is_sig=True)
        rng = random.Random(99)
        fires = sum(1 for _ in range(200)
                     if should_use_bonus_action(a, sig_bonus, rng))
        rate = fires / 200
        # Expected ~80%; tolerance ±10pp
        self.assertGreater(rate, 0.70,
                            f"Reactive_only signature fire rate too low: {rate}")
        self.assertLess(rate, 0.90,
                          f"Reactive_only signature fire rate too high: {rate}")


# ============================================================================
# generate_candidates is slot-aware
# ============================================================================

class GenerateCandidatesSlotAwareTest(unittest.TestCase):

    def test_default_slot_skips_bonus_actions(self) -> None:
        main = _weapon_attack("a_main", slot="action")
        bonus = _weapon_attack("a_bonus", slot="bonus_action")
        a = _make_actor("a", side="pc", actions=[main, bonus])
        enemy = _make_actor("e", side="enemy")
        state = _state_with([a, enemy])

        # Default call enumerates action slot
        action_cands = generate_candidates(a, state)
        bonus_cands = generate_candidates(a, state, slot="bonus_action")

        action_ids = {c["action"]["id"] for c in action_cands}
        bonus_ids = {c["action"]["id"] for c in bonus_cands}
        self.assertEqual(action_ids, {"a_main"})
        self.assertEqual(bonus_ids, {"a_bonus"})

    def test_untagged_actions_treated_as_main_slot(self) -> None:
        """Backward-compat: actions without a `slot` field are main-slot."""
        untagged = _weapon_attack("a_untagged")  # no `slot` field
        a = _make_actor("a", side="pc", actions=[untagged])
        enemy = _make_actor("e", side="enemy")
        state = _state_with([a, enemy])

        cands = generate_candidates(a, state)
        self.assertEqual(len(cands), 1,
                          "Untagged actions should appear in the default-slot call")


# ============================================================================
# End-to-end via the runner: bonus action fires for a creature with one
# ============================================================================

class RunnerBonusActionIntegrationTest(unittest.TestCase):

    def test_bonus_action_fires_during_turn(self) -> None:
        """A creature with a signature bonus action under Optimal preset
        should land both a main attack AND a bonus attack in one turn."""
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        # Attacker has Optimal preset, a main attack, and a signature bonus attack
        main = _weapon_attack("a_main", bonus=10, dice="1d6", modifier=3)
        sig_bonus = _weapon_attack("a_offhand", bonus=10, dice="1d4",
                                     modifier=0, slot="bonus_action",
                                     is_sig=True)
        attacker = _make_actor("attacker", side="enemy", hp=20,
                                 actions=[main, sig_bonus],
                                 presets={"action_economy": "optimal"})
        # Target is a beefy training dummy that won't die in one turn
        target = _make_actor("target", side="pc", hp=200, ac=10)
        encounter = Encounter(id="bonus_test", actors=[attacker, target])

        primitives_module.set_rng(random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Count attacker's attacks against target in round 1 only
        round_1_events = []
        in_round_1 = True
        for e in state.event_log:
            if e.get("event") == "turn_start" and e.get("actor") == "attacker":
                in_round_1 = True
            elif e.get("event") == "turn_end" and e.get("actor") == "attacker":
                break
            if in_round_1 and e.get("event") == "attack_roll" \
                    and e.get("actor") == "attacker":
                round_1_events.append(e)
        # Should have 2 attacks: one main (a_main pipeline) + one bonus (a_offhand)
        self.assertGreaterEqual(len(round_1_events), 2,
                                 "Attacker should land both main + bonus action "
                                 f"in their first turn; got {len(round_1_events)}")


# ============================================================================
# End-to-end via the runner: Reactive_only PC can downgrade multiattack
# ============================================================================

class RunnerDowngradeIntegrationTest(unittest.TestCase):

    def test_reactive_only_can_log_downgrade(self) -> None:
        """A creature with Reactive_only preset attacking a tank should
        log at least one 'action_downgraded' event over many rounds."""
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        dagger = _weapon_attack("a_dagger", bonus=2, dice="1d4")
        # Listed FIRST so it's the default; multiattack listed SECOND so
        # it's NOT picked as default but it's the top-eHP pick.
        multi = {"id": "a_multi", "type": "multiattack",
                  "count": 2, "sub_actions": ["a_dagger"]}
        attacker = _make_actor("attacker", side="enemy", hp=40,
                                 actions=[dagger, multi],
                                 presets={"action_economy": "reactive_only"})
        # Beefy target — won't die mid-encounter; gives us many turns to roll
        target = _make_actor("target", side="pc", hp=500, ac=10)
        encounter = Encounter(id="downgrade_test", actors=[attacker, target])

        primitives_module.set_rng(random.Random(7))
        runner = EncounterRunner.new(encounter, seed=7)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=7)

        downgrades = [e for e in state.event_log
                       if e.get("event") == "action_downgraded"]
        # 50 rounds at 35% miss rate ≈ 17 expected downgrades; ≥ 1 is very safe.
        self.assertGreater(len(downgrades), 0,
                            "Reactive_only attacker should have at least one "
                            "logged action_downgraded over 50 rounds")


if __name__ == "__main__":
    unittest.main()
