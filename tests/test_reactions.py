"""Reaction infrastructure tests (PR #45).

Layers:
  1. is_reaction_action detection (trigger: <event> tag)
  2. pipeline.generate_candidates filters reactions out of main/bonus
  3. resolve_reaction_triggers scans actors + fires eligible reactions
  4. try_use_reaction consumes the reaction slot + spell slot
  5. Conditions vocabulary: shield_would_help,
     attack_against_ally_within_5_ft, damage_taken_by_self_from_attacker
  6. Shield end-to-end: retroactive AC turns hit into miss, slot
     consumed, doesn't fire when attack would miss anyway
  7. Protection end-to-end: ally adjacent attacker gets disadvantage,
     non-adjacent ally not protected
  8. Hellish Rebuke end-to-end: attacker takes 2d10 fire after damaging
     the rebuker
  9. One reaction per round (RAW): subsequent triggers don't refire
     the same reactor

Run via:
    python -m unittest tests.test_reactions
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, Encounter, CombatState
from engine.core.reactions import (
    is_reaction_action, resolve_reaction_triggers,
    _reaction_condition_satisfied,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, side="pc", hp=30, ac=14, position=(0, 0),
                con_save=0, dex_save=0,
                actions=None, resources=None, spell_slots=None):
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 10, "save": dex_save},
        "con": {"score": 10, "save": con_save},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "combat": {
                    "armor_class": ac,
                    "hit_points": {"average": hp, "dice": "5d10",
                                     "con_contribution": 10},
                    "speed": {"walk": 30},
                    "initiative": {"modifier": 0, "score": 10},
                },
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": 30}, position=position,
                  abilities=abilities,
                  resources=resources or {},
                  spell_slots=spell_slots or {})


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _shield_action() -> dict:
    return {
        "id": "a_shield", "name": "Shield",
        "type": "defensive_buff",
        "spell_slot_level": 1,
        "slot": "reaction",
        "trigger": "attack_roll_pending",
        "condition": "shield_would_help",
        "named_effect": "shield",
        "pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "self", "modifier": "ac_modifier",
                          "value": 5,
                          "lifetime": "until_actor_next_turn_start"}},
        ],
    }


def _protection_action() -> dict:
    return {
        "id": "a_protection", "name": "Protection",
        "type": "defensive_buff",
        "slot": "reaction",
        "trigger": "attack_targeting_resolved",
        "condition": "attack_against_ally_within_5_ft",
        "pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "current_target",
                          "modifier": "disadvantage_for_attacker",
                          "lifetime": "per_single_attack"}},
        ],
    }


def _hellish_rebuke_action() -> dict:
    return {
        "id": "a_hellish_rebuke", "name": "Hellish Rebuke",
        "type": "hard_control",
        "spell_slot_level": 1,
        "slot": "reaction",
        "trigger": "damage_taken",
        "condition": "damage_taken_by_self_from_attacker",
        "named_effect": "hellish_rebuke",
        "pipeline": [
            {"primitive": "forced_save",
              "params": {
                  "ability": "dexterity",
                  "dc": 13,
                  "affected": "current_target",
                  "on_fail": [{"primitive": "damage",
                                "params": {"dice": "2d10", "type": "fire"}}],
                  "on_success": [{"primitive": "damage",
                                    "params": {"dice": "2d10", "type": "fire",
                                                "multiplier": 0.5}}],
              }},
        ],
    }


def _weapon_attack(action_id="a_attack", bonus=4, dice="1d8", modifier=2,
                    reach_ft=5):
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus,
                          "reach_ft": reach_ft}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# is_reaction_action + candidate filtering
# ============================================================================

class IsReactionActionTest(unittest.TestCase):

    def test_action_with_trigger_is_reaction(self) -> None:
        self.assertTrue(is_reaction_action(_shield_action()))
        self.assertTrue(is_reaction_action(_protection_action()))
        self.assertTrue(is_reaction_action(_hellish_rebuke_action()))

    def test_normal_action_is_not_reaction(self) -> None:
        self.assertFalse(is_reaction_action(_weapon_attack()))


class GenerateCandidatesFiltersReactionsTest(unittest.TestCase):

    def test_reactions_not_in_main_candidates(self) -> None:
        from engine.core.pipeline import generate_candidates
        actor = _make_actor("a", actions=[_weapon_attack(),
                                            _shield_action()],
                              spell_slots={1: 1})
        enemy = _make_actor("e", side="enemy", position=(0, 1),
                              actions=[_weapon_attack()])
        state = _state_with([actor, enemy])
        cands = generate_candidates(actor, state, slot="action")
        ids = [c["action"].get("id") for c in cands]
        self.assertNotIn("a_shield", ids)


# ============================================================================
# Condition vocabulary
# ============================================================================

class ReactionConditionTest(unittest.TestCase):

    def test_none_means_always(self) -> None:
        actor = _make_actor("a")
        state = _state_with([actor])
        self.assertTrue(_reaction_condition_satisfied(
            None, actor, {}, state))
        self.assertTrue(_reaction_condition_satisfied(
            "always", actor, {}, state))

    def test_shield_would_help_yes(self) -> None:
        """total=18, current_ac=15: would hit (18 >= 15) AND would miss
        if AC bumped (18 < 20). Shield should fire."""
        wizard = _make_actor("wiz")
        state = _state_with([wizard])
        ed = {"target": wizard, "total": 18, "current_ac": 15}
        self.assertTrue(_reaction_condition_satisfied(
            "shield_would_help", wizard, ed, state))

    def test_shield_would_help_no_attack_would_miss_anyway(self) -> None:
        """total=10 vs AC 15: already missing. Don't waste Shield."""
        wizard = _make_actor("wiz")
        state = _state_with([wizard])
        ed = {"target": wizard, "total": 10, "current_ac": 15}
        self.assertFalse(_reaction_condition_satisfied(
            "shield_would_help", wizard, ed, state))

    def test_shield_would_help_no_attack_would_hit_anyway(self) -> None:
        """total=22 vs AC 15: would hit even at AC 20. Shield wastes."""
        wizard = _make_actor("wiz")
        state = _state_with([wizard])
        ed = {"target": wizard, "total": 22, "current_ac": 15}
        self.assertFalse(_reaction_condition_satisfied(
            "shield_would_help", wizard, ed, state))

    def test_shield_would_help_not_self(self) -> None:
        """Reactor must be the target. Ally being hit doesn't qualify."""
        wizard = _make_actor("wiz")
        ally = _make_actor("ally")
        state = _state_with([wizard, ally])
        ed = {"target": ally, "total": 18, "current_ac": 15}
        self.assertFalse(_reaction_condition_satisfied(
            "shield_would_help", wizard, ed, state))

    def test_attack_against_ally_within_5_ft_yes(self) -> None:
        protector = _make_actor("p", position=(0, 0))
        ally = _make_actor("a", side="pc", position=(0, 1))
        state = _state_with([protector, ally])
        ed = {"target": ally}
        self.assertTrue(_reaction_condition_satisfied(
            "attack_against_ally_within_5_ft", protector, ed, state))

    def test_attack_against_ally_within_5_ft_not_adjacent(self) -> None:
        protector = _make_actor("p", position=(0, 0))
        ally = _make_actor("a", side="pc", position=(10, 10))
        state = _state_with([protector, ally])
        ed = {"target": ally}
        self.assertFalse(_reaction_condition_satisfied(
            "attack_against_ally_within_5_ft", protector, ed, state))

    def test_attack_against_ally_within_5_ft_enemy_target(self) -> None:
        """Don't Protect an enemy."""
        protector = _make_actor("p", side="pc")
        enemy = _make_actor("e", side="enemy", position=(0, 1))
        state = _state_with([protector, enemy])
        ed = {"target": enemy}
        self.assertFalse(_reaction_condition_satisfied(
            "attack_against_ally_within_5_ft", protector, ed, state))

    def test_damage_taken_by_self_from_attacker_yes(self) -> None:
        warlock = _make_actor("w")
        attacker = _make_actor("att", side="enemy")
        state = _state_with([warlock, attacker])
        ed = {"target_id": "w", "attacker": attacker}
        self.assertTrue(_reaction_condition_satisfied(
            "damage_taken_by_self_from_attacker", warlock, ed, state))
        # Side effect: sets the _reaction_target_is_attacker flag
        self.assertTrue(ed.get("_reaction_target_is_attacker"))

    def test_damage_taken_by_other_doesnt_fire(self) -> None:
        warlock = _make_actor("w")
        other = _make_actor("o")
        attacker = _make_actor("att", side="enemy")
        state = _state_with([warlock, other, attacker])
        ed = {"target_id": "o", "attacker": attacker}
        self.assertFalse(_reaction_condition_satisfied(
            "damage_taken_by_self_from_attacker", warlock, ed, state))


