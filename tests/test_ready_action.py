"""Ready Action tests (PR #86) — first PR in the party-coordination arc.

RAW (PHB 2024 p.380):
  "You can hold an action to occur later. Take the Ready action on
  your turn, which lets you act using your reaction before the start
  of your next turn. First, you choose what perceivable circumstance
  will trigger your reaction. Then, you choose the action you will
  take in response to that trigger."

v1 ships two triggers: enemy_enters_reach + enemy_casts_spell.

Layers:
  1. Trigger vocabulary + register / discard / has_readied_action
  2. _ready_action primitive flips state correctly
  3. on_movement_completed fires Ready on enters_reach trigger
  4. on_spell_cast_initiated fires Ready on casts_spell trigger
  5. Reaction-economy: only fires if reaction slot available
  6. Discard on next own turn (RAW: not taken before next turn → lost)
  7. Candidate emission gating (no Ready when actor can close-and-attack)
  8. Candidate emission for outranged actor (Ready valid here)
  9. Score formula: expected_damage × trigger_fires_probability
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

def _melee_attack(action_id, *, reach=5, bonus=5, dice="1d8", mod=3):
    return {
        "id": action_id,
        "name": action_id,
        "type": "weapon_attack",
        "slot": "action",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "ability": "str",
                          "bonus": bonus, "reach_ft": reach}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": mod,
                          "type": "slashing"}},
        ],
    }


def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  actions=None, str_score=16, walk=30):
    abilities = {
        "str": {"score": str_score, "save": 3},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}",
        "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": list(actions or []),
    }
    return Actor(
        id=actor_id, name=actor_id, template=template,
        side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": walk}, position=position,
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
# Layer 1: trigger vocabulary + transitions
# ============================================================================

class TriggerVocabularyTest(unittest.TestCase):

    def test_known_triggers_set_contains_v1_pair(self) -> None:
        self.assertIn("enemy_enters_reach", ra.KNOWN_TRIGGERS)
        self.assertIn("enemy_casts_spell", ra.KNOWN_TRIGGERS)

    def test_register_unknown_trigger_raises(self) -> None:
        a = _make_actor("a1", actions=[_melee_attack("a_sword")])
        state = _make_state([a])
        with self.assertRaises(ValueError):
            ra.register(a, "a_sword", "ally_takes_damage", state)

    def test_register_sets_actor_state(self) -> None:
        a = _make_actor("a1", actions=[_melee_attack("a_sword")])
        state = _make_state([a])
        ra.register(a, "a_sword", "enemy_enters_reach", state,
                      trigger_params={"reach_ft": 5})
        self.assertTrue(ra.has_readied_action(a))
        self.assertEqual(a.readied_action["action_id"], "a_sword")
        self.assertEqual(a.readied_action["trigger"], "enemy_enters_reach")
        self.assertEqual(a.readied_action["trigger_params"]["reach_ft"], 5)
        self.assertEqual(a.readied_action["round_readied"], 1)

    def test_register_overwrites_prior_readied(self) -> None:
        a = _make_actor("a1", actions=[_melee_attack("a_sword"),
                                            _melee_attack("a_axe")])
        state = _make_state([a])
        ra.register(a, "a_sword", "enemy_enters_reach", state)
        ra.register(a, "a_axe", "enemy_casts_spell", state)
        self.assertEqual(a.readied_action["action_id"], "a_axe")
        self.assertEqual(a.readied_action["trigger"], "enemy_casts_spell")

    def test_discard_clears_and_logs(self) -> None:
        a = _make_actor("a1", actions=[_melee_attack("a_sword")])
        state = _make_state([a])
        ra.register(a, "a_sword", "enemy_enters_reach", state)
        ra.discard(a, state, reason="fired")
        self.assertFalse(ra.has_readied_action(a))
        discards = [e for e in state.event_log
                      if e.get("event") == "ready_action_discarded"]
        self.assertEqual(len(discards), 1)
        self.assertEqual(discards[0]["reason"], "fired")

    def test_discard_on_none_is_noop(self) -> None:
        a = _make_actor("a1")
        state = _make_state([a])
        ra.discard(a, state, reason="turn_start")
        # No log spam when there was nothing to discard
        discards = [e for e in state.event_log
                      if e.get("event") == "ready_action_discarded"]
        self.assertEqual(len(discards), 0)


# ============================================================================
# Layer 2: _ready_action primitive
# ============================================================================

class ReadyActionPrimitiveTest(unittest.TestCase):

    def test_primitive_sets_readied_action(self) -> None:
        from engine.primitives import _ready_action
        a = _make_actor("a1", actions=[_melee_attack("a_sword")])
        state = _make_state([a])
        state.current_attack = {"actor": a, "target": a,
                                  "action": {"id": "a_ready_test"}}
        bus = EventBus()
        _ready_action({
            "sub_action_id": "a_sword",
            "trigger": "enemy_enters_reach",
        }, state, bus)
        self.assertTrue(ra.has_readied_action(a))
        self.assertEqual(a.readied_action["action_id"], "a_sword")

    def test_primitive_missing_params_raises(self) -> None:
        from engine.primitives import _ready_action
        a = _make_actor("a1")
        state = _make_state([a])
        state.current_attack = {"actor": a, "target": a, "action": {}}
        bus = EventBus()
        with self.assertRaises(ValueError):
            _ready_action({"sub_action_id": "a_sword"}, state, bus)
        with self.assertRaises(ValueError):
            _ready_action({"trigger": "enemy_enters_reach"}, state, bus)


# ============================================================================
# Layer 3: enters_reach trigger
# ============================================================================

class EntersReachTriggerTest(unittest.TestCase):

    def test_fires_when_enemy_enters_reach(self) -> None:
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry

        attack = _melee_attack("a_sword", reach=5, bonus=10, dice="1d8")
        actor = _make_actor("guard", side="pc", position=(0, 0),
                              actions=[attack])
        # Grid units = 5ft squares per engine convention. Pre (2,0) =
        # 10ft from actor (out of 5ft reach); post (1,0) = 5ft (in).
        mover = _make_actor("goblin", side="enemy", position=(1, 0),
                              hp=20)
        state = _make_state([actor, mover])
        ra.register(actor, "a_sword", "enemy_enters_reach", state,
                      trigger_params={"reach_ft": 5})
        bus = EventBus()
        primitives = PrimitiveRegistry.with_defaults()
        fired = ra.on_movement_completed(
            mover, pre_position=(2, 0), state=state,
            event_bus=bus, primitives=primitives,
        )
        self.assertEqual(fired, 1)
        events = [e for e in state.event_log
                    if e.get("event") == "ready_action_fired"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "guard")
        self.assertEqual(events[0]["target"], "goblin")
        # Readied action should be discarded after firing
        self.assertFalse(ra.has_readied_action(actor))
        # Reaction slot consumed
        self.assertTrue(actor.actions_used_this_turn["reaction"])

    def test_does_not_fire_when_already_in_reach(self) -> None:
        # Mover was already in reach (no transition) → no trigger
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry

        attack = _melee_attack("a_sword", reach=5, bonus=10)
        actor = _make_actor("guard", side="pc", position=(0, 0),
                              actions=[attack])
        mover = _make_actor("goblin", side="enemy", position=(5, 0),
                              hp=20)
        state = _make_state([actor, mover])
        ra.register(actor, "a_sword", "enemy_enters_reach", state,
                      trigger_params={"reach_ft": 5})
        bus = EventBus()
        primitives = PrimitiveRegistry.with_defaults()
        # Pre-position 5ft (in reach); post 5ft (still in reach) → no
        # transition INTO reach.
        fired = ra.on_movement_completed(
            mover, pre_position=(5, 0), state=state,
            event_bus=bus, primitives=primitives,
        )
        self.assertEqual(fired, 0)
        self.assertTrue(ra.has_readied_action(actor))

    def test_does_not_fire_for_same_side_movement(self) -> None:
        # Ally moving doesn't trigger enemy_enters_reach
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry

        attack = _melee_attack("a_sword", reach=5, bonus=10)
        actor = _make_actor("guard", side="pc", position=(0, 0),
                              actions=[attack])
        ally = _make_actor("ranger", side="pc", position=(5, 0))
        state = _make_state([actor, ally])
        ra.register(actor, "a_sword", "enemy_enters_reach", state)
        bus = EventBus()
        primitives = PrimitiveRegistry.with_defaults()
        fired = ra.on_movement_completed(
            ally, pre_position=(15, 0), state=state,
            event_bus=bus, primitives=primitives,
        )
        self.assertEqual(fired, 0)
        self.assertTrue(ra.has_readied_action(actor))


# ============================================================================
# Layer 4: casts_spell trigger
# ============================================================================

class CastsSpellTriggerTest(unittest.TestCase):

    def test_fires_when_enemy_casts_within_range(self) -> None:
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry

        attack = _melee_attack("a_bow", reach=80, bonus=6)
        actor = _make_actor("archer", side="pc", position=(0, 0),
                              actions=[attack])
        # Grid = 5ft squares. (6,0) = 30ft, within 60ft trigger window.
        caster = _make_actor("warlock", side="enemy", position=(6, 0),
                                hp=20)
        state = _make_state([actor, caster])
        ra.register(actor, "a_bow", "enemy_casts_spell", state,
                      trigger_params={"within_ft": 60})
        bus = EventBus()
        primitives = PrimitiveRegistry.with_defaults()
        fired = ra.on_spell_cast_initiated(
            caster, state, event_bus=bus, primitives=primitives,
        )
        self.assertEqual(fired, 1)
        self.assertFalse(ra.has_readied_action(actor))
        self.assertTrue(actor.actions_used_this_turn["reaction"])

    def test_does_not_fire_when_caster_out_of_range(self) -> None:
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry

        attack = _melee_attack("a_bow", reach=80, bonus=6)
        actor = _make_actor("archer", side="pc", position=(0, 0),
                              actions=[attack])
        # within_ft=60, caster at (13,0) = 65ft → out of trigger range
        caster = _make_actor("warlock", side="enemy", position=(13, 0))
        state = _make_state([actor, caster])
        ra.register(actor, "a_bow", "enemy_casts_spell", state,
                      trigger_params={"within_ft": 60})
        bus = EventBus()
        primitives = PrimitiveRegistry.with_defaults()
        fired = ra.on_spell_cast_initiated(
            caster, state, event_bus=bus, primitives=primitives,
        )
        self.assertEqual(fired, 0)
        self.assertTrue(ra.has_readied_action(actor))


# ============================================================================
# Layer 5: reaction-economy interaction
# ============================================================================

class ReactionEconomyTest(unittest.TestCase):

    def test_does_not_fire_when_reaction_already_used(self) -> None:
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry

        attack = _melee_attack("a_sword", reach=5, bonus=10)
        actor = _make_actor("guard", side="pc", position=(0, 0),
                              actions=[attack])
        actor.actions_used_this_turn["reaction"] = True  # used elsewhere
        # 5ft squares: post (1,0)=5ft, pre (2,0)=10ft
        mover = _make_actor("goblin", side="enemy", position=(1, 0))
        state = _make_state([actor, mover])
        ra.register(actor, "a_sword", "enemy_enters_reach", state)
        bus = EventBus()
        primitives = PrimitiveRegistry.with_defaults()
        fired = ra.on_movement_completed(
            mover, pre_position=(2, 0), state=state,
            event_bus=bus, primitives=primitives,
        )
        self.assertEqual(fired, 0)
        # Ready stays held — reaction wasn't available to fire it
        self.assertTrue(ra.has_readied_action(actor))
        skips = [e for e in state.event_log
                   if e.get("event") == "ready_action_skipped"]
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]["reason"], "reaction_already_used")


# ============================================================================
# Layer 6: discard on next own turn (RAW)
# ============================================================================

class DiscardOnNextTurnTest(unittest.TestCase):

    def test_reset_turn_discards_readied_action(self) -> None:
        a = _make_actor("a1", actions=[_melee_attack("a_sword")])
        state = _make_state([a])
        ra.register(a, "a_sword", "enemy_enters_reach", state)
        self.assertTrue(ra.has_readied_action(a))
        a.reset_turn()
        self.assertFalse(ra.has_readied_action(a))
        # reset_turn stashes the discard for the runner to log;
        # verify the sentinel attribute was set
        self.assertIsNotNone(getattr(a, "_ready_discarded_this_reset", None))


# ============================================================================
# Layer 7+8: candidate emission gating
# ============================================================================

class CandidateEmissionTest(unittest.TestCase):

    def test_no_ready_when_actor_can_close_and_attack(self) -> None:
        # Goblin with scimitar (5ft reach) + walk 30: any enemy within
        # 35ft is reachable this turn → no Ready candidates.
        # Grid = 5ft squares. PC at (5,0) = 25ft away — within
        # walk+reach window.
        from engine.core.pipeline import generate_candidates
        goblin = _make_actor("goblin", side="enemy", position=(0, 0),
                                actions=[_melee_attack("a_scim", reach=5)])
        pc = _make_actor("pc", side="pc", position=(5, 0))
        state = _make_state([goblin, pc])
        candidates = generate_candidates(goblin, state, slot="action")
        ready_candidates = [c for c in candidates if c.get("kind") == "ready"]
        self.assertEqual(ready_candidates, [])

    def test_ready_emits_when_actor_is_outranged(self) -> None:
        # PC fighter at (0,0) with greataxe (5ft melee reach), walk 30.
        # Enemy at (10,0) = 50ft away with walk 30. PC walk+reach = 35ft
        # — can't close-and-attack (35 < 50). Enemy can plausibly enter
        # reach (walk 30 + actor reach 5 + 5 fudge = 40 < 50... not quite).
        # Bump enemy walk to 60: 60+5+5 = 70 >= 50 → enters_reach plausible.
        from engine.core.pipeline import generate_candidates
        axe = _melee_attack("a_axe", reach=5, bonus=6, dice="1d12")
        pc = _make_actor("pc", side="pc", position=(0, 0), walk=30,
                            actions=[axe])
        enemy = _make_actor("enemy", side="enemy", position=(10, 0),
                              walk=60)
        state = _make_state([pc, enemy])
        candidates = generate_candidates(pc, state, slot="action")
        ready_candidates = [c for c in candidates if c.get("kind") == "ready"]
        self.assertGreater(len(ready_candidates), 0)


class CandidateEmissionEntersReachPlausibleTest(unittest.TestCase):

    def test_ready_emits_enters_reach_when_enemy_can_close(self) -> None:
        # Grid = 5ft squares. PC (0,0), enemy (10,0) = 50ft away.
        # PC walk 30 + reach 5 = 35ft → can't close+attack.
        # Enemy walk 60 + actor reach 5 + 5 fudge = 70ft >= 50 → enters_reach
        # plausibility passes.
        from engine.core.pipeline import generate_candidates
        axe = _melee_attack("a_axe", reach=5, bonus=6, dice="1d12")
        pc = _make_actor("pc", side="pc", position=(0, 0), walk=30,
                            actions=[axe])
        enemy = _make_actor("enemy", side="enemy", position=(10, 0),
                               walk=60)
        state = _make_state([pc, enemy])
        candidates = generate_candidates(pc, state, slot="action")
        enters_reach_candidates = [
            c for c in candidates
            if c.get("kind") == "ready"
            and c["action"]["_ready_trigger"] == "enemy_enters_reach"
        ]
        self.assertGreater(len(enters_reach_candidates), 0)


# ============================================================================
# Layer 9: scoring formula
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_score_is_discounted_expected_damage(self) -> None:
        from engine.ai.ehp_scoring import (
            offensive_ehp_ready, offensive_ehp_single_attack,
            READY_TRIGGER_FIRES_PROBABILITY,
        )
        axe = _melee_attack("a_axe", reach=5, bonus=6, dice="1d12", mod=4)
        pc = _make_actor("pc", side="pc", position=(0, 0), actions=[axe])
        enemy = _make_actor("enemy", side="enemy", position=(100, 0), hp=20)
        state = _make_state([pc, enemy])
        synth = {
            "id": "a_ready__a_axe__on__enemy_enters_reach",
            "type": "ready",
            "_ready_sub_action": axe,
            "_ready_trigger": "enemy_enters_reach",
        }
        score = offensive_ehp_ready(pc, synth, state)
        baseline = offensive_ehp_single_attack(pc, enemy, axe, state)
        self.assertAlmostEqual(
            score, baseline * READY_TRIGGER_FIRES_PROBABILITY,
            places=4)

    def test_zero_score_when_no_living_enemies(self) -> None:
        from engine.ai.ehp_scoring import offensive_ehp_ready
        axe = _melee_attack("a_axe")
        pc = _make_actor("pc", actions=[axe])
        state = _make_state([pc])
        synth = {"type": "ready", "_ready_sub_action": axe}
        self.assertEqual(offensive_ehp_ready(pc, synth, state), 0.0)


if __name__ == "__main__":
    unittest.main()
