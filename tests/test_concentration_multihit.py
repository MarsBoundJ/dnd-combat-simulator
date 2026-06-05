"""Multi-hit concentration saves — backlog task #65 (red-team item).

The red-team raised: when a multi-projectile / multi-attack spell strikes a
concentrating target, does the engine force ONE save per hit (RAW), or wrongly
amalgamate all the damage into a single big-DC save?

This test EVIDENCES (rather than asserts) that the engine is already correct,
on two layers:

  A. ENGINE CONTRACT (per-damage-instance). The `_damage` primitive calls
     attempt_concentration_save with THIS instance's damage. So N separate
     `_damage` calls = N separate DC-max(10, ceil(dmg/2)) saves, and one
     summed `_damage` call = exactly one save. This is the architectural
     guarantee, independent of any particular spell.

  B. CONTENT CORRECTNESS (the two spells the red-team had in mind).
       * Scorching Ray (ray_count: 3) expands to THREE (attack_roll, damage)
         pairs → three separate `_damage` calls at runtime → three saves.
         CORRECT: each ray is a separate hit, each forces its own save.
       * Magic Missile collapses its darts into ONE summed `_damage`
         (3d4+3) → exactly one save. CORRECT per Sage Advice: the darts
         strike simultaneously, so it's a single save against the total —
         the red-team's "three saves for Magic Missile" premise is wrong.

Run via:
    python -m unittest tests.test_concentration_multihit
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine import primitives as primitives_module
from engine.core.concentration import apply_concentration
from engine.core.events import EventBus
from engine.core.state import Actor, Encounter, CombatState
from engine.loader import load_content
from engine.pc_schema import build_pc_template

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _make_actor(actor_id: str, side: str = "pc", hp: int = 200,
                con_save: int = 20) -> Actor:
    """con_save=+20 => auto-pass, so concentration is NEVER dropped and a
    multi-hit sequence keeps producing one save per hit (we're counting
    saves, not measuring drops)."""
    abilities = {
        "str": {"score": 14, "save": 2}, "dex": {"score": 12, "save": 1},
        "con": {"score": 12, "save": con_save}, "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2}, "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id, "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                 hp_current=hp, hp_max=hp, ac=14, position=(0, 0),
                 abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    state = CombatState(encounter=Encounter(id="t", actors=actors))
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _bless() -> dict:
    return {"id": "a_bless", "name": "Bless", "type": "offensive_buff",
            "concentration": True}


def _save_events(state: CombatState) -> list[dict]:
    return [e for e in state.event_log if e["event"] == "concentration_save"]


def _wizard_action(action_id: str, level: int = 13) -> dict:
    spec = {"class": "c_wizard", "level": level,
            "ability_scores": {"str": 8, "dex": 14, "con": 12,
                                "int": 18, "wis": 12, "cha": 10}}
    template = build_pc_template(spec, _registry())
    for a in template.get("actions", []):
        if a.get("id") == action_id:
            return a
    raise AssertionError(f"{action_id} not in L{level} wizard action set")


def _count_damage_steps(action: dict) -> int:
    return sum(1 for step in action.get("pipeline", [])
               if step.get("primitive") == "damage")


# ============================================================================
# A. Engine contract — one save per `_damage` instance
# ============================================================================

class PerInstanceSaveContractTest(unittest.TestCase):

    def _hit(self, target, attacker, state, dice):
        state.current_attack = {"actor": attacker, "target": target,
                                 "action": {}, "state": "hit"}
        primitives_module._damage(
            {"dice": dice, "modifier": 0, "type": "fire"}, state, EventBus())

    def test_three_separate_damage_calls_three_saves(self):
        """Three separate `_damage` instances (as a 3-ray spell emits) =
        three concentration saves — one per hit, RAW."""
        primitives_module.set_rng(random.Random(1))
        caster = _make_actor("c", con_save=20)        # auto-pass: never drops
        attacker = _make_actor("a", side="enemy")
        state = _state_with([caster, attacker])
        apply_concentration(caster, _bless(), state)
        state.event_log.clear()

        for _ in range(3):
            self._hit(caster, attacker, state, "2d6")

        self.assertEqual(len(_save_events(state)), 3)
        # Still concentrating (all three auto-passed).
        self.assertIsNotNone(caster.concentration_on)

    def test_one_summed_damage_call_one_save(self):
        """A single summed `_damage` (as Magic Missile emits) = exactly one
        save against the total — NOT one per die."""
        primitives_module.set_rng(random.Random(1))
        caster = _make_actor("c", con_save=20)
        attacker = _make_actor("a", side="enemy")
        state = _state_with([caster, attacker])
        apply_concentration(caster, _bless(), state)
        state.event_log.clear()

        self._hit(caster, attacker, state, "3d4")       # 3 darts, one packet

        self.assertEqual(len(_save_events(state)), 1)

    def test_each_save_dc_is_per_instance_not_summed(self):
        """The per-instance DC is computed from each hit's own damage, so
        three modest hits give three DC-10-ish saves — NOT one giant-DC
        save against the summed damage (which is the amalgamation bug)."""
        primitives_module.set_rng(random.Random(1))
        caster = _make_actor("c", con_save=20)
        attacker = _make_actor("a", side="enemy")
        state = _state_with([caster, attacker])
        apply_concentration(caster, _bless(), state)
        state.event_log.clear()

        for _ in range(3):
            self._hit(caster, attacker, state, "2d6")    # ~7 each => DC 10

        saves = _save_events(state)
        self.assertEqual(len(saves), 3)
        # Each DC reflects a single ~7-damage hit (max(10, ceil(7/2)=4) = 10),
        # never the ~21 summed total (which would be DC 11+).
        for s in saves:
            self.assertLessEqual(s["damage_taken"], 12,
                                 "a save saw summed (not per-instance) damage")


# ============================================================================
# B. Content correctness — Scorching Ray vs Magic Missile expansion
# ============================================================================

class SpellExpansionConcentrationTest(unittest.TestCase):

    def test_scorching_ray_emits_three_damage_steps(self):
        """ray_count: 3 → three (attack_roll, damage) pairs → three separate
        `_damage` calls → three saves against a concentrating target."""
        action = _wizard_action("a_scorching_ray")
        self.assertEqual(_count_damage_steps(action), 3,
                         "Scorching Ray should force one save per ray (3)")

    def test_magic_missile_emits_one_damage_step(self):
        """Magic Missile collapses its darts into ONE summed `_damage` →
        exactly one save (correct per Sage Advice; the red-team's
        three-saves premise is wrong)."""
        action = _wizard_action("a_magic_missile")
        self.assertEqual(_count_damage_steps(action), 1,
                         "Magic Missile should force exactly one save (darts "
                         "strike simultaneously)")


if __name__ == "__main__":
    unittest.main()
