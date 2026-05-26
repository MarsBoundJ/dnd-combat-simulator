"""Opportunity Attack v1 tests — movement-triggered melee reactions.

Layers:
  1. find_oa_triggers — pure-data detection
     * Reactor's reach broken by movement (was-in / now-out)
     * Reactor with no melee weapon → no trigger
     * Reactor with reaction already used → no trigger
     * Dead / fled reactor → no trigger
     * Same-side actor → no trigger (no friendly fire OAs in v1)
  2. resolve_opportunity_attacks — orchestration
     * AE percentage gates (Optimal always fires, Reactive_only often)
     * Reaction slot marked used after firing
     * Mover dropped by OA → stop iterating; subsequent triggers skip
     * Position restoration after attack (mover ends at post-move position
       if alive)
  3. Runner integration — full encounter demonstrates OA firing during
     _move_to_engage and the mover may drop / pass turn after

Run via:
    python -m unittest tests.test_opportunity_attacks
"""
from __future__ import annotations

import random
import unittest

from engine.core.reactions import (
    find_oa_triggers, resolve_opportunity_attacks,
)
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Test helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy",
                hp: int = 30, ac: int = 15,
                position: tuple[int, int] = (0, 0),
                speed: int = 30,
                actions: list[dict] | None = None,
                presets: dict | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 14, "save": 2},
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
    if presets:
        template["behavior_profile"] = {"presets": presets}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _melee_attack(action_id: str = "a_sword", reach: int = 5,
                   bonus: int = 5, dice: str = "1d8",
                   modifier: int = 3) -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": reach}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


def _ranged_attack(action_id: str = "a_bow", range_ft: int = 80,
                    bonus: int = 5, dice: str = "1d8") -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "ranged", "bonus": bonus,
                          "range_ft": range_ft}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": 3, "type": "piercing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# find_oa_triggers — pure detection
# ============================================================================

class FindOATriggersTest(unittest.TestCase):

    def test_fires_when_mover_leaves_reactor_reach(self) -> None:
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_melee_attack(reach=5)])
        mover = _make_actor("m", side="enemy", position=(2, 0))   # 10ft post
        state = _state_with([reactor, mover])
        # Pre-position was (1, 0): 5 ft — in reach
        triggers = find_oa_triggers(mover, pre_position=(1, 0), state=state)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0][0].id, "r")

    def test_no_trigger_if_mover_stays_in_reach(self) -> None:
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_melee_attack(reach=5)])
        mover = _make_actor("m", side="enemy", position=(1, 1))   # 5ft post
        state = _state_with([reactor, mover])
        # Pre and post both in reach → no trigger
        triggers = find_oa_triggers(mover, pre_position=(1, 0), state=state)
        self.assertEqual(triggers, [])

    def test_no_trigger_if_mover_was_never_in_reach(self) -> None:
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_melee_attack(reach=5)])
        mover = _make_actor("m", side="enemy", position=(10, 0))
        state = _state_with([reactor, mover])
        # Pre was (8, 0): 40 ft — never in reach
        triggers = find_oa_triggers(mover, pre_position=(8, 0), state=state)
        self.assertEqual(triggers, [])

    def test_no_trigger_if_reactor_no_melee_weapon(self) -> None:
        """An archer with only a ranged weapon doesn't OA."""
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_ranged_attack(range_ft=80)])
        mover = _make_actor("m", side="enemy", position=(2, 0))
        state = _state_with([reactor, mover])
        triggers = find_oa_triggers(mover, pre_position=(1, 0), state=state)
        self.assertEqual(triggers, [],
                          "Ranged-only attacker shouldn't OA")

    def test_no_trigger_if_reactor_reaction_used(self) -> None:
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_melee_attack(reach=5)])
        reactor.actions_used_this_turn["reaction"] = True
        mover = _make_actor("m", side="enemy", position=(2, 0))
        state = _state_with([reactor, mover])
        triggers = find_oa_triggers(mover, pre_position=(1, 0), state=state)
        self.assertEqual(triggers, [])

    def test_no_trigger_from_same_side(self) -> None:
        """No friendly-fire OAs (when an ally moves past you)."""
        reactor = _make_actor("r", side="enemy", position=(0, 0),
                                actions=[_melee_attack(reach=5)])
        mover = _make_actor("m", side="enemy", position=(2, 0))
        state = _state_with([reactor, mover])
        triggers = find_oa_triggers(mover, pre_position=(1, 0), state=state)
        self.assertEqual(triggers, [])

    def test_no_trigger_from_dead_reactor(self) -> None:
        reactor = _make_actor("r", side="pc", position=(0, 0), hp=10,
                                actions=[_melee_attack(reach=5)])
        reactor.is_dead = True
        reactor.hp_current = 0
        mover = _make_actor("m", side="enemy", position=(2, 0))
        state = _state_with([reactor, mover])
        triggers = find_oa_triggers(mover, pre_position=(1, 0), state=state)
        self.assertEqual(triggers, [])

    def test_extended_reach_glaive(self) -> None:
        """A 10-ft reach weapon triggers OA at 10 ft, not 5."""
        glaive = _melee_attack(reach=10)
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[glaive])
        mover = _make_actor("m", side="enemy", position=(3, 0))   # 15ft post
        state = _state_with([reactor, mover])
        # Pre was (2, 0): 10 ft — in reach for glaive
        triggers = find_oa_triggers(mover, pre_position=(2, 0), state=state)
        self.assertEqual(len(triggers), 1)


