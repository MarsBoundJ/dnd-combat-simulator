"""Multi-target Bless tests (PR #98).

Bless RAW (PHB 2024): pick up to 3 creatures within 30 ft; each adds
1d4 to attack rolls AND saving throws. Single-target emission was the
deferral noted in PR #82's f_bless.yaml. PR #97's candidate-grouping
infra (built for Aid) generalizes to offensive_buff here.

This PR:
  - Extends the offensive_buff candidate branch with max_targets
    grouping (was heal/defensive_buff only)
  - Adds the multi-target sum to the offensive_buff scoring dispatch
  - Flips f_bless.yaml max_targets: 3

Layers:
  1. f_bless.yaml has max_targets: 3
  2. One grouped Bless candidate emitted (not N per ally)
  3. Group covers up to 3 allies, excludes self
  4. execute() applies the buff to all targets in the group
  5. score_candidate sums offensive-buff value across the group
  6. Single-target offensive_buff (max_targets unset) still works
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine.ai.ehp_scoring import score_candidate, offensive_ehp_buff_ally
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  actions=None):
    abilities = {a: {"score": 14, "save": 2}
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
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _attacker(actor_id, position):
    """An ally with a weapon so offensive_ehp_buff_ally scores > 0."""
    return _make_actor(actor_id, side="pc", position=position, actions=[{
        "id": "a_sword", "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "ability": "str",
                          "bonus": 5, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "1d8", "modifier": 3,
                          "type": "slashing"}},
        ],
    }])


def _bless_action(max_targets=3):
    return {
        "id": "a_bless", "name": "Bless", "type": "offensive_buff",
        "spell_slot_level": 1, "slot": "action",
        "concentration": True, "named_effect": "bless",
        "range_ft": 30, "max_targets": max_targets,
        "pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "ally", "when": "attacker_is_self",
                          "modifier": "attack_bonus", "value": 2,
                          "lifetime": "until_short_rest"}},
        ],
    }


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1: YAML
# ============================================================================

class YamlTest(unittest.TestCase):

    def test_f_bless_has_max_targets(self) -> None:
        registry = load_content(CONTENT_ROOT, validate=True,
                                  schema_root=SCHEMA_ROOT)
        feature = registry.get("feature", "f_bless")
        self.assertEqual(
            feature["action_template"]["max_targets"], 3)


# ============================================================================
# Layer 2+3: candidate emission
# ============================================================================

class CandidateEmissionTest(unittest.TestCase):

    def test_one_grouped_candidate_excludes_self(self) -> None:
        cleric = _make_actor("cleric", side="pc", position=(0, 0),
                                actions=[_bless_action()])
        cleric.spell_slots = {1: 2}
        f1 = _attacker("f1", (1, 0))
        f2 = _attacker("f2", (1, 0))
        f3 = _attacker("f3", (1, 0))
        f4 = _attacker("f4", (1, 0))
        state = _make_state([cleric, f1, f2, f3, f4])
        candidates = pipeline.generate_candidates(cleric, state,
                                                      slot="action")
        bless = [c for c in candidates
                   if c.get("action", {}).get("id") == "a_bless"]
        self.assertEqual(len(bless), 1)
        targets = bless[0]["targets"]
        # max 3 targets, self excluded
        self.assertEqual(len(targets), 3)
        self.assertNotIn(cleric, targets)


# ============================================================================
# Layer 4: execution
# ============================================================================

class ExecutionTest(unittest.TestCase):

    def test_buff_applied_to_all_targets(self) -> None:
        import engine.primitives as primitives_module
        primitives_module.set_rng(random.Random(7))
        cleric = _make_actor("cleric", side="pc", position=(0, 0))
        cleric.spell_slots = {1: 2}
        f1 = _attacker("f1", (1, 0))
        f2 = _attacker("f2", (1, 0))
        state = _make_state([cleric, f1, f2])
        chosen = {
            "kind": "offensive_buff",
            "action": _bless_action(),
            "target": f1,
            "targets": [f1, f2],
            "actor": cleric,
        }
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Both allies got a Bless attack_modifier
        for ally in (f1, f2):
            bless_mods = [m for m in ally.active_modifiers
                            if m.get("primitive") == "attack_modifier"
                            and (m.get("source") or {}).get("named_effect")
                                == "bless"]
            self.assertEqual(len(bless_mods), 1)


# ============================================================================
# Layer 5+6: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_multi_target_score_sums(self) -> None:
        cleric = _make_actor("cleric", side="pc")
        f1 = _attacker("f1", (1, 0))
        f2 = _attacker("f2", (1, 0))
        f3 = _attacker("f3", (1, 0))
        state = _make_state([cleric, f1, f2, f3])
        action = _bless_action()
        candidate = {
            "kind": "offensive_buff", "action": action,
            "target": f1, "targets": [f1, f2, f3], "actor": cleric,
        }
        grouped = score_candidate(candidate, state)
        single = offensive_ehp_buff_ally(cleric, f1, action, state)
        self.assertAlmostEqual(grouped, single * 3, places=4)
        self.assertGreater(grouped, 0)

    def test_single_target_still_works(self) -> None:
        cleric = _make_actor("cleric", side="pc")
        f1 = _attacker("f1", (1, 0))
        state = _make_state([cleric, f1])
        action = _bless_action(max_targets=1)
        candidate = {
            "kind": "offensive_buff", "action": action,
            "target": f1, "actor": cleric,
        }
        score = score_candidate(candidate, state)
        self.assertEqual(
            score, offensive_ehp_buff_ally(cleric, f1, action, state))


if __name__ == "__main__":
    unittest.main()
