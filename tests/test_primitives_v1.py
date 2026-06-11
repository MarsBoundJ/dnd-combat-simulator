"""Integration tests for primitives v1 — the Q5 unified modifier system,
forced_save, recurring_save, multiattack.

Tests the keystone change: conditions applied to an actor actually
affect attack resolution / save resolution through the active_modifiers
registry consulted by the engine.

Run via:
    python -m unittest tests.test_primitives_v1
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine import primitives as primitives_module
from engine.cli import _build_encounter
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, Encounter, CombatState
from engine.core import modifiers
from engine.loader import load_content, load_yaml_file
from engine.primitives import (
    PrimitiveRegistry, remove_condition,
    _apply_condition, _attack_roll, _forced_save, _recurring_save,
    _crit_threshold_modifier, _attack_modifier,
)


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
MULTIATTACK_FIXTURE = Path(__file__).parent / "fixtures" / "test_multiattack_encounter.yaml"
SMOKE_FIXTURE = Path(__file__).parent / "fixtures" / "smoke_encounter.yaml"


def _make_actor(actor_id: str, side: str, hp: int = 20, ac: int = 15,
                abilities: dict | None = None) -> Actor:
    abilities = abilities or {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id, "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2}}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac, abilities=abilities)


def _make_state(actors: list[Actor], registry=None) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    return CombatState(encounter=enc, content_registry=registry)


# ============================================================================
# Test: Blinded target → attacker has advantage on attacks against it
# ============================================================================

class BlindedAdvantageTest(unittest.TestCase):
    """Apply Blinded to a creature; attacks against it should have advantage."""

    def test_blinded_target_gives_attacker_advantage(self) -> None:
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        attacker = _make_actor("att", "pc")
        target = _make_actor("tgt", "enemy")
        state = _make_state([attacker, target], registry=registry)

        # Apply Blinded to the target
        state.current_attack = {"actor": attacker, "target": target}
        _apply_condition({"condition_id": "co_blinded"}, state, None)

        # Verify Blinded's effects landed in target's active_modifiers
        attack_mods_on_target = [m for m in target.active_modifiers
                                  if m["primitive"] == "attack_modifier"]
        self.assertGreater(len(attack_mods_on_target), 0,
                            "Blinded should have added attack_modifier entries")

        # Now query the modifier aggregator
        result = modifiers.query_attack_modifiers(attacker, target, state)
        self.assertEqual(result.net_advantage(), "advantage",
                          "Attacker should have advantage against Blinded target")

    def test_blinded_self_gives_disadvantage_on_own_attacks(self) -> None:
        """The blinded creature's OWN attacks are at disadvantage."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        blinded_attacker = _make_actor("blinded", "enemy")
        target = _make_actor("victim", "pc")
        state = _make_state([blinded_attacker, target], registry=registry)

        state.current_attack = {"actor": target, "target": blinded_attacker}
        _apply_condition({"condition_id": "co_blinded"}, state, None)

        # When blinded_attacker attacks target, it should have disadvantage
        result = modifiers.query_attack_modifiers(blinded_attacker, target, state)
        self.assertEqual(result.net_advantage(), "disadvantage",
                          "Blinded creature's own attacks should have disadvantage")


# ============================================================================
# Test: Paralyzed → auto-fail STR/DEX saves + inherited Incapacitated
# ============================================================================

class ParalyzedSavesTest(unittest.TestCase):

    def test_paralyzed_auto_fails_str_save(self) -> None:
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        victim = _make_actor("victim", "enemy")
        caster = _make_actor("caster", "pc")
        state = _make_state([caster, victim], registry=registry)

        state.current_attack = {"actor": caster, "target": victim}
        _apply_condition({"condition_id": "co_paralyzed"}, state, None)

        # Query save modifiers for STR
        result = modifiers.query_save_modifiers(victim, "strength", state)
        self.assertEqual(result.net_outcome_override(), "auto_fail",
                          "Paralyzed should auto-fail STR saves")

    def test_paralyzed_auto_fails_dex_save(self) -> None:
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        victim = _make_actor("victim", "enemy")
        caster = _make_actor("caster", "pc")
        state = _make_state([caster, victim], registry=registry)

        state.current_attack = {"actor": caster, "target": victim}
        _apply_condition({"condition_id": "co_paralyzed"}, state, None)

        result = modifiers.query_save_modifiers(victim, "dexterity", state)
        self.assertEqual(result.net_outcome_override(), "auto_fail")

    def test_paralyzed_does_NOT_auto_fail_wis_save(self) -> None:
        """Paralyzed only auto-fails STR + DEX; WIS save still rolls normally."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        victim = _make_actor("victim", "enemy")
        caster = _make_actor("caster", "pc")
        state = _make_state([caster, victim], registry=registry)

        state.current_attack = {"actor": caster, "target": victim}
        _apply_condition({"condition_id": "co_paralyzed"}, state, None)

        result = modifiers.query_save_modifiers(victim, "wisdom", state)
        self.assertIsNone(result.net_outcome_override())

    def test_paralyzed_inherits_incapacitated(self) -> None:
        """Paralyzed includes Incapacitated; both should appear in applied_conditions."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        victim = _make_actor("victim", "enemy")
        caster = _make_actor("caster", "pc")
        state = _make_state([caster, victim], registry=registry)

        state.current_attack = {"actor": caster, "target": victim}
        _apply_condition({"condition_id": "co_paralyzed"}, state, None)

        condition_ids = [a["condition_id"] for a in victim.applied_conditions]
        self.assertIn("co_paralyzed", condition_ids)
        self.assertIn("co_incapacitated", condition_ids,
                       "Paralyzed should also apply Incapacitated via inheritance")