# ============================================================================
# resolve_opportunity_attacks — orchestration
# ============================================================================

class ResolveOATest(unittest.TestCase):

    def _run_oa_event_setup(self, reactor_preset: str = "average"):
        """Build a minimal scene where mover left reactor's reach.
        Returns (mover, reactor, state)."""
        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_melee_attack(
                                    reach=5, bonus=10, dice="1d4", modifier=0)],
                                presets={"action_economy": reactor_preset})
        mover = _make_actor("m", side="enemy", position=(2, 0),
                              hp=20, ac=10)   # easy to hit
        state = _state_with([reactor, mover])
        return mover, reactor, state

    def test_optimal_preset_always_fires(self) -> None:
        from engine.core.events import EventBus
        from engine import primitives as primitives_module

        mover, reactor, state = self._run_oa_event_setup("optimal")
        primitives_module.set_rng(random.Random(1))
        # 20 seeds — Optimal (100%) should always fire
        for s in range(20):
            mover.hp_current = mover.hp_max
            reactor.actions_used_this_turn["reaction"] = False
            state.event_log = []
            fired = resolve_opportunity_attacks(
                mover, pre_position=(1, 0), state=state,
                event_bus=EventBus(),
                primitives=primitives_module.PrimitiveRegistry.with_defaults(),
                rng=random.Random(s),
            )
            self.assertEqual(fired, 1,
                              f"Optimal should always fire OA (seed {s})")

    def test_reactive_only_misses_some(self) -> None:
        """Reactive_only oa_reaction = 80% — over many seeds, some misses
        should occur."""
        from engine.core.events import EventBus
        from engine import primitives as primitives_module

        misses = 0
        for s in range(100):
            mover, reactor, state = self._run_oa_event_setup("reactive_only")
            primitives_module.set_rng(random.Random(s))
            fired = resolve_opportunity_attacks(
                mover, pre_position=(1, 0), state=state,
                event_bus=EventBus(),
                primitives=primitives_module.PrimitiveRegistry.with_defaults(),
                rng=random.Random(s),
            )
            if fired == 0:
                misses += 1
        # ~20% miss rate; tolerate 5-40%
        self.assertGreater(misses, 5,
                            f"Reactive_only should decline some OAs "
                            f"({misses}/100)")
        self.assertLess(misses, 40)

    def test_reaction_slot_marked_used_after_fire(self) -> None:
        from engine.core.events import EventBus
        from engine import primitives as primitives_module

        mover, reactor, state = self._run_oa_event_setup("optimal")
        primitives_module.set_rng(random.Random(1))
        self.assertFalse(reactor.actions_used_this_turn["reaction"])
        resolve_opportunity_attacks(
            mover, pre_position=(1, 0), state=state,
            event_bus=EventBus(),
            primitives=primitives_module.PrimitiveRegistry.with_defaults(),
            rng=random.Random(1),
        )
        self.assertTrue(reactor.actions_used_this_turn["reaction"],
                         "Reaction slot should be marked used after OA")

    def test_event_log_records_oa(self) -> None:
        from engine.core.events import EventBus
        from engine import primitives as primitives_module

        mover, reactor, state = self._run_oa_event_setup("optimal")
        primitives_module.set_rng(random.Random(1))
        resolve_opportunity_attacks(
            mover, pre_position=(1, 0), state=state,
            event_bus=EventBus(),
            primitives=primitives_module.PrimitiveRegistry.with_defaults(),
            rng=random.Random(1),
        )
        events = [e["event"] for e in state.event_log]
        self.assertIn("opportunity_attack_triggered", events)

    def test_mover_position_restored_if_alive(self) -> None:
        from engine.core.events import EventBus
        from engine import primitives as primitives_module

        mover, reactor, state = self._run_oa_event_setup("optimal")
        # Big HP so OA doesn't drop
        mover.hp_current = 200
        mover.hp_max = 200
        primitives_module.set_rng(random.Random(1))
        resolve_opportunity_attacks(
            mover, pre_position=(1, 0), state=state,
            event_bus=EventBus(),
            primitives=primitives_module.PrimitiveRegistry.with_defaults(),
            rng=random.Random(1),
        )
        self.assertEqual(mover.position, (2, 0),
                          "Mover position should be restored to post-move "
                          "after OA")

    def test_no_oa_if_no_trigger(self) -> None:
        """Mover that stays in reactor's reach triggers nothing."""
        from engine.core.events import EventBus
        from engine import primitives as primitives_module

        reactor = _make_actor("r", side="pc", position=(0, 0),
                                actions=[_melee_attack(reach=5)])
        mover = _make_actor("m", side="enemy", position=(1, 1))
        state = _state_with([reactor, mover])
        fired = resolve_opportunity_attacks(
            mover, pre_position=(1, 0), state=state,
            event_bus=EventBus(),
            primitives=primitives_module.PrimitiveRegistry.with_defaults(),
            rng=random.Random(1),
        )
        self.assertEqual(fired, 0)


