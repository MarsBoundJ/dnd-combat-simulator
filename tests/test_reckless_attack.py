"""Reckless Attack tests (PR #85).

RAW (Barbarian L2, PHB 2024 p.50):
  "When you make your first attack roll on your turn, you can decide
  to attack recklessly. Doing so gives you advantage on
  Strength-based melee weapon attack rolls during this turn, but
  attack rolls against you have advantage until the start of your
  next turn."

Layers covered:
  1. Eligibility (is_eligible / has_str_melee_weapon)
  2. activate flips both flags + idempotent
  3. applies_self_advantage gating (STR-melee yes, DEX-finesse no,
     ranged no, non-reckless no)
  4. applies_attacker_advantage_against (any attack shape against
     reckless target)
  5. query_attack_modifiers integration (both arms grant advantage)
  6. reset_turn clears both flags at start of next own turn
  7. should_activate archetype overrides (always / never / default)
  8. should_activate cost-benefit heuristic
  9. Runner integration: hook fires before main slot + logs event
"""
from __future__ import annotations

import random
import unittest

from engine.core import reckless_attack as ra
from engine.core.modifiers import query_attack_modifiers
from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), level=2,
                  hp=30, hp_max=30, ac=14, str_score=18,
                  dex_score=10, has_reckless=True,
                  weapon_kind="melee", weapon_ability="str",
                  archetype=None):
    abilities = {
        "str": {"score": str_score, "save": 4},
        "dex": {"score": dex_score, "save": 0},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    actions = [{
        "id": "a_greataxe",
        "name": "Greataxe",
        "type": "weapon_attack",
        "slot": "action",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": weapon_kind, "ability": weapon_ability,
                          "bonus": 7}},
            {"primitive": "damage",
              "params": {"dice": "1d12", "modifier": 4,
                          "type": "slashing"}},
        ],
    }]
    template = {
        "id": f"tpl_{actor_id}",
        "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": actions,
        "levels": {"barbarian": level},
        "features_known": (["f_reckless_attack"] if has_reckless else []),
    }
    if archetype is not None:
        template["behavior_profile"] = {"archetype": archetype}
    return Actor(
        id=actor_id, name=actor_id, template=template,
        side=side,
        hp_current=hp, hp_max=hp_max, ac=ac,
        speed={"walk": 30}, position=position,
        abilities=abilities,
        resources={},
    )


def _make_enemy(actor_id, *, side="enemy", position=(5, 0),
                  hp=20, ac=13, attack_dice="1d8", attack_mod=3):
    abilities = {a: {"score": 12, "save": 1}
                  for a in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}",
        "name": actor_id,
        "abilities": abilities,
        "actions": [{
            "id": "a_attack",
            "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "ability": "str",
                              "bonus": 4}},
                {"primitive": "damage",
                  "params": {"dice": attack_dice, "modifier": attack_mod,
                              "type": "slashing"}},
            ],
        }],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template,
        side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position,
        abilities=abilities,
        resources={},
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1: eligibility
# ============================================================================

class EligibilityTest(unittest.TestCase):

    def test_is_eligible_true_with_feature(self) -> None:
        a = _make_actor("b1", has_reckless=True)
        self.assertTrue(ra.is_eligible(a))

    def test_is_eligible_false_without_feature(self) -> None:
        a = _make_actor("b1", has_reckless=False)
        self.assertFalse(ra.is_eligible(a))

    def test_has_str_melee_weapon_true_for_greataxe(self) -> None:
        a = _make_actor("b1")
        self.assertTrue(ra.has_str_melee_weapon(a))

    def test_has_str_melee_weapon_false_for_ranged(self) -> None:
        a = _make_actor("b1", weapon_kind="ranged")
        self.assertFalse(ra.has_str_melee_weapon(a))

    def test_has_str_melee_weapon_false_for_dex_finesse(self) -> None:
        a = _make_actor("b1", weapon_ability="dex")
        self.assertFalse(ra.has_str_melee_weapon(a))