# ============================================================================
# Test: Champion Improved Critical lowers crit threshold to 19
# ============================================================================

class ImprovedCriticalTest(unittest.TestCase):

    def test_crit_threshold_modifier_lowers_threshold(self) -> None:
        attacker = _make_actor("champion", "pc")
        target = _make_actor("dummy", "enemy", hp=100, ac=10)
        state = _make_state([attacker, target])

        # Manually apply Improved Critical (no condition wrapping; direct modifier)
        attacker.active_modifiers.append({
            "primitive": "crit_threshold_modifier",
            "params": {"new_threshold": 19},
            "lifetime": "until_long_rest",
            "source": {"type": "feature", "id": "f_improved_critical"},
            "owner_id": attacker.id,
        })

        result = modifiers.query_crit_modifiers(attacker, target, state)
        self.assertEqual(result.crit_threshold, 19,
                          "Improved Critical should lower threshold to 19")


# ============================================================================
# Test: Champion Superior Critical lowers crit threshold to 18
# ============================================================================

class SuperiorCriticalTest(unittest.TestCase):

    def test_crit_threshold_modifier_lowers_threshold_to_18(self) -> None:
        attacker = _make_actor("champion_l15", "pc")
        target = _make_actor("dummy", "enemy", hp=100, ac=10)
        state = _make_state([attacker, target])

        # Manually apply Superior Critical (same pattern as Improved Critical)
        attacker.active_modifiers.append({
            "primitive": "crit_threshold_modifier",
            "params": {"new_threshold": 18},
            "lifetime": "until_long_rest",
            "source": {"type": "feature", "id": "f_superior_critical"},
            "owner_id": attacker.id,
        })

        result = modifiers.query_crit_modifiers(attacker, target, state)
        self.assertEqual(result.crit_threshold, 18,
                          "Superior Critical should lower threshold to 18")

    def test_superior_critical_beats_improved_critical(self) -> None:
        """When both are active, query_crit_modifiers takes the minimum (18)."""
        attacker = _make_actor("champion_l15", "pc")
        target = _make_actor("dummy", "enemy", hp=100, ac=10)
        state = _make_state([attacker, target])

        attacker.active_modifiers.append({
            "primitive": "crit_threshold_modifier",
            "params": {"new_threshold": 19},
            "lifetime": "until_long_rest",
            "source": {"type": "feature", "id": "f_improved_critical"},
            "owner_id": attacker.id,
        })
        attacker.active_modifiers.append({
            "primitive": "crit_threshold_modifier",
            "params": {"new_threshold": 18},
            "lifetime": "until_long_rest",
            "source": {"type": "feature", "id": "f_superior_critical"},
            "owner_id": attacker.id,
        })

        result = modifiers.query_crit_modifiers(attacker, target, state)
        self.assertEqual(result.crit_threshold, 18,
                          "Superior Critical (18) should win over Improved Critical (19)")


# ============================================================================
# Test: Multiattack runs N attacks per turn
# ============================================================================

