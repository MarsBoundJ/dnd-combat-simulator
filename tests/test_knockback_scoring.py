"""Knockback / forced-movement AI scoring tests (PR #108).

Closes the deferred half of Repelling Blast (PR #106): the AI now
VALUES the push, not just the damage. `knockback_ehp` adds a small
tempo bonus on top of an attack's damage score when the action carries
a forced_movement step and the target is a melee threat — so a Warlock
with Repelling Blast prefers Eldritch Blast over an equal-damage
option, and prefers pushing a slow melee bruiser over a fast skirmisher.

Layers:
  1. _forced_movement_distance sums push distance across a pipeline
  2. _has_melee_attack distinguishes melee vs ranged-only creatures
  3. knockback_ehp = 0 for a non-repelling attack
  4. knockback_ehp = 0 against a ranged-only target
  5. knockback_ehp > 0 for repelling EB vs a melee target
  6. Slower target → larger tempo fraction (capped at 1.0)
  7. score_candidate: repelling EB out-scores plain EB vs same melee foe
  8. Multiattack: more beams → more knockback value
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.ehp_scoring import (
    _forced_movement_distance, _has_melee_attack, knockback_ehp,
    score_candidate, KNOCKBACK_TEMPO_WEIGHT,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _registry():
    return load_content(CONTENT_ROOT, validate=True,
                          schema_root=SCHEMA_ROOT)


def _melee_attack(bonus=4, dice="1d8", mod=3):
    return {"id": "a_claw", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": bonus,
                              "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": dice, "modifier": mod,
                              "type": "slashing"}},
            ]}


def _ranged_attack():
    return {"id": "a_bow", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "ranged", "bonus": 4,
                              "range_ft": 80}},
                {"primitive": "damage",
                  "params": {"dice": "1d8", "modifier": 2,
                              "type": "piercing"}},
            ]}


def _foe(foe_id="foe", *, position=(2, 0), hp=50, ac=13, speed=30,
           actions=None):
    template = {"id": "t", "name": foe_id, "abilities": {},
                "cr": {"proficiency_bonus": 2},
                "actions": actions if actions is not None
                              else [_melee_attack()]}
    return Actor(id=foe_id, name=foe_id, template=template, side="enemy",
                   hp_current=hp, hp_max=hp, ac=ac,
                   speed={"walk": speed}, position=position, abilities={})


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


def _build_warlock(registry, level=1, repelling=False):
    invocations = ["f_repelling_blast"] if repelling else None
    pc_spec = {
        "id": f"wl{level}", "class": "c_warlock", "level": level,
        "ability_scores": {"str": 8, "dex": 14, "con": 14,
                              "int": 10, "wis": 12, "cha": 16},
        "weapons": [],
    }
    if invocations:
        pc_spec["invocations"] = invocations
    return build_pc_template(pc_spec, registry)


def _beam(template):
    return next(a for a in template["actions"]
                  if a.get("id") == "a_eldritch_blast")


# ============================================================================
# Layers 1+2: helpers
# ============================================================================

class HelperTest(unittest.TestCase):

    def test_forced_movement_distance_sums(self) -> None:
        action = {"pipeline": [
            {"primitive": "attack_roll", "params": {}},
            {"primitive": "forced_movement", "params": {"distance_ft": 10}},
        ]}
        self.assertEqual(_forced_movement_distance(action), 10)

    def test_forced_movement_distance_zero_without_step(self) -> None:
        action = {"pipeline": [{"primitive": "damage", "params": {}}]}
        self.assertEqual(_forced_movement_distance(action), 0)

    def test_has_melee_attack_true(self) -> None:
        self.assertTrue(_has_melee_attack(_foe(actions=[_melee_attack()])))

    def test_has_melee_attack_false_for_ranged_only(self) -> None:
        self.assertFalse(_has_melee_attack(_foe(actions=[_ranged_attack()])))


# ============================================================================
# Layers 3+4+5+6: knockback_ehp
# ============================================================================

class KnockbackEhpTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_zero_for_non_repelling_attack(self) -> None:
        wl = _build_warlock(self.registry, 1, repelling=False)
        actor = Actor(id="wl", name="wl", template=wl, side="pc",
                        hp_current=20, hp_max=20, ac=12, position=(0, 0),
                        abilities=wl["abilities"])
        foe = _foe()
        st = _state([actor, foe])
        self.assertEqual(knockback_ehp(actor, foe, _beam(wl), st), 0.0)

    def test_zero_against_ranged_target(self) -> None:
        wl = _build_warlock(self.registry, 1, repelling=True)
        actor = Actor(id="wl", name="wl", template=wl, side="pc",
                        hp_current=20, hp_max=20, ac=12, position=(0, 0),
                        abilities=wl["abilities"])
        archer = _foe("archer", actions=[_ranged_attack()])
        st = _state([actor, archer])
        self.assertEqual(knockback_ehp(actor, archer, _beam(wl), st), 0.0)

    def test_positive_for_repelling_vs_melee(self) -> None:
        wl = _build_warlock(self.registry, 1, repelling=True)
        actor = Actor(id="wl", name="wl", template=wl, side="pc",
                        hp_current=20, hp_max=20, ac=12, position=(0, 0),
                        abilities=wl["abilities"])
        foe = _foe()
        st = _state([actor, foe])
        self.assertGreater(knockback_ehp(actor, foe, _beam(wl), st), 0.0)

    def test_slower_target_scores_higher(self) -> None:
        wl = _build_warlock(self.registry, 1, repelling=True)
        actor = Actor(id="wl", name="wl", template=wl, side="pc",
                        hp_current=20, hp_max=20, ac=12, position=(0, 0),
                        abilities=wl["abilities"])
        fast = _foe("fast", speed=40)
        slow = _foe("slow", speed=10)
        st = _state([actor, fast, slow])
        beam = _beam(wl)
        self.assertGreater(knockback_ehp(actor, slow, beam, st),
                             knockback_ehp(actor, fast, beam, st))

    def test_capped_at_full_dpr_weight(self) -> None:
        # Even a near-stationary enemy can't exceed DPR × weight.
        from engine.ai.defensive_ehp import estimate_dpr
        wl = _build_warlock(self.registry, 1, repelling=True)
        actor = Actor(id="wl", name="wl", template=wl, side="pc",
                        hp_current=20, hp_max=20, ac=12, position=(0, 0),
                        abilities=wl["abilities"])
        slug = _foe("slug", speed=5, ac=1)   # low AC → near-certain hit
        st = _state([actor, slug])
        val = knockback_ehp(actor, slug, _beam(wl), st)
        ceiling = estimate_dpr(slug) * KNOCKBACK_TEMPO_WEIGHT
        self.assertLessEqual(val, ceiling + 1e-9)


# ============================================================================
# Layer 7+8: score_candidate integration
# ============================================================================

class ScoreCandidateTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def _actor(self, template):
        return Actor(id="wl", name="wl", template=template, side="pc",
                       hp_current=20, hp_max=20, ac=12, position=(0, 0),
                       abilities=template["abilities"])

    def test_repelling_eb_outscores_plain_eb(self) -> None:
        plain = _build_warlock(self.registry, 1, repelling=False)
        repel = _build_warlock(self.registry, 1, repelling=True)
        foe_a = _foe("foe_a", ac=13)
        foe_b = _foe("foe_b", ac=13)
        st_plain = _state([self._actor(plain), foe_a])
        st_repel = _state([self._actor(repel), foe_b])
        plain_score = score_candidate(
            {"kind": "weapon_attack", "action": _beam(plain),
              "actor": st_plain.encounter.actors[0], "target": foe_a},
            st_plain)
        repel_score = score_candidate(
            {"kind": "weapon_attack", "action": _beam(repel),
              "actor": st_repel.encounter.actors[0], "target": foe_b},
            st_repel)
        # Same 1d10 damage; repelling adds the tempo bonus on top.
        self.assertGreater(repel_score, plain_score)

    def test_multiattack_more_beams_more_knockback(self) -> None:
        # L11 Warlock fires 3 beams → more cumulative push than L5's 2.
        wl5 = _build_warlock(self.registry, 5, repelling=True)
        wl11 = _build_warlock(self.registry, 11, repelling=True)
        foe5 = _foe("foe5", speed=30, hp=200)
        foe11 = _foe("foe11", speed=30, hp=200)
        st5 = _state([self._actor(wl5), foe5])
        st11 = _state([self._actor(wl11), foe11])
        multi5 = next(a for a in wl5["actions"]
                        if a.get("id") == "a_eldritch_blast_beams")
        multi11 = next(a for a in wl11["actions"]
                         if a.get("id") == "a_eldritch_blast_beams")
        kb5 = knockback_ehp(st5.encounter.actors[0], foe5, multi5, st5)
        kb11 = knockback_ehp(st11.encounter.actors[0], foe11, multi11, st11)
        self.assertGreater(kb11, kb5)


if __name__ == "__main__":
    unittest.main()