# ============================================================================
# Layer 2: activate transitions
# ============================================================================

class ActivateTest(unittest.TestCase):

    def test_activate_flips_both_flags(self) -> None:
        a = _make_actor("b1")
        state = _make_state([a])
        self.assertFalse(a.reckless_active)
        self.assertFalse(a.reckless_grants_advantage_until_next_turn)
        ra.activate(a, state)
        self.assertTrue(a.reckless_active)
        self.assertTrue(a.reckless_grants_advantage_until_next_turn)

    def test_activate_emits_event(self) -> None:
        a = _make_actor("b1")
        state = _make_state([a])
        ra.activate(a, state)
        events = [e for e in state.event_log
                    if e.get("event") == "reckless_attack_activated"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "b1")

    def test_activate_idempotent(self) -> None:
        a = _make_actor("b1")
        state = _make_state([a])
        ra.activate(a, state)
        ra.activate(a, state)
        events = [e for e in state.event_log
                    if e.get("event") == "reckless_attack_activated"]
        self.assertEqual(len(events), 1)


# ============================================================================
# Layer 3: applies_self_advantage gating
# ============================================================================

class SelfAdvantageGateTest(unittest.TestCase):

    def test_no_advantage_when_not_reckless(self) -> None:
        a = _make_actor("b1")
        self.assertFalse(ra.applies_self_advantage(
            a, {"kind": "melee", "ability": "str"}))

    def test_advantage_on_str_melee_when_reckless(self) -> None:
        a = _make_actor("b1")
        a.reckless_active = True
        self.assertTrue(ra.applies_self_advantage(
            a, {"kind": "melee", "ability": "str"}))

    def test_no_advantage_on_ranged_even_when_reckless(self) -> None:
        a = _make_actor("b1")
        a.reckless_active = True
        self.assertFalse(ra.applies_self_advantage(
            a, {"kind": "ranged", "ability": "str"}))

    def test_no_advantage_on_dex_finesse_even_when_reckless(self) -> None:
        a = _make_actor("b1")
        a.reckless_active = True
        self.assertFalse(ra.applies_self_advantage(
            a, {"kind": "melee", "ability": "dex"}))

    def test_defaults_to_str_melee_when_params_absent(self) -> None:
        # If a primitive caller doesn't specify kind/ability, the RAW
        # default is "melee weapon attack using STR" — apply advantage.
        a = _make_actor("b1")
        a.reckless_active = True
        self.assertTrue(ra.applies_self_advantage(a, {}))
        self.assertTrue(ra.applies_self_advantage(a, None))


# ============================================================================
# Layer 4: applies_attacker_advantage_against
# ============================================================================

class AttackerAdvantageGateTest(unittest.TestCase):

    def test_no_advantage_when_window_closed(self) -> None:
        target = _make_actor("b1")
        self.assertFalse(ra.applies_attacker_advantage_against(target))

    def test_advantage_when_window_open(self) -> None:
        target = _make_actor("b1")
        target.reckless_grants_advantage_until_next_turn = True
        self.assertTrue(ra.applies_attacker_advantage_against(target))


# ============================================================================
# Layer 5: query_attack_modifiers integration
# ============================================================================

class QueryIntegrationTest(unittest.TestCase):

    def test_self_advantage_routes_through_query(self) -> None:
        attacker = _make_actor("b1", side="pc")
        target = _make_enemy("g1")
        state = _make_state([attacker, target])
        attacker.reckless_active = True
        # Set up current_attack with the action so query can read
        # the in-flight attack_roll params.
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": attacker.template["actions"][0],
            "state": None,
        }
        result = query_attack_modifiers(attacker, target, state)
        self.assertEqual(result.net_advantage(), "advantage")

    def test_attacker_advantage_against_reckless_target(self) -> None:
        # Enemy attacking the reckless Barbarian: enemy's outgoing
        # attack rolls with advantage.
        attacker = _make_enemy("g1")
        target = _make_actor("b1")
        target.reckless_grants_advantage_until_next_turn = True
        state = _make_state([attacker, target])
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": attacker.template["actions"][0],
            "state": None,
        }
        result = query_attack_modifiers(attacker, target, state)
        self.assertEqual(result.net_advantage(), "advantage")

    def test_no_advantage_for_dex_swing_even_when_reckless(self) -> None:
        # A Reckless Barbarian wielding a Rapier (DEX-finesse) gets
        # nothing on their outgoing swing — RAW pins to STR. But
        # incoming attacks still get advantage.
        attacker = _make_actor("b1", weapon_ability="dex")
        target = _make_enemy("g1")
        state = _make_state([attacker, target])
        attacker.reckless_active = True
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": attacker.template["actions"][0],
            "state": None,
        }
        result = query_attack_modifiers(attacker, target, state)
        # The Barbarian's outgoing rapier attack: no advantage.
        self.assertEqual(result.net_advantage(), "normal")


