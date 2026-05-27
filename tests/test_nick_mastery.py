"""Nick weapon mastery tests (PR #57).

Layers:
  1. `nick` is in KNOWN_MASTERIES (not deferred)
  2. _nick_active helper:
     - actor knows nick + off-hand has nick → True
     - actor knows nick + primary light has nick → True
     - actor knows nick + neither weapon has nick → False
     - actor does NOT know nick → always False
     - non-light primary with nick → does not qualify primary path
     - ranged "light" primary with nick → does not qualify
  3. build_pc_template integration:
     - Nick active → off-hand slot=free, nick_active=true on action
     - Nick NOT active (actor doesn't know nick) → off-hand stays
       slot=bonus_action
     - Nick NOT active (no weapon has nick) → off-hand stays
       slot=bonus_action
     - No off-hand weapon → no action emitted (regardless of Nick)
  4. apply_mastery_effects: passing mastery_params with id=nick is
     a clean no-op (it's not a per-attack effect; dispatch falls
     through)
  5. Runner free-phase end-to-end:
     - Free action fires automatically after main slot
     - free_action_fired event logged
     - Free action without in-reach enemy → free_action_skipped event
     - Free action doesn't consume action or bonus_action slot

Run via:
    python -m unittest tests.test_nick_mastery
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.core.weapon_masteries import (
    DEFERRED_MASTERIES, KNOWN_MASTERIES,
    apply_mastery_effects,
)
from engine.pc_schema import (
    _nick_active, build_pc_template,
)


# ============================================================================
# Mock registry (mirrors test_two_weapon_fighting)
# ============================================================================

class _MockRegistry:
    def __init__(self, classes):
        self._classes = classes
    def get(self, etype, eid):
        if etype != "class":
            raise KeyError(etype)
        if eid not in self._classes:
            raise KeyError(eid)
        return self._classes[eid]


def _fighter_class_def():
    return {
        "id": "c_fighter", "name": "Fighter",
        "core_traits": {"hit_die": "d10",
                         "save_proficiencies": ["strength", "constitution"]},
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": ["f_fighting_style", "f_second_wind"],
              "class_resources": {"second_wind_uses": 2,
                                       "weapon_mastery_count": 3}},
        ],
    }


def _registry():
    return _MockRegistry({"c_fighter": _fighter_class_def()})


def _shortsword(id_="a_shortsword", mastery=None):
    w = {"id": id_, "name": "Shortsword",
          "attack_ability": "str", "damage_dice": "1d6",
          "damage_type": "piercing", "reach_ft": 5,
          "light": True}
    if mastery:
        w["mastery"] = mastery
    return w


def _longsword(mastery=None):
    w = {"id": "a_longsword", "name": "Longsword",
          "attack_ability": "str", "damage_dice": "1d8",
          "damage_type": "slashing", "reach_ft": 5}
    if mastery:
        w["mastery"] = mastery
    return w


def _base_pc_spec(weapons=None, off_hand=None, masteries=None):
    spec = {
        "class": "c_fighter", "level": 1,
        "ability_scores": {"str": 16, "dex": 14, "con": 14,
                            "int": 10, "wis": 10, "cha": 10},
        "weapons": weapons if weapons is not None else [_shortsword()],
    }
    if off_hand is not None:
        spec["off_hand_weapon"] = off_hand
    if masteries is not None:
        spec["weapon_masteries"] = masteries
    return spec


# ============================================================================
# Layer 1: nick is KNOWN
# ============================================================================

class NickKnownTest(unittest.TestCase):

    def test_nick_in_known(self) -> None:
        self.assertIn("nick", KNOWN_MASTERIES)

    def test_nick_not_in_deferred(self) -> None:
        self.assertNotIn("nick", DEFERRED_MASTERIES)


# ============================================================================
# Layer 2: _nick_active helper
# ============================================================================

class NickActiveHelperTest(unittest.TestCase):

    def test_actor_knows_nick_off_hand_has_nick(self) -> None:
        off_hand = _shortsword("a_off", mastery="nick")
        primary = _shortsword("a_main")
        self.assertTrue(_nick_active(off_hand, [primary], ["nick"]))

    def test_actor_knows_nick_primary_has_nick(self) -> None:
        off_hand = _shortsword("a_off")
        primary = _shortsword("a_main", mastery="nick")
        self.assertTrue(_nick_active(off_hand, [primary], ["nick"]))

    def test_actor_knows_nick_neither_has_nick(self) -> None:
        off_hand = _shortsword("a_off")
        primary = _shortsword("a_main")
        self.assertFalse(_nick_active(off_hand, [primary], ["nick"]))

    def test_actor_does_NOT_know_nick(self) -> None:
        off_hand = _shortsword("a_off", mastery="nick")
        primary = _shortsword("a_main", mastery="nick")
        # Actor's masteries list omits nick
        self.assertFalse(_nick_active(off_hand, [primary], ["vex"]))

    def test_empty_masteries_list(self) -> None:
        off_hand = _shortsword("a_off", mastery="nick")
        self.assertFalse(_nick_active(off_hand, [_shortsword()], []))

    def test_empty_masteries_none(self) -> None:
        off_hand = _shortsword("a_off", mastery="nick")
        self.assertFalse(_nick_active(off_hand, [_shortsword()], None))

    def test_primary_must_be_light(self) -> None:
        # Longsword (non-light) with nick mastery shouldn't qualify
        # the primary path. Off-hand without nick.
        off_hand = _shortsword("a_off")
        # Longsword with nick — non-light
        non_light = _longsword(mastery="nick")
        self.assertFalse(_nick_active(off_hand, [non_light], ["nick"]))

    def test_primary_must_be_melee(self) -> None:
        # Ranged "light" weapon with nick shouldn't qualify via primary.
        off_hand = _shortsword("a_off")
        ranged = {"id": "a_lc", "name": "LC",
                    "attack_ability": "dex", "damage_dice": "1d6",
                    "damage_type": "piercing",
                    "range_ft": 80, "light": True, "mastery": "nick"}
        self.assertFalse(_nick_active(off_hand, [ranged], ["nick"]))


# ============================================================================
# Layer 3: build_pc_template integration
# ============================================================================

class BuildTemplateNickTest(unittest.TestCase):

    def test_nick_active_off_hand_slot_free(self) -> None:
        spec = _base_pc_spec(
            weapons=[_shortsword("a_main", mastery="nick")],
            off_hand=_shortsword("a_off", mastery="nick"),
            masteries=["nick"])
        template = build_pc_template(spec, _registry())
        off_hand_action = next(a for a in template["actions"]
                                  if a.get("id", "").endswith("_offhand"))
        self.assertEqual(off_hand_action["slot"], "free")
        self.assertTrue(off_hand_action.get("nick_active"))

    def test_nick_inactive_no_mastery_known(self) -> None:
        # Off-hand has Nick but actor doesn't know it → stays bonus
        spec = _base_pc_spec(
            weapons=[_shortsword("a_main")],
            off_hand=_shortsword("a_off", mastery="nick"),
            masteries=["vex"])    # know Vex, not Nick
        template = build_pc_template(spec, _registry())
        off_hand_action = next(a for a in template["actions"]
                                  if a.get("id", "").endswith("_offhand"))
        self.assertEqual(off_hand_action["slot"], "bonus_action")
        self.assertFalse(off_hand_action.get("nick_active"))

    def test_nick_inactive_no_weapon_has_nick(self) -> None:
        # Actor knows Nick but neither weapon has it → stays bonus
        spec = _base_pc_spec(
            weapons=[_shortsword("a_main")],
            off_hand=_shortsword("a_off"),
            masteries=["nick"])
        template = build_pc_template(spec, _registry())
        off_hand_action = next(a for a in template["actions"]
                                  if a.get("id", "").endswith("_offhand"))
        self.assertEqual(off_hand_action["slot"], "bonus_action")

    def test_no_off_hand_no_off_hand_action(self) -> None:
        spec = _base_pc_spec(masteries=["nick"])
        template = build_pc_template(spec, _registry())
        off_hand_actions = [a for a in template["actions"]
                              if a.get("id", "").endswith("_offhand")]
        self.assertEqual(len(off_hand_actions), 0)


# ============================================================================
# Layer 4: apply_mastery_effects with Nick is a no-op
# ============================================================================

def _make_actor(actor_id="a"):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side="pc",
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities,
                  weapon_masteries=["nick"])


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


class NickDispatchNoOpTest(unittest.TestCase):

    def test_nick_dispatch_no_modifiers_added(self) -> None:
        actor = _make_actor("rogue")
        target = _make_actor("ogre")
        target.side = "enemy"
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "nick", "ability_mod": 3,
                                  "damage_type": "piercing", "save_dc": 13},
                                 actor, target, "hit", state)
        # No modifiers added to actor or target
        self.assertEqual(len(actor.active_modifiers), 0)
        self.assertEqual(len(target.active_modifiers), 0)
        # No events
        self.assertEqual(len(state.event_log), 0)


# ============================================================================
# Layer 5: Runner free-phase end-to-end
# ============================================================================

class FreePhaseTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def _make_full_actor(self, actor_id, *, side="pc", position=(0, 0),
                            free_actions=None, normal_actions=None):
        """Build an Actor with both normal and free-slot actions for
        the runner free-phase test."""
        abilities = {k: {"score": 14 if k == "str" else 10, "save": 0}
                      for k in ("str", "dex", "con",
                                 "int", "wis", "cha")}
        actions = list(normal_actions or [])
        actions.extend(list(free_actions or []))
        template = {"id": f"tpl_{actor_id}", "name": actor_id,
                     "abilities": abilities,
                     "cr": {"value": 0, "xp": 0,
                             "proficiency_bonus": 2},
                     "actions": actions}
        return Actor(id=actor_id, name=actor_id, template=template,
                      side=side,
                      hp_current=30, hp_max=30, ac=14,
                      speed={"walk": 30}, position=position,
                      abilities=abilities)

    def test_free_phase_fires_auto(self) -> None:
        from engine.core.runner import EncounterRunner
        free_attack = {
            "id": "a_offhand_nick", "name": "Off-Hand (Nick)",
            "type": "weapon_attack", "slot": "free",
            "nick_active": True,
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "1d6", "modifier": 0,
                              "type": "piercing"},
                  "when": {"event": "damage_roll",
                            "condition": "combat.attack_state == hit"}},
            ],
        }
        actor = self._make_full_actor("rogue",
                                          free_actions=[free_attack])
        enemy = self._make_full_actor("dummy", side="enemy",
                                          position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        # free_action_fired event logged
        fire_events = [e for e in state.event_log
                          if e.get("event") == "free_action_fired"]
        self.assertEqual(len(fire_events), 1)
        self.assertEqual(fire_events[0]["action"], "a_offhand_nick")

    def test_free_phase_no_in_reach_enemy(self) -> None:
        from engine.core.runner import EncounterRunner
        free_attack = {
            "id": "a_offhand_nick", "name": "Off-Hand",
            "type": "weapon_attack", "slot": "free",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
            ],
        }
        actor = self._make_full_actor("rogue",
                                          free_actions=[free_attack])
        enemy = self._make_full_actor("dummy", side="enemy",
                                          position=(20, 0))    # out of reach
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        skip_events = [e for e in state.event_log
                          if e.get("event") == "free_action_skipped"]
        self.assertEqual(len(skip_events), 1)

    def test_free_phase_doesnt_consume_action_slot(self) -> None:
        from engine.core.runner import EncounterRunner
        free_attack = {
            "id": "a_offhand_nick", "name": "Off-Hand",
            "type": "weapon_attack", "slot": "free",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
            ],
        }
        actor = self._make_full_actor("rogue",
                                          free_actions=[free_attack])
        enemy = self._make_full_actor("dummy", side="enemy",
                                          position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        # Neither main nor bonus action slot consumed
        self.assertFalse(actor.actions_used_this_turn.get("action"))
        self.assertFalse(actor.actions_used_this_turn.get("bonus_action"))

    def test_no_free_actions_silent_skip(self) -> None:
        from engine.core.runner import EncounterRunner
        actor = self._make_full_actor("rogue")   # no actions at all
        enemy = self._make_full_actor("dummy", side="enemy",
                                          position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        # No events at all
        self.assertEqual(len(state.event_log), 0)

    def test_free_phase_no_double_fire(self) -> None:
        """Calling _run_free_phase twice doesn't double-fire."""
        from engine.core.runner import EncounterRunner
        free_attack = {
            "id": "a_offhand_nick", "name": "Off-Hand",
            "type": "weapon_attack", "slot": "free",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
            ],
        }
        actor = self._make_full_actor("rogue",
                                          free_actions=[free_attack])
        enemy = self._make_full_actor("dummy", side="enemy",
                                          position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        runner._run_free_phase(actor, state)
        fire_events = [e for e in state.event_log
                          if e.get("event") == "free_action_fired"]
        # Only one fire across two calls (per-turn dedup)
        self.assertEqual(len(fire_events), 1)


if __name__ == "__main__":
    unittest.main()