# ============================================================================
# resolve_reaction_triggers + try_use_reaction
# ============================================================================

class TryUseReactionTest(unittest.TestCase):

    def test_reaction_slot_consumed(self) -> None:
        from engine.core.reactions import try_use_reaction
        wizard = _make_actor("wiz", actions=[_shield_action()],
                                spell_slots={1: 1})
        attacker = _make_actor("att", side="enemy")
        state = _state_with([wizard, attacker])
        ed = {"target": wizard, "total": 18, "current_ac": 15}
        result = try_use_reaction(
            wizard, _shield_action(), ed, state, bus=None)
        self.assertTrue(result)
        self.assertTrue(wizard.actions_used_this_turn.get("reaction"))
        # Spell slot consumed
        self.assertEqual(wizard.spell_slots.get(1), 0)

    def test_reaction_skipped_without_slot(self) -> None:
        from engine.core.reactions import try_use_reaction
        wizard = _make_actor("wiz", actions=[_shield_action()],
                                spell_slots={1: 0})
        state = _state_with([wizard])
        ed = {"target": wizard, "total": 18, "current_ac": 15}
        result = try_use_reaction(
            wizard, _shield_action(), ed, state, bus=None)
        self.assertFalse(result)
        self.assertFalse(wizard.actions_used_this_turn.get("reaction"))

    def test_one_reaction_per_round(self) -> None:
        """A reactor who has already used their reaction this round
        doesn't fire again."""
        wizard = _make_actor("wiz", actions=[_shield_action()],
                                spell_slots={1: 1})
        attacker = _make_actor("att", side="enemy")
        state = _state_with([wizard, attacker])
        wizard.actions_used_this_turn["reaction"] = True   # already used
        n = resolve_reaction_triggers("attack_roll_pending",
            {"target": wizard, "total": 18, "current_ac": 15,
              "actor": attacker}, state, bus=None)
        self.assertEqual(n, 0)


