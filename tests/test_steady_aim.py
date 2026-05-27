"""Steady Aim tests (PR #80).

Layers:
  1. steady_aim primitive registers advantage attack_modifier
  2. steady_aim primitive sets moved_this_turn = True
  3. steady_aim primitive logs steady_aim_taken event
  4. Modifier lifetime: consumes on owner's next attack
  5. Self-targeted recognition for defensive_buff dedup
  6. AI scoring: returns positive value when enemies present
  7. AI scoring: returns 0 when no enemies
  8. Pipeline filter: requires_no_movement blocks candidate after move
  9. Pipeline filter: candidate emits when actor hasn't moved
 10. pc_schema: Rogue L3+ gets a_steady_aim action
 11. pc_schema: Rogue L1/L2 does NOT get a_steady_aim
 12. f_steady_aim YAML loads
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
from engine.core import pipeline
from engine.core.basic_actions import is_self_targeted_defensive_buff
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _steady_aim, _attack_roll


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_rogue(actor_id="rogue", *, level=3, position=(0, 0)):
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 18, "save": 4},
        "con": {"score": 14, "save": 2},
        "int": {"score": 12, "save": 1},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [
            {"id": "a_rapier", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll",
                    "params": {"kind": "melee", "ability": "dex",
                                 "bonus": 6, "reach_ft": 5,
                                 "finesse": True}},
                  {"primitive": "damage",
                    "params": {"dice": "1d8", "modifier": 4,
                                 "type": "piercing"}},
              ]},
        ],
        "levels": {"rogue": level},
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side="pc",
        hp_current=25, hp_max=25, ac=15,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_target(actor_id="dummy", *, position=(1, 0), side="enemy",
                   hp=100):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=14,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1+2+3: steady_aim primitive
# ============================================================================

class SteadyAimPrimitiveTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_steady_aim_registers_advantage_modifier(self) -> None:
        actor = _make_rogue()
        state = _make_state([actor])
        state.current_attack = {"actor": actor, "target": actor,
                                  "action": {"id": "a_steady_aim"}}
        _steady_aim({}, state, EventBus())
        # Check the actor has an attack_modifier with advantage
        adv_mods = [m for m in actor.active_modifiers
                      if m.get("primitive") == "attack_modifier"
                      and (m.get("params") or {}).get("modifier") == "advantage"]
        self.assertEqual(len(adv_mods), 1)

    def test_steady_aim_sets_moved_this_turn(self) -> None:
        actor = _make_rogue()
        actor.moved_this_turn = False
        state = _make_state([actor])
        state.current_attack = {"actor": actor, "target": actor,
                                  "action": {"id": "a_steady_aim"}}
        _steady_aim({}, state, EventBus())
        self.assertTrue(actor.moved_this_turn)

    def test_steady_aim_logs_event(self) -> None:
        actor = _make_rogue()
        state = _make_state([actor])
        state.current_attack = {"actor": actor, "target": actor,
                                  "action": {"id": "a_steady_aim"}}
        _steady_aim({}, state, EventBus())
        events = [e for e in state.event_log
                    if e.get("event") == "steady_aim_taken"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "rogue")


# ============================================================================
# Layer 4: modifier consumes on next attack
# ============================================================================

class SteadyAimLifetimeTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_advantage_consumed_on_next_attack(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(1, 0))
        state = _make_state([attacker, target])
        # Apply Steady Aim
        state.current_attack = {"actor": attacker, "target": target,
                                  "action": {"id": "a_steady_aim"}}
        _steady_aim({}, state, EventBus())
        # One advantage modifier registered
        adv_mods_before = [m for m in attacker.active_modifiers
                              if m.get("primitive") == "attack_modifier"]
        self.assertEqual(len(adv_mods_before), 1)
        # Run one attack — modifier should consume
        attack_action = attacker.template["actions"][0]
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": attack_action, "state": None,
            "had_advantage": False, "had_disadvantage": False,
        }
        _attack_roll({"kind": "melee", "ability": "dex",
                       "bonus": 6, "reach_ft": 5, "finesse": True},
                      state, EventBus())
        # Modifier should be gone (per_owner_attack lifetime consumed)
        adv_mods_after = [m for m in attacker.active_modifiers
                            if m.get("primitive") == "attack_modifier"]
        self.assertEqual(len(adv_mods_after), 0)


# ============================================================================
# Layer 5: self-targeted recognition
# ============================================================================

class SteadyAimSelfTargetedTest(unittest.TestCase):

    def test_steady_aim_recognized_as_self_targeted(self) -> None:
        action = {
            "id": "a_steady_aim", "type": "defensive_buff",
            "slot": "bonus_action",
            "pipeline": [{"primitive": "steady_aim", "params": {}}],
        }
        self.assertTrue(is_self_targeted_defensive_buff(action))


# ============================================================================
# Layer 6+7: AI scoring
# ============================================================================

class SteadyAimScoringTest(unittest.TestCase):

    def test_scores_positive_when_enemies_present(self) -> None:
        attacker = _make_rogue()
        target = _make_target(position=(1, 0))
        state = _make_state([attacker, target])
        action = {
            "id": "a_steady_aim", "type": "defensive_buff",
            "pipeline": [{"primitive": "steady_aim", "params": {}}],
        }
        score = defensive_ehp_defensive_buff(attacker, attacker,
                                                  action, state)
        self.assertGreater(score, 0)

    def test_scores_zero_when_no_enemies(self) -> None:
        attacker = _make_rogue()
        state = _make_state([attacker])
        action = {
            "id": "a_steady_aim", "type": "defensive_buff",
            "pipeline": [{"primitive": "steady_aim", "params": {}}],
        }
        score = defensive_ehp_defensive_buff(attacker, attacker,
                                                  action, state)
        self.assertEqual(score, 0.0)


# ============================================================================
# Layer 8+9: pipeline filter (requires_no_movement)
# ============================================================================

class SteadyAimPipelineFilterTest(unittest.TestCase):

    def test_filtered_out_after_movement(self) -> None:
        attacker = _make_rogue()
        attacker.moved_this_turn = True
        target = _make_target(position=(1, 0))
        # Add the steady aim action to the actor's template
        attacker.template["actions"].append({
            "id": "a_steady_aim",
            "name": "Steady Aim",
            "type": "defensive_buff",
            "slot": "bonus_action",
            "requires_no_movement": True,
            "pipeline": [{"primitive": "steady_aim", "params": {}}],
        })
        state = _make_state([attacker, target])
        candidates = pipeline.generate_candidates(attacker, state,
                                                      slot="bonus_action")
        sa_candidates = [c for c in candidates
                           if c.get("action", {}).get("id") == "a_steady_aim"]
        self.assertEqual(len(sa_candidates), 0)

    def test_emits_when_actor_has_not_moved(self) -> None:
        attacker = _make_rogue()
        attacker.moved_this_turn = False
        target = _make_target(position=(1, 0))
        attacker.template["actions"].append({
            "id": "a_steady_aim",
            "name": "Steady Aim",
            "type": "defensive_buff",
            "slot": "bonus_action",
            "requires_no_movement": True,
            "pipeline": [{"primitive": "steady_aim", "params": {}}],
        })
        state = _make_state([attacker, target])
        candidates = pipeline.generate_candidates(attacker, state,
                                                      slot="bonus_action")
        sa_candidates = [c for c in candidates
                           if c.get("action", {}).get("id") == "a_steady_aim"]
        self.assertEqual(len(sa_candidates), 1)


# ============================================================================
# Layer 10+11: pc_schema integration
# ============================================================================

class PcSchemaSteadyAimTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def _build(self, level):
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": f"rogue{level}",
            "class": "c_rogue",
            "level": level,
            "ability_scores": {"str": 8, "dex": 18, "con": 14,
                                 "int": 12, "wis": 10, "cha": 10},
            "weapons": [{"id": "rapier", "name": "Rapier",
                          "damage_dice": "1d8",
                          "damage_type": "piercing",
                          "attack_ability": "dex", "finesse": True}],
        }
        return build_pc_template(pc_spec, self.registry)

    def test_rogue_l3_has_steady_aim(self) -> None:
        template = self._build(3)
        ids = {a.get("id") for a in template["actions"]}
        self.assertIn("a_steady_aim", ids)

    def test_rogue_l1_does_not_have_steady_aim(self) -> None:
        template = self._build(1)
        ids = {a.get("id") for a in template["actions"]}
        self.assertNotIn("a_steady_aim", ids)

    def test_rogue_l2_does_not_have_steady_aim(self) -> None:
        template = self._build(2)
        ids = {a.get("id") for a in template["actions"]}
        self.assertNotIn("a_steady_aim", ids)

    def test_steady_aim_action_shape(self) -> None:
        template = self._build(5)
        sa = next(a for a in template["actions"]
                       if a.get("id") == "a_steady_aim")
        self.assertEqual(sa["slot"], "bonus_action")
        self.assertEqual(sa["type"], "defensive_buff")
        self.assertTrue(sa["requires_no_movement"])
        self.assertEqual(sa["pipeline"][0]["primitive"], "steady_aim")


# ============================================================================
# Layer 12: feature YAML loading
# ============================================================================

class FeatureLoadingTest(unittest.TestCase):

    def test_f_steady_aim_loads(self) -> None:
        registry = load_content(CONTENT_ROOT, validate=True,
                                  schema_root=SCHEMA_ROOT)
        feature = registry.get("feature", "f_steady_aim")
        self.assertEqual(feature["granted_by"]["class"], "c_rogue")
        self.assertEqual(feature["granted_by"]["level"], 3)


if __name__ == "__main__":
    unittest.main()