class MultiattackTest(unittest.TestCase):

    def test_multiattack_dual_wielder(self) -> None:
        """Test Dual Wielder uses Multiattack → 2 scimitar attacks per turn."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        spec = load_yaml_file(MULTIATTACK_FIXTURE)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(random.Random(11))
        runner = EncounterRunner.new(encounter, seed=11, content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=11)

        # Count attack events from the dual_wielder per round
        dual_attack_events = [
            e for e in state.event_log
            if e.get("event") == "attack_roll" and e.get("actor") == "dual_wielder_1"
        ]
        # Even if combat ends in 1 round, we should see at least 2 attacks (multiattack)
        # OR if dual wielder never got a turn (Fighter went first and won), expect 0+.
        # Assert: the encounter has at least one round where dual wielder attacks twice.
        if dual_attack_events:
            # Group by round; each round should have 2 attacks
            from collections import Counter
            attacks_by_round = Counter()
            for e in dual_attack_events:
                attacks_by_round[e.get("round", 0)] += 1
            max_attacks_in_round = max(attacks_by_round.values())
            self.assertGreaterEqual(
                max_attacks_in_round, 2,
                f"Dual wielder should make 2 attacks per multiattack turn; "
                f"max seen in one round: {max_attacks_in_round}"
            )


# ============================================================================
# Test: forced_save resolves with on_fail / on_success differential outcomes
# ============================================================================

class ForcedSaveTest(unittest.TestCase):

    def test_forced_save_with_high_dc_likely_fails(self) -> None:
        """DC 20 save against a creature with low Wisdom should usually fail."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        target = _make_actor("low_wis_target", "enemy",
                              abilities={
                                  "str": {"score": 8, "save": -1},
                                  "dex": {"score": 8, "save": -1},
                                  "con": {"score": 8, "save": -1},
                                  "int": {"score": 8, "save": -1},
                                  "wis": {"score": 6, "save": -2},
                                  "cha": {"score": 8, "save": -1},
                              })
        caster = _make_actor("caster", "pc")
        state = _make_state([caster, target], registry=registry)
        state.current_attack = {"actor": caster, "target": target}

        primitives_module.set_rng(random.Random(3))

        result = _forced_save({
            "ability": "wisdom",
            "dc": 20,
            "affected": "current_target",
            "on_fail": [{
                "primitive": "apply_condition",
                "params": {"condition_id": "co_frightened"},
            }],
        }, state, None)

        self.assertEqual(len(result["rolls"]), 1)
        roll = result["rolls"][0]
        # With seed=3 and target WIS save -2 vs DC 20, the save WILL fail
        # (even with d20=20 → 20-2=18 < 20). So this is deterministic.
        self.assertEqual(roll["outcome"], "fail")
        # And the on_fail subprimitive should have applied Frightened
        condition_ids = [a["condition_id"] for a in target.applied_conditions]
        self.assertIn("co_frightened", condition_ids)


# ============================================================================
# Test: recurring_save registers and resolves at target's turn_end
# ============================================================================

class RecurringSaveTest(unittest.TestCase):

    def test_recurring_save_registered_and_attempted(self) -> None:
        """A recurring_save registers an entry; runner resolves at turn_end.

        Verifies the registration mechanism. Eventual end-of-condition via
        successful save is covered by integration with Hold Person's full
        pipeline (deferred until apply_condition+recurring_save are exercised
        together by an actual spell).
        """
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        caster = _make_actor("caster", "pc")
        victim = _make_actor("victim", "enemy")
        state = _make_state([caster, victim], registry=registry)
        state.current_attack = {"actor": caster, "target": victim}

        _recurring_save({
            "ability": "wisdom",
            "dc": 15,
            "trigger_event": "target_turn_end",
            "on_success": "end_spell_on_target",
            "condition_id": "co_paralyzed",
        }, state, None)

        self.assertEqual(len(state.recurring_saves), 1)
        entry = state.recurring_saves[0]
        self.assertEqual(entry["target_id"], "victim")
        self.assertEqual(entry["ability"], "wisdom")
        self.assertEqual(entry["dc"], 15)


# ============================================================================
# Test: remove_condition cleans up active_modifiers
# ============================================================================

class ConditionRemovalTest(unittest.TestCase):

    def test_removing_blinded_removes_its_active_modifiers(self) -> None:
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        target = _make_actor("victim", "enemy")
        caster = _make_actor("caster", "pc")
        state = _make_state([caster, target], registry=registry)

        state.current_attack = {"actor": caster, "target": target}
        _apply_condition({"condition_id": "co_blinded"}, state, None)
        self.assertGreater(len(target.active_modifiers), 0)

        removed = remove_condition(target, "co_blinded", source_creature_id=caster.id)
        self.assertGreater(removed, 0, "Should have removed at least one modifier")
        self.assertEqual(len(target.active_modifiers), 0,
                          "All Blinded modifiers should be removed")
        # Condition entry should also be gone
        condition_ids = [a["condition_id"] for a in target.applied_conditions]
        self.assertNotIn("co_blinded", condition_ids)

    def test_removing_paralyzed_removes_inherited_incapacitated_modifiers(self) -> None:
        """Paralyzed inherits Incapacitated; removing Paralyzed should remove
        the inherited Incapacitated's modifiers too (per parent_condition chain)."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        target = _make_actor("victim", "enemy")
        caster = _make_actor("caster", "pc")
        state = _make_state([caster, target], registry=registry)

        state.current_attack = {"actor": caster, "target": target}
        _apply_condition({"condition_id": "co_paralyzed"}, state, None)

        before = len(target.active_modifiers)
        self.assertGreater(before, 0)
        remove_condition(target, "co_paralyzed", source_creature_id=caster.id)
        self.assertEqual(len(target.active_modifiers), 0,
                          f"All Paralyzed (and inherited Incapacitated) modifiers "
                          f"should be removed; {len(target.active_modifiers)} remain")


if __name__ == "__main__":
    unittest.main()