# ============================================================================
# Shield end-to-end
# ============================================================================

class ShieldEndToEndTest(unittest.TestCase):

    def _run_single_attack(self, attacker, target, attack_bonus=4,
                              rng_seed=1):
        """Invoke a single _attack_roll cycle. attack_bonus must match
        the attacker's weapon's bonus param (the helper passes it
        directly to _attack_roll rather than reading the action).

        PR #67: sets encounters_remaining=1 so pace-aware reaction
        scoring doesn't suppress the reaction firing (these tests
        verify mechanics, not pacing — the dedicated pace tests
        live in test_pace_aware_reactions.py)."""
        from engine.primitives import _attack_roll
        from engine.core.events import EventBus
        import engine.primitives as primitives_module
        state = _state_with([attacker, target])
        state.encounters_remaining_today = 1
        primitives_module.set_rng(random.Random(rng_seed))
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": _weapon_attack(bonus=attack_bonus),
            "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": None, "area_direction": None,
        }
        bus = EventBus()
        result = _attack_roll(
            {"kind": "melee", "bonus": attack_bonus, "reach_ft": 5},
            state, bus)
        return result, state

    def test_shield_turns_hit_into_miss(self) -> None:
        """Attacker rolls a high d20; total would hit but Shield bumps
        AC by 5 and the same total now misses."""
        # Wizard with AC 14, Shield prepped. Attacker with +10 bonus
        # to nearly guarantee a hit.
        wizard = _make_actor("wiz", ac=14, position=(0, 0),
                                actions=[_shield_action()],
                                spell_slots={1: 1})
        attacker = _make_actor("att", side="enemy", position=(0, 1),
                                  actions=[_weapon_attack(bonus=10)])
        # Use a seed that produces a d20 that would hit AC 14 but miss
        # AC 19. seed=1's first d20 is 5 → total 15 (hits 14, misses 19).
        result, state = self._run_single_attack(attacker, wizard,
                                                    attack_bonus=10)
        # If d20 + 10 was >= 14 (hit at base) AND < 19 (miss with Shield),
        # we expect a miss + Shield fired. With seed=1 the d20 is 5 →
        # total = 15. That hits AC 14 base; misses AC 19 (Shield).
        # Expected: miss, Shield fired.
        if 15 >= wizard.ac and 15 < wizard.ac + 5:
            self.assertEqual(result["state"], "miss",
                              "Shield should have turned a 15-vs-14 hit "
                              "into a miss against 15-vs-19")
            fired = [e for e in state.event_log
                      if e.get("event") == "reaction_fired"
                      and e.get("action") == "a_shield"]
            self.assertEqual(len(fired), 1)
            # Slot consumed
            self.assertEqual(wizard.spell_slots[1], 0)

    def test_shield_doesnt_fire_when_attack_misses_anyway(self) -> None:
        """Low d20 → attack would miss without Shield → don't waste it."""
        wizard = _make_actor("wiz", ac=20, position=(0, 0),
                                actions=[_shield_action()],
                                spell_slots={1: 1})
        attacker = _make_actor("att", side="enemy", position=(0, 1),
                                  actions=[_weapon_attack(bonus=2)])
        result, state = self._run_single_attack(attacker, wizard,
                                                    attack_bonus=2)
        # bonus 2 + max d20 24 = 22, but AC is 20 so 18 d20 is needed.
        # Whatever the roll, if total < 20 the attack misses naturally
        # → Shield should NOT fire.
        if result["state"] == "miss":
            fired = [e for e in state.event_log
                      if e.get("event") == "reaction_fired"]
            self.assertEqual(len(fired), 0,
                              "Shield shouldn't fire when attack misses "
                              "anyway")
            self.assertEqual(wizard.spell_slots[1], 1)   # slot preserved


