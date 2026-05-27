"""Sneak Attack tests (PR #72).

Layers:
  1. Level table: SA dice scale by Rogue level
  2. Weapon gate: finesse-melee + ranged qualify, vanilla melee doesn't
  3. Roll-state gate: advantage qualifies; disadvantage suppresses
  4. Ally-adjacent fallback when no advantage
  5. Incapacitated-ally doesn't enable SA
  6. Per-turn dedup (once per turn, even across multiple attacks)
  7. Per-turn dedup RESETS at the next turn (multi-turn fire)
  8. Crit doubles SA dice
  9. Non-Rogue actors never SA
 10. pc_schema integration (template.levels.rogue, finesse plumb-through)
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.sneak_attack import (
    SNEAK_ATTACK_DICE_BY_LEVEL,
    sneak_attack_dice_at_level,
    qualifies_for_sneak_attack,
    try_apply_sneak_attack,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _damage


# ============================================================================
# Helpers
# ============================================================================

def _make_rogue(actor_id="rogue", *, level=3, position=(0, 0),
                  side="pc"):
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 18, "save": 4},
        "con": {"score": 14, "save": 2},
        "int": {"score": 12, "save": 1},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}",
        "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
        "levels": {"rogue": level},
    }
    return Actor(
        id=actor_id, name=actor_id, template=template,
        side=side, hp_current=20, hp_max=20, ac=14,
        speed={"walk": 30}, position=position,
        abilities=abilities,
    )


def _make_target(actor_id="dummy", *, position=(1, 0), side="enemy",
                   hp=100):
    abilities = {k: {"score": 10, "save": 0}
                 for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}",
        "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template,
        side=side, hp_current=hp, hp_max=hp, ac=14,
        speed={"walk": 30}, position=position,
        abilities=abilities,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _attack_context(state, attacker, target, *, finesse=False,
                       ranged=False, ability="dex",
                       had_advantage=False, had_disadvantage=False,
                       attack_state="hit"):
    """Build a state.current_attack matching what _attack_roll would set."""
    attack_params = {
        "kind": "ranged" if ranged else "melee",
        "ability": ability,
        "bonus": 6,
    }
    if finesse:
        attack_params["finesse"] = True
    if ranged:
        attack_params["range_ft"] = 80
    else:
        attack_params["reach_ft"] = 5
    action = {"id": "a_test", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll", "params": attack_params},
              ]}
    state.current_attack = {
        "actor": attacker, "target": target,
        "action": action, "state": attack_state,
        "had_advantage": had_advantage,
        "had_disadvantage": had_disadvantage,
    }
    return attack_params


# ============================================================================
# Layer 1: level table
# ============================================================================

class SneakAttackLevelTableTest(unittest.TestCase):

    def test_table_matches_raw(self) -> None:
        # RAW: ceil(level/2) d6 at odd levels; pairs at even levels
        # 1d6 at L1-2; 2d6 at L3-4; ... 10d6 at L19-20
        self.assertEqual(sneak_attack_dice_at_level(1), 1)
        self.assertEqual(sneak_attack_dice_at_level(2), 1)
        self.assertEqual(sneak_attack_dice_at_level(3), 2)
        self.assertEqual(sneak_attack_dice_at_level(5), 3)
        self.assertEqual(sneak_attack_dice_at_level(11), 6)
        self.assertEqual(sneak_attack_dice_at_level(19), 10)
        self.assertEqual(sneak_attack_dice_at_level(20), 10)

    def test_zero_and_clamp(self) -> None:
        self.assertEqual(sneak_attack_dice_at_level(0), 0)
        self.assertEqual(sneak_attack_dice_at_level(-1), 0)
        self.assertEqual(sneak_attack_dice_at_level(25), 10)


# ============================================================================
# Layer 2: weapon gate
# ============================================================================

class WeaponGateTest(unittest.TestCase):

    def test_finesse_melee_qualifies(self) -> None:
        attacker = _make_rogue()
        target = _make_target()
        state = _make_state([attacker, target])
        params = _attack_context(state, attacker, target, finesse=True,
                                    had_advantage=True)
        self.assertTrue(qualifies_for_sneak_attack(
            attacker, target, state, params))

    def test_ranged_qualifies(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(15, 0))
        state = _make_state([attacker, target])
        params = _attack_context(state, attacker, target, ranged=True,
                                    had_advantage=True)
        self.assertTrue(qualifies_for_sneak_attack(
            attacker, target, state, params))

    def test_vanilla_melee_does_not_qualify(self) -> None:
        attacker = _make_rogue()
        target = _make_target()
        state = _make_state([attacker, target])
        # No finesse, not ranged — straight melee (e.g. spear w/o finesse)
        params = _attack_context(state, attacker, target,
                                    had_advantage=True)
        self.assertFalse(qualifies_for_sneak_attack(
            attacker, target, state, params))


# ============================================================================
# Layer 3: roll-state gate
# ============================================================================

class RollStateGateTest(unittest.TestCase):

    def test_advantage_qualifies(self) -> None:
        attacker = _make_rogue()
        target = _make_target()
        state = _make_state([attacker, target])
        params = _attack_context(state, attacker, target, finesse=True,
                                    had_advantage=True)
        self.assertTrue(qualifies_for_sneak_attack(
            attacker, target, state, params))

    def test_disadvantage_suppresses_even_with_ally_adjacent(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(1, 0))
        # Ally adjacent to target
        ally = _make_target("ally", position=(2, 0), side="pc")
        ally.id = "ally"   # ensure id is correct
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True,
                                    had_disadvantage=True)
        self.assertFalse(qualifies_for_sneak_attack(
            attacker, target, state, params))


# ============================================================================
# Layer 4: ally-adjacent fallback
# ============================================================================

class AllyAdjacentFallbackTest(unittest.TestCase):

    def test_no_advantage_no_ally_no_sa(self) -> None:
        attacker = _make_rogue()
        target = _make_target()
        state = _make_state([attacker, target])
        params = _attack_context(state, attacker, target, finesse=True)
        # No advantage, no other allies anywhere
        self.assertFalse(qualifies_for_sneak_attack(
            attacker, target, state, params))

    def test_no_advantage_ally_adjacent_qualifies(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(5, 0))
        # Place ally 5ft from target (distance_ft uses Chebyshev or similar)
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True)
        self.assertTrue(qualifies_for_sneak_attack(
            attacker, target, state, params))

    def test_attacker_itself_does_not_count_as_ally(self) -> None:
        # RAW: "Another enemy" — the attacker doesn't count as their own
        # adjacent ally. If the attacker is the only PC adjacent to
        # target, SA should NOT qualify on the ally-adjacent path.
        attacker = _make_rogue(position=(0, 0))
        target = _make_target(position=(1, 0))  # attacker is adjacent
        state = _make_state([attacker, target])
        params = _attack_context(state, attacker, target, finesse=True)
        self.assertFalse(qualifies_for_sneak_attack(
            attacker, target, state, params))


# ============================================================================
# Layer 5: incapacitated ally doesn't enable SA
# ============================================================================

class IncapacitatedAllyTest(unittest.TestCase):

    def test_incapacitated_adjacent_ally_does_not_enable_sa(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(5, 0))
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        ally.applied_conditions = [{"condition_id": "co_incapacitated"}]
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True)
        self.assertFalse(qualifies_for_sneak_attack(
            attacker, target, state, params))


# ============================================================================
# Layer 6+7: per-turn dedup
# ============================================================================

class PerTurnDedupTest(unittest.TestCase):

    def test_sa_fires_only_once_per_turn(self) -> None:
        rng = random.Random(7)
        attacker = _make_rogue(level=3)   # 2d6
        target = _make_target(position=(5, 0), hp=200)
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True)
        # First call: fires
        dmg1 = try_apply_sneak_attack(attacker, target, state, params,
                                          rng, is_crit=False)
        self.assertGreater(dmg1, 0)
        self.assertTrue(attacker._sneak_attack_used_this_turn)
        # Second call same turn: returns 0
        dmg2 = try_apply_sneak_attack(attacker, target, state, params,
                                          rng, is_crit=False)
        self.assertEqual(dmg2, 0)

    def test_reset_turn_clears_dedup_flag(self) -> None:
        rng = random.Random(7)
        attacker = _make_rogue()
        target = _make_target(position=(5, 0))
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True)
        try_apply_sneak_attack(attacker, target, state, params, rng,
                                  is_crit=False)
        self.assertTrue(attacker._sneak_attack_used_this_turn)
        attacker.reset_turn()
        self.assertFalse(attacker._sneak_attack_used_this_turn)
        # Now SA fires again on the next turn
        dmg = try_apply_sneak_attack(attacker, target, state, params, rng,
                                          is_crit=False)
        self.assertGreater(dmg, 0)


# ============================================================================
# Layer 8: crit doubles dice
# ============================================================================

class CritDoubleTest(unittest.TestCase):

    def test_crit_doubles_dice_count(self) -> None:
        # Roll N times and check both crit-rolled and normal-rolled
        # totals fall in the expected ranges. L3 = 2d6 normal,
        # 4d6 on crit.
        attacker = _make_rogue(level=3)
        target = _make_target(position=(5, 0), hp=500)
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True)
        rng = random.Random(99)
        crit_max_seen = 0
        for _ in range(30):
            attacker._sneak_attack_used_this_turn = False
            dmg = try_apply_sneak_attack(attacker, target, state, params,
                                              rng, is_crit=True)
            crit_max_seen = max(crit_max_seen, dmg)
        # Normal max = 2 * 6 = 12; crit max = 4 * 6 = 24. With 30 rolls
        # we should regularly exceed 12.
        self.assertGreater(crit_max_seen, 12)


# ============================================================================
# Layer 9: non-Rogue actors never SA
# ============================================================================

class NonRogueTest(unittest.TestCase):

    def test_fighter_does_not_sneak_attack(self) -> None:
        attacker = _make_rogue("fighter")
        # Strip the rogue level
        attacker.template["levels"] = {"fighter": 5}
        target = _make_target(position=(5, 0))
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True,
                                    had_advantage=True)
        self.assertFalse(qualifies_for_sneak_attack(
            attacker, target, state, params))

    def test_no_levels_at_all_does_not_sa(self) -> None:
        attacker = _make_rogue("goblin")
        attacker.template["levels"] = {}
        target = _make_target(position=(5, 0))
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        params = _attack_context(state, attacker, target, finesse=True,
                                    had_advantage=True)
        self.assertFalse(qualifies_for_sneak_attack(
            attacker, target, state, params))


# ============================================================================
# Layer 10: damage primitive integration + pc_schema
# ============================================================================

class DamagePrimitiveIntegrationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(13))

    def test_damage_primitive_applies_sa(self) -> None:
        # End-to-end: build attack context, call _damage, observe
        # higher damage when SA fires than when it doesn't.
        attacker = _make_rogue(level=3)   # 2d6 SA
        target = _make_target(position=(5, 0), hp=500)
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        _attack_context(state, attacker, target, finesse=True)
        # Track HP delta over multiple swings with SA + multiple
        # without (by flipping the dedup flag manually).
        sa_damages = []
        no_sa_damages = []
        for _ in range(30):
            # With SA
            target.hp_current = 500
            attacker._sneak_attack_used_this_turn = False
            state.current_attack["state"] = "hit"
            _damage({"dice": "1d6", "modifier": 4, "type": "piercing"},
                    state, EventBus())
            sa_damages.append(500 - target.hp_current)
            # Without SA (force the flag)
            target.hp_current = 500
            attacker._sneak_attack_used_this_turn = True
            _damage({"dice": "1d6", "modifier": 4, "type": "piercing"},
                    state, EventBus())
            no_sa_damages.append(500 - target.hp_current)
        # SA should average significantly higher (extra ~7 avg from 2d6)
        avg_sa = sum(sa_damages) / len(sa_damages)
        avg_no = sum(no_sa_damages) / len(no_sa_damages)
        self.assertGreater(avg_sa - avg_no, 3.0)

    def test_damage_logs_sneak_attack_event(self) -> None:
        attacker = _make_rogue(level=1)
        target = _make_target(position=(5, 0))
        ally = _make_rogue("ally", position=(6, 0), side="pc")
        state = _make_state([attacker, ally, target])
        _attack_context(state, attacker, target, finesse=True)
        state.current_attack["state"] = "hit"
        _damage({"dice": "1d6", "modifier": 4, "type": "piercing"},
                state, EventBus())
        sa_events = [e for e in state.event_log
                       if e.get("event") == "sneak_attack_applied"]
        self.assertEqual(len(sa_events), 1)
        self.assertEqual(sa_events[0]["dice_count"], 1)
        self.assertEqual(sa_events[0]["trigger"], "ally_adjacent")


class PcSchemaSneakAttackTest(unittest.TestCase):

    def test_l3_rogue_template_levels_and_finesse_plumb(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        from engine.pc_schema import build_pc_template
        repo_root = Path(__file__).parent.parent
        registry = load_content(repo_root / "schema" / "content",
                                  validate=True,
                                  schema_root=repo_root / "schema" / "definitions")
        pc_spec = {
            "id": "rogue3",
            "class": "c_rogue",
            "level": 3,
            "ability_scores": {"str": 8, "dex": 18, "con": 14,
                                 "int": 12, "wis": 10, "cha": 10},
            "weapons": [{"id": "rapier", "name": "Rapier",
                          "damage_dice": "1d8", "damage_type": "piercing",
                          "attack_ability": "dex", "finesse": True,
                          "mastery": "vex"}],
            "weapon_masteries": ["vex"],
        }
        template = build_pc_template(pc_spec, registry)
        # template.levels.rogue stamped
        self.assertEqual(template["levels"]["rogue"], 3)
        # Rapier action has finesse=True in attack_params
        rapier = next(a for a in template["actions"]
                          if a.get("id") == "rapier")
        attack_step = rapier["pipeline"][0]
        self.assertEqual(attack_step["primitive"], "attack_roll")
        self.assertTrue(attack_step["params"].get("finesse"))


if __name__ == "__main__":
    unittest.main()
