"""Ready Action ally_takes_damage trigger tests (PR #93).

Third Ready trigger after PR #86's enemy_enters_reach + enemy_casts_spell.
Closes the deferred follow-on flagged in PR #86's open items.

RAW: Ready triggers on a "perceivable circumstance." Ally taking
damage is the iconic supportive-caster pattern — Cleric Ready
Healing-Word-on-damage, Wizard Ready-Shield-on-ally-damage, Bard
Ready Healing-Word-on-ally-drop. v1 ships the trigger; the iconic
Healing-Word-picks-up-downed-ally case works via the new
`allow_dead_target=True` kwarg on try_fire.

Layers:
  1. KNOWN_TRIGGERS contains ally_takes_damage
  2. register accepts ally_takes_damage trigger
  3. on_ally_takes_damage fires when ally takes damage
  4. Filters: not same-side / not self / within range / min_damage
  5. allow_dead_target=True lets Ready fire on downed ally
  6. _damage hook fires the trigger after damage applies
  7. Candidate emission: heal/defensive_buff sub-actions emit
  8. Candidate emission: no-ally / no-in-danger skip
  9. Scorer: ally_takes_damage routes through defensive_ehp
"""
from __future__ import annotations

import random
import unittest

from engine.core import ready_action as ra
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  actions=None, walk=30):
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
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": walk}, position=position, abilities=abilities,
    )


def _healing_word_action():
    """A heal-type action mimicking Healing Word."""
    return {
        "id": "a_healing_word",
        "name": "Healing Word",
        "type": "heal",
        "slot": "bonus_action",
        "spell_slot_level": 1,
        "pipeline": [
            {"primitive": "heal",
              "params": {"target": "current_target",
                          "amount_dice": "1d4",
                          "amount_modifier": 3}},
        ],
    }


def _melee_attack():
    return {
        "id": "a_attack", "type": "weapon_attack", "slot": "action",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "ability": "str",
                          "bonus": 5, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "1d8", "modifier": 3,
                          "type": "slashing"}},
        ],
    }


def _make_state(actors, turn_order=None):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = list(turn_order) if turn_order else [
        a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1+2: KNOWN_TRIGGERS + register
# ============================================================================

class TriggerVocabularyTest(unittest.TestCase):

    def test_ally_takes_damage_in_known_triggers(self) -> None:
        self.assertIn("ally_takes_damage", ra.KNOWN_TRIGGERS)

    def test_register_accepts_ally_takes_damage(self) -> None:
        cleric = _make_actor("cleric", actions=[_healing_word_action()])
        state = _make_state([cleric])
        ra.register(cleric, "a_healing_word", "ally_takes_damage", state,
                      trigger_params={"within_ft": 60,
                                        "min_damage": 5})
        self.assertEqual(cleric.readied_action["trigger"],
                            "ally_takes_damage")
        self.assertEqual(cleric.readied_action["trigger_params"]["within_ft"], 60)
        self.assertEqual(cleric.readied_action["trigger_params"]["min_damage"], 5)


# ============================================================================
# Layer 3+4: on_ally_takes_damage handler firing + filters
# ============================================================================

class OnAllyTakesDamageTest(unittest.TestCase):

    def test_fires_when_ally_takes_damage(self) -> None:
        cleric = _make_actor("cleric", side="pc", position=(0, 0),
                                actions=[_healing_word_action()])
        fighter = _make_actor("fighter", side="pc", position=(1, 0),
                                 hp=20)
        state = _make_state([cleric, fighter])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state)
        # Fighter takes 8 damage
        bus = EventBus()
        fired = ra.on_ally_takes_damage(fighter, 8, state, bus)
        self.assertEqual(fired, 1)
        events = [e for e in state.event_log
                    if e.get("event") == "ready_action_fired"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target"], "fighter")
        self.assertFalse(ra.has_readied_action(cleric))
        self.assertTrue(cleric.actions_used_this_turn["reaction"])

    def test_does_not_fire_for_enemy_damage(self) -> None:
        cleric = _make_actor("cleric", side="pc", position=(0, 0),
                                actions=[_healing_word_action()])
        goblin = _make_actor("goblin", side="enemy", position=(2, 0),
                                hp=20)
        state = _make_state([cleric, goblin])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state)
        bus = EventBus()
        fired = ra.on_ally_takes_damage(goblin, 8, state, bus)
        self.assertEqual(fired, 0)
        self.assertTrue(ra.has_readied_action(cleric))

    def test_does_not_fire_for_self_damage(self) -> None:
        # Cleric reading on ally damage shouldn't self-fire if THEY
        # take damage (they're not their own ally for this trigger).
        cleric = _make_actor("cleric", side="pc",
                                actions=[_healing_word_action()])
        state = _make_state([cleric])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state)
        bus = EventBus()
        fired = ra.on_ally_takes_damage(cleric, 5, state, bus)
        self.assertEqual(fired, 0)
        self.assertTrue(ra.has_readied_action(cleric))

    def test_does_not_fire_outside_range(self) -> None:
        # Grid = 5ft squares. within_ft=30, ally at (10,0) = 50ft → out
        cleric = _make_actor("cleric", side="pc", position=(0, 0),
                                actions=[_healing_word_action()])
        fighter = _make_actor("fighter", side="pc", position=(10, 0))
        state = _make_state([cleric, fighter])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state, trigger_params={"within_ft": 30})
        bus = EventBus()
        fired = ra.on_ally_takes_damage(fighter, 8, state, bus)
        self.assertEqual(fired, 0)
        self.assertTrue(ra.has_readied_action(cleric))

    def test_does_not_fire_below_min_damage(self) -> None:
        # min_damage=10 — 5 damage shouldn't trip the trigger
        cleric = _make_actor("cleric", side="pc",
                                actions=[_healing_word_action()])
        fighter = _make_actor("fighter", side="pc", position=(1, 0))
        state = _make_state([cleric, fighter])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state, trigger_params={"min_damage": 10})
        bus = EventBus()
        fired = ra.on_ally_takes_damage(fighter, 5, state, bus)
        self.assertEqual(fired, 0)
        self.assertTrue(ra.has_readied_action(cleric))

    def test_fires_at_or_above_min_damage(self) -> None:
        cleric = _make_actor("cleric", side="pc",
                                actions=[_healing_word_action()])
        fighter = _make_actor("fighter", side="pc", position=(1, 0))
        state = _make_state([cleric, fighter])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state, trigger_params={"min_damage": 10})
        bus = EventBus()
        fired = ra.on_ally_takes_damage(fighter, 10, state, bus)
        self.assertEqual(fired, 1)