# ============================================================================
# Regression: reaction self-modifier owner when firing between turns
# ============================================================================

class ReactionSelfModifierOwnerTest(unittest.TestCase):
    """A self-targeted reaction modifier (Shield's +5 AC) owns to the REACTOR,
    even when the reaction fires BETWEEN turns — current_turn_idx out of range,
    as during a legendary action. This reproduces the Adult Brass Dragon crash
    (IndexError in current_actor via _resolve_modifier_owner) and verifies the
    fix: current_actor() returns None instead of raising, and the reaction's
    self-modifier resolves to current_attack['actor'] (the reactor)."""

    def test_shield_owner_is_reactor_when_turn_idx_out_of_range(self) -> None:
        from engine.core.reactions import try_use_reaction
        wizard = _make_actor("wiz", ac=14, actions=[_shield_action()],
                              spell_slots={1: 1})
        attacker = _make_actor("att", side="enemy",
                                actions=[_weapon_attack(bonus=10)])
        state = _state_with([wizard, attacker])
        state.encounters_remaining_today = 1
        # Reaction fires between turns (legendary-action timing): the turn
        # index points past the end of turn_order.
        state.current_turn_idx = len(state.turn_order)
        self.assertIsNone(state.current_actor())   # hardened — no IndexError

        ed = {"target": wizard, "total": 18, "current_ac": 14,
              "actor": attacker}
        result = try_use_reaction(wizard, _shield_action(), ed, state, bus=None)
        self.assertTrue(result)
        # The +5 AC attaches to the REACTOR (wizard), never the attacker.
        self.assertTrue(wizard.active_modifiers,
                        "Shield's AC modifier should own to the reactor")
        self.assertEqual(attacker.active_modifiers, [],
                         "Reaction self-buff must NOT attach to the turn-holder")


# ============================================================================
# Protection end-to-end
# ============================================================================