# ============================================================================
# Layer 6: reset_turn clears flags
# ============================================================================

class ResetTurnTest(unittest.TestCase):

    def test_reset_turn_clears_both_flags(self) -> None:
        a = _make_actor("b1")
        a.reckless_active = True
        a.reckless_grants_advantage_until_next_turn = True
        a.reset_turn()
        self.assertFalse(a.reckless_active)
        self.assertFalse(a.reckless_grants_advantage_until_next_turn)


# ============================================================================
# Layer 7: should_activate archetype overrides
# ============================================================================

class ShouldActivateArchetypeTest(unittest.TestCase):

    def test_berserker_fanatic_always_activates(self) -> None:
        a = _make_actor("b1", archetype="berserker_fanatic")
        e = _make_enemy("g1")
        state = _make_state([a, e])
        ok, reason = ra.should_activate(a, state)
        self.assertTrue(ok)
        self.assertEqual(reason, "archetype_always")

    def test_mindless_aggressor_always_activates(self) -> None:
        a = _make_actor("b1", archetype="mindless_aggressor")
        e = _make_enemy("g1")
        state = _make_state([a, e])
        ok, reason = ra.should_activate(a, state)
        self.assertTrue(ok)
        self.assertEqual(reason, "archetype_always")

    def test_cowardly_skirmisher_never_activates(self) -> None:
        a = _make_actor("b1", archetype="cowardly_skirmisher")
        e = _make_enemy("g1")
        state = _make_state([a, e])
        ok, reason = ra.should_activate(a, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "archetype_never")

    def test_no_enemies_skip(self) -> None:
        a = _make_actor("b1")
        state = _make_state([a])
        ok, reason = ra.should_activate(a, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_enemies")

    def test_no_feature_skip(self) -> None:
        a = _make_actor("b1", has_reckless=False)
        e = _make_enemy("g1")
        state = _make_state([a, e])
        ok, reason = ra.should_activate(a, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_feature")

    def test_no_str_melee_skip(self) -> None:
        # Reckless Barbarian holding only a ranged weapon — would
        # benefit nothing from the advantage uplift.
        a = _make_actor("b1", weapon_kind="ranged")
        e = _make_enemy("g1")
        state = _make_state([a, e])
        ok, reason = ra.should_activate(a, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_str_melee")

    def test_already_active_skip(self) -> None:
        a = _make_actor("b1")
        e = _make_enemy("g1")
        state = _make_state([a, e])
        a.reckless_active = True
        ok, reason = ra.should_activate(a, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "already_active")


# ============================================================================
# Layer 8: should_activate cost-benefit heuristic
# ============================================================================

class ShouldActivateHeuristicTest(unittest.TestCase):

    def test_solo_strong_barbarian_vs_weak_goblin_activates(self) -> None:
        # Barbarian Greataxe (1d12+4 ~ 10.5 avg) vs 1 goblin (1d8+3
        # ~ 7.5 avg). Gain = 1 × 0.25 × 10.5 = 2.625.
        # Cost = min(1, 3) × 0.25 × 7.5 = 1.875. Activate.
        a = _make_actor("b1")
        e = _make_enemy("g1", attack_dice="1d8", attack_mod=3)
        state = _make_state([a, e])
        ok, reason = ra.should_activate(a, state)
        self.assertTrue(ok)
        self.assertEqual(reason, "gain_exceeds_cost")

    def test_outnumbered_vs_strong_enemies_holds_back(self) -> None:
        # Barbarian alone vs 3 hard-hitting enemies (2d10+5 ~ 16 avg
        # each). Cost = 3 × 0.25 × 16 = 12. Gain ≈ 1 × 0.25 × 10.5
        # = 2.625. Don't activate.
        a = _make_actor("b1")
        e1 = _make_enemy("g1", attack_dice="2d10", attack_mod=5)
        e2 = _make_enemy("g2", attack_dice="2d10", attack_mod=5,
                            position=(0, 5))
        e3 = _make_enemy("g3", attack_dice="2d10", attack_mod=5,
                            position=(5, 5))
        state = _make_state([a, e1, e2, e3])
        ok, reason = ra.should_activate(a, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "cost_exceeds_gain")


# ============================================================================
# Layer 9: runner integration
# ============================================================================

class RunnerIntegrationTest(unittest.TestCase):
    """Pre-action hook fires before the main slot and logs event."""

    def test_hook_fires_and_activates(self) -> None:
        from engine.core.runner import EncounterRunner
        a = _make_actor("b1", archetype="berserker_fanatic")
        e = _make_enemy("g1")
        state = _make_state([a, e])
        runner = EncounterRunner.new(state.encounter, seed=42)
        runner._maybe_activate_reckless_attack(a, state)
        self.assertTrue(a.reckless_active)
        self.assertTrue(a.reckless_grants_advantage_until_next_turn)
        events = [e for e in state.event_log
                    if e.get("event") == "reckless_attack_activated"]
        self.assertEqual(len(events), 1)

    def test_hook_skip_logs_reason(self) -> None:
        from engine.core.runner import EncounterRunner
        a = _make_actor("b1", archetype="cowardly_skirmisher")
        e = _make_enemy("g1")
        state = _make_state([a, e])
        runner = EncounterRunner.new(state.encounter, seed=42)
        runner._maybe_activate_reckless_attack(a, state)
        self.assertFalse(a.reckless_active)
        events = [e for e in state.event_log
                    if e.get("event") == "reckless_attack_skipped"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reason"], "archetype_never")

    def test_hook_silent_for_non_barbarian(self) -> None:
        # Non-Barbarian doesn't pollute the log every turn with
        # "no_feature" skips.
        from engine.core.runner import EncounterRunner
        a = _make_actor("not_a_barb", has_reckless=False)
        e = _make_enemy("g1")
        state = _make_state([a, e])
        runner = EncounterRunner.new(state.encounter, seed=42)
        runner._maybe_activate_reckless_attack(a, state)
        events = [e for e in state.event_log
                    if e.get("event") in ("reckless_attack_activated",
                                            "reckless_attack_skipped")]
        self.assertEqual(events, [])


# ============================================================================
# Layer 10: PC schema integration (feature appears in features_known)
# ============================================================================

class PcSchemaIntegrationTest(unittest.TestCase):
    """At L2, a Barbarian PC should have f_reckless_attack in
    features_known so the runner hook activates."""

    def test_barbarian_l2_has_reckless_attack_feature(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        from engine.pc_schema import build_pc_template

        repo_root = Path(__file__).resolve().parent.parent
        content = load_content(
            repo_root / "schema" / "content", validate=True,
            schema_root=repo_root / "schema",
        )
        pc_spec = {
            "id": "pc_test_barb",
            "name": "Test Barb",
            "class": "c_barbarian",
            "level": 2,
            "abilities": {
                "str": 18, "dex": 12, "con": 14,
                "int": 8, "wis": 10, "cha": 10,
            },
            "weapons": [],
        }
        template = build_pc_template(pc_spec, content)
        self.assertIn("f_reckless_attack",
                        template.get("features_known", []))


if __name__ == "__main__":
    unittest.main()