# ============================================================================
# Runner integration — OA fires in a real encounter
# ============================================================================

class RunnerOAIntegrationTest(unittest.TestCase):

    def test_oa_fires_when_mover_leaves_guardian_reach(self) -> None:
        """Goblin starts within a polearm-wielding guardian's 10-ft
        reach (but the goblin's own 5-ft scimitar can't reach the
        guardian back). Goblin targets weakest_target (healer); to
        engage healer it must move out of guardian's reach, triggering
        an OA."""
        import random as _random
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        # Guardian has a glaive with 10-ft reach — covers the goblin's
        # starting square but extends beyond its own square's adjacency.
        guardian_glaive = _melee_attack("a_glaive", reach=10,
                                           bonus=8, dice="1d10", modifier=4)
        healer_mace = _melee_attack("a_mace", reach=5, bonus=3,
                                      dice="1d6", modifier=1)
        # Goblin has only a 5-ft scimitar — can NOT reach guardian (10 ft
        # away), and can NOT reach healer (15 ft away) without moving.
        goblin_scimitar = _melee_attack("a_scimitar", reach=5,
                                          bonus=4, dice="1d6", modifier=2)

        guardian = _make_actor("guardian", side="pc", hp=40, ac=18,
                                 position=(5, 0),
                                 actions=[guardian_glaive],
                                 presets={"action_economy": "optimal",
                                           "retreat": "ftd"},
                                 template_extras={"combat": {
                                     "initiative": {"modifier": 0, "score": 8},
                                 }})
        # Healer immobile (speed 0) — keeps the geometry stable so the
        # goblin has to actually move to engage her.
        healer = _make_actor("healer", side="pc", hp=15, ac=14,
                               position=(0, 0),
                               speed=0,
                               actions=[healer_mace],
                               presets={"retreat": "ftd"},
                               template_extras={"combat": {
                                   "initiative": {"modifier": 0, "score": 5},
                               }})
        # Goblin at (3, 0): 10 ft from guardian (within glaive reach),
        # 15 ft from healer. Targets weakest (healer at 15 HP). Must move
        # to engage, leaving guardian's reach → OA triggers.
        # Bigger HP so the OA + retaliations don't drop it before the
        # event log records the move. High init_mod to force goblin to
        # act before guardian gets a swing on its first turn.
        goblin = _make_actor("goblin", side="enemy", hp=40, ac=13,
                               position=(3, 0),
                               actions=[goblin_scimitar],
                               presets={"targeting": "weakest_target",
                                         "retreat": "ftd"},
                               template_extras={"combat": {
                                   "initiative": {"modifier": 20, "score": 30},
                               }})
        encounter = Encounter(id="oa_test",
                                actors=[guardian, healer, goblin])

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # The guardian should have triggered an OA against the goblin
        # at some point as the goblin moved past to reach the healer.
        oas = [e for e in state.event_log
                if e.get("event") == "opportunity_attack_triggered"
                and e.get("reactor") == "guardian"
                and e.get("mover") == "goblin"]
        self.assertGreater(len(oas), 0,
                            "Guardian should have OA-attacked the goblin "
                            "as it moved past")

    def test_ranged_attacker_does_not_oa_passing_enemy(self) -> None:
        """An archer can't OA — only melee weapons trigger reactions."""
        import random as _random
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        bow = _ranged_attack("a_bow", range_ft=80, bonus=5, dice="1d6")
        scimitar = _melee_attack("a_scim", reach=5, bonus=4, dice="1d6",
                                   modifier=2)

        archer = _make_actor("archer", side="pc", hp=30, ac=14,
                               position=(0, 0),
                               actions=[bow],
                               presets={"retreat": "ftd"},
                               template_extras={"combat": {
                                   "initiative": {"modifier": 3, "score": 17},
                               }})
        # Distant target to lure goblin past archer
        far_pc = _make_actor("far_pc", side="pc", hp=10, ac=10,
                              position=(0, 5),   # 25 ft from goblin starting
                              actions=[scimitar],
                              presets={"retreat": "ftd"},
                              template_extras={"combat": {
                                  "initiative": {"modifier": 0, "score": 3},
                              }})
        goblin = _make_actor("goblin", side="enemy", hp=14, ac=13,
                               position=(1, 0),
                               actions=[scimitar],
                               presets={"targeting": "weakest_target",
                                         "retreat": "ftd"},
                               template_extras={"combat": {
                                   "initiative": {"modifier": 2, "score": 14},
                               }})
        encounter = Encounter(id="ranged_no_oa",
                                actors=[archer, far_pc, goblin])

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Archer should never have triggered an OA
        archer_oas = [e for e in state.event_log
                       if e.get("event") == "opportunity_attack_triggered"
                       and e.get("reactor") == "archer"]
        self.assertEqual(len(archer_oas), 0,
                          "Archer with only ranged weapon should never OA")


if __name__ == "__main__":
    unittest.main()