class ProtectionEndToEndTest(unittest.TestCase):

    def test_protection_imposes_disadvantage_on_adjacent_ally(self) -> None:
        """Attacker swings at a wizard adjacent to the protector;
        protector reacts, attack rolls with disadvantage."""
        from engine.primitives import _attack_roll
        from engine.core.events import EventBus
        import engine.primitives as primitives_module

        protector = _make_actor("p", side="pc", position=(0, 0),
                                   actions=[_protection_action()])
        ally = _make_actor("a", side="pc", position=(0, 1))    # 5 ft from p
        attacker = _make_actor("att", side="enemy", position=(0, 2))
        state = _state_with([protector, ally, attacker])
        primitives_module.set_rng(random.Random(1))
        state.current_attack = {
            "actor": attacker, "target": ally,
            "action": _weapon_attack(), "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": None, "area_direction": None,
        }
        bus = EventBus()
        result = _attack_roll({"kind": "melee", "bonus": 4, "reach_ft": 5},
                                state, bus)
        # Attack should be rolled with disadvantage
        fired = [e for e in state.event_log
                  if e.get("event") == "reaction_fired"
                  and e.get("action") == "a_protection"]
        self.assertEqual(len(fired), 1)
        # attack_roll event has advantage_state recorded
        attack_event = next((e for e in state.event_log
                              if e.get("event") == "attack_roll"
                              and e.get("actor") == "att"), None)
        self.assertIsNotNone(attack_event)
        self.assertEqual(attack_event["advantage_state"], "disadvantage")

    def test_protection_skipped_when_ally_not_adjacent(self) -> None:
        from engine.primitives import _attack_roll
        from engine.core.events import EventBus
        import engine.primitives as primitives_module

        protector = _make_actor("p", side="pc", position=(0, 0),
                                   actions=[_protection_action()])
        ally = _make_actor("a", side="pc", position=(20, 20))    # far
        attacker = _make_actor("att", side="enemy", position=(21, 20))
        state = _state_with([protector, ally, attacker])
        primitives_module.set_rng(random.Random(1))
        state.current_attack = {
            "actor": attacker, "target": ally,
            "action": _weapon_attack(), "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": None, "area_direction": None,
        }
        bus = EventBus()
        _attack_roll({"kind": "melee", "bonus": 4, "reach_ft": 5},
                       state, bus)
        fired = [e for e in state.event_log
                  if e.get("event") == "reaction_fired"]
        self.assertEqual(len(fired), 0)


# ============================================================================
# Hellish Rebuke end-to-end
# ============================================================================

class HellishRebukeEndToEndTest(unittest.TestCase):

    def test_hellish_rebuke_damages_attacker(self) -> None:
        """Warlock takes damage, reacts with HR, attacker takes 2d10
        fire damage (DEX save half)."""
        from engine.primitives import _attack_roll, _damage
        from engine.core.events import EventBus
        import engine.primitives as primitives_module

        warlock = _make_actor("warlock", side="pc", position=(0, 0),
                                 ac=10,    # easy to hit
                                 actions=[_hellish_rebuke_action()],
                                 spell_slots={1: 1})
        # Attacker with low DEX save and low HP so HR's damage is
        # measurable
        attacker = _make_actor("att", side="enemy", position=(0, 1),
                                  hp=30, dex_save=-2,
                                  actions=[_weapon_attack(bonus=10)])
        state = _state_with([warlock, attacker])
        # PR #67: set encounters_remaining=1 so pace-aware reaction
        # scoring doesn't suppress HR firing. HR's value (~8 eHP) is
        # below the new L1 base cost of 10 in mid-day setups; the
        # last-encounter case bypasses pacing for this mechanics test.
        state.encounters_remaining_today = 1
        primitives_module.set_rng(random.Random(1))
        # Run a full attack — _attack_roll then _damage
        state.current_attack = {
            "actor": attacker, "target": warlock,
            "action": _weapon_attack(), "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": None, "area_direction": None,
        }
        bus = EventBus()
        _attack_roll({"kind": "melee", "bonus": 10, "reach_ft": 5},
                       state, bus)
        # Only run damage if hit
        if state.current_attack.get("state") in ("hit", "crit"):
            attacker_hp_before = attacker.hp_current
            _damage({"dice": "1d8", "modifier": 2, "type": "slashing"},
                      state, bus)
            # HR should have fired against the attacker
            fired = [e for e in state.event_log
                      if e.get("event") == "reaction_fired"
                      and e.get("action") == "a_hellish_rebuke"]
            self.assertEqual(len(fired), 1)
            # Attacker took fire damage
            self.assertLess(attacker.hp_current, attacker_hp_before)
            # Slot consumed
            self.assertEqual(warlock.spell_slots[1], 0)


if __name__ == "__main__":
    unittest.main()