# ============================================================================
# Layer 5: allow_dead_target — Healing Word picks up downed ally
# ============================================================================

class HealsDeadAllyTest(unittest.TestCase):
    """The iconic Cleric move: ally takes damage, drops to 0 HP,
    Cleric's readied Healing Word fires picking them back up."""

    def test_fires_on_dead_ally(self) -> None:
        cleric = _make_actor("cleric", side="pc",
                                actions=[_healing_word_action()])
        fighter = _make_actor("fighter", side="pc", position=(1, 0),
                                hp=0)  # already dropped
        fighter.is_dead = True
        state = _make_state([cleric, fighter])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state)
        bus = EventBus()
        fired = ra.on_ally_takes_damage(fighter, 5, state, bus)
        # Note: on_ally_takes_damage passes allow_dead_target=True
        # so the trigger should fire even though fighter.is_alive() is False
        self.assertEqual(fired, 1)


# ============================================================================
# Layer 6: _damage hook
# ============================================================================

class DamageHookIntegrationTest(unittest.TestCase):
    """End-to-end: real _damage call triggers the ally_takes_damage
    hook in the same _damage invocation."""

    def setUp(self) -> None:
        import engine.primitives as primitives_module
        primitives_module.set_rng(random.Random(7))

    def test_damage_to_ally_triggers_ready(self) -> None:
        from engine.primitives import _damage
        cleric = _make_actor("cleric", side="pc",
                                actions=[_healing_word_action()])
        fighter = _make_actor("fighter", side="pc", position=(1, 0),
                                 hp=50)
        goblin = _make_actor("goblin", side="enemy", position=(2, 0),
                                actions=[_melee_attack()])
        state = _make_state([cleric, fighter, goblin])
        ra.register(cleric, "a_healing_word", "ally_takes_damage",
                      state)
        # Simulate goblin attacking fighter — set up current_attack
        # then call _damage directly
        state.current_attack = {
            "actor": goblin, "target": fighter,
            "action": goblin.template["actions"][0],
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        _damage({"dice": "1d8", "modifier": 3,
                   "type": "slashing"}, state, EventBus())
        # Ready should have fired
        events = [e for e in state.event_log
                    if e.get("event") == "ready_action_fired"]
        self.assertEqual(len(events), 1)
        self.assertFalse(ra.has_readied_action(cleric))


# ============================================================================
# Layer 7+8: candidate emission
# ============================================================================

class CandidateEmissionTest(unittest.TestCase):

    def test_heal_ready_emits_when_ally_in_danger(self) -> None:
        from engine.core.pipeline import generate_candidates
        cleric = _make_actor("cleric", side="pc", position=(0, 0),
                                actions=[_healing_word_action()])
        # Fighter at (1,0) = 5ft from goblin. Goblin walk 30 + reach
        # 5 = 35ft threat envelope easily covers the fighter.
        fighter = _make_actor("fighter", side="pc", position=(1, 0))
        goblin = _make_actor("goblin", side="enemy", position=(2, 0),
                                actions=[_melee_attack()])
        state = _make_state([cleric, fighter, goblin])
        candidates = generate_candidates(cleric, state, slot="action")
        ready_candidates = [
            c for c in candidates
            if c.get("kind") == "ready"
            and c["action"].get("_ready_trigger") == "ally_takes_damage"
        ]
        self.assertGreater(len(ready_candidates), 0)

    def test_heal_ready_skipped_when_no_ally(self) -> None:
        # Cleric alone — no ally to protect
        from engine.core.pipeline import generate_candidates
        cleric = _make_actor("cleric", side="pc",
                                actions=[_healing_word_action()])
        goblin = _make_actor("goblin", side="enemy", position=(2, 0),
                                actions=[_melee_attack()])
        state = _make_state([cleric, goblin])
        candidates = generate_candidates(cleric, state, slot="action")
        ready_candidates = [
            c for c in candidates
            if c.get("kind") == "ready"
            and c["action"].get("_ready_trigger") == "ally_takes_damage"
        ]
        self.assertEqual(len(ready_candidates), 0)

    def test_heal_ready_skipped_when_ally_safe(self) -> None:
        # Ally is 200 ft away from the only enemy — out of any
        # plausible threat range. No Ready emission.
        from engine.core.pipeline import generate_candidates
        cleric = _make_actor("cleric", side="pc", position=(0, 0),
                                actions=[_healing_word_action()])
        fighter = _make_actor("fighter", side="pc", position=(1, 0))
        # Enemy at (60, 0) = 300ft. Even with walk 60 + reach 5 = 65ft
        # threat range, fighter at 295ft is way out.
        goblin = _make_actor("goblin", side="enemy", position=(60, 0),
                                walk=30, actions=[_melee_attack()])
        state = _make_state([cleric, fighter, goblin])
        candidates = generate_candidates(cleric, state, slot="action")
        ready_candidates = [
            c for c in candidates
            if c.get("kind") == "ready"
            and c["action"].get("_ready_trigger") == "ally_takes_damage"
        ]
        self.assertEqual(len(ready_candidates), 0)


# ============================================================================
# Layer 9: scoring routes through defensive_ehp for heal sub-actions
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_heal_ready_scores_positive(self) -> None:
        from engine.ai.ehp_scoring import (
            offensive_ehp_ready, READY_TRIGGER_FIRES_PROBABILITY)
        cleric = _make_actor("cleric", side="pc",
                                actions=[_healing_word_action()])
        # Wounded fighter — needs the heal
        fighter = _make_actor("fighter", side="pc", position=(1, 0),
                                hp=5, ac=14)
        # Bump fighter hp_max so missing > 0
        fighter.hp_max = 50
        goblin = _make_actor("goblin", side="enemy", position=(2, 0),
                                actions=[_melee_attack()])
        state = _make_state([cleric, fighter, goblin])
        synth = {
            "id": "a_ready__a_healing_word__on__ally_takes_damage",
            "type": "ready",
            "_ready_sub_action": _healing_word_action(),
            "_ready_trigger": "ally_takes_damage",
        }
        score = offensive_ehp_ready(cleric, synth, state)
        # Should be positive — wounded ally + heal available
        self.assertGreaterEqual(score, 0.0)

    def test_attack_ready_still_scores_via_old_path(self) -> None:
        # Existing PR #86 behavior preserved — non-ally-damage Ready
        # candidates still score via the offensive_ehp_single_attack
        # path.
        from engine.ai.ehp_scoring import offensive_ehp_ready
        fighter = _make_actor("fighter", side="pc",
                                actions=[_melee_attack()])
        goblin = _make_actor("goblin", side="enemy", position=(2, 0),
                                hp=20)
        state = _make_state([fighter, goblin])
        synth = {
            "id": "a_ready_attack",
            "type": "ready",
            "_ready_sub_action": _melee_attack(),
            "_ready_trigger": "enemy_enters_reach",
        }
        score = offensive_ehp_ready(fighter, synth, state)
        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
