"""Aid tests (PR #97) — max-HP grant + multi-target candidate grouping.

RAW (2nd-level Cleric/Paladin/Bard/Ranger/Artificer, PHB 2024):
  Action cast, 30 ft, up to 3 creatures. Each target's HP maximum AND
  current HP increase by 5 for the duration (8 hours, NOT
  concentration). +5 per slot level above 2nd.

Two new pieces of infrastructure this PR exercises:
  A. **hp_max_grant** — raises actual max + current HP (distinct from
     temp HP). Ledgered on Actor.hp_max_bonuses for clean long-rest
     removal.
  B. **Multi-target candidate grouping** — the pattern deferred since
     Bless (PR #82). One candidate covers up to N allies; scoring
     sums; execute() loops the pipeline per target.

Layers:
  1. hp_max_grant raises max + current HP + ledger entry
  2. Dedup: same named_effect doesn't stack
  3. Upcast: amount_per_slot_above_base scales
  4. remove_hp_max_bonus lowers max + caps current
  5. Long rest clears hp_max_bonuses (before HP restore)
  6. _select_multi_target_group picks up-to-N, most-wounded-first
  7. _select_multi_target_group respects range
  8. Multi-target candidate emitted (one, with targets list)
  9. execute() applies hp_max_grant to all targets in group
 10. score_candidate sums per-target value across group
 11. f_aid YAML loads with correct shape (max_targets=3, NOT conc)
 12. Scoring dedups when target already has Aid
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import (
    _hp_max_grant, remove_hp_max_bonus, PrimitiveRegistry,
)


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30,
                  hp_max=30, ac=14, actions=None):
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
        hp_current=hp, hp_max=hp_max, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _aid_action():
    return {
        "id": "a_aid", "name": "Aid", "type": "defensive_buff",
        "spell_slot_level": 2, "slot": "action",
        "named_effect": "aid", "range_ft": 30, "max_targets": 3,
        "pipeline": [
            {"primitive": "hp_max_grant",
              "params": {"target": "ally", "amount": 5,
                          "amount_per_slot_above_base": 5}},
        ],
    }


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1+2+3: hp_max_grant primitive
# ============================================================================

class HpMaxGrantTest(unittest.TestCase):

    def test_grant_raises_max_and_current(self) -> None:
        caster = _make_actor("caster")
        target = _make_actor("ally", side="pc", hp=20, hp_max=30)
        state = _make_state([caster, target])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_aid", "named_effect": "aid"},
        }
        _hp_max_grant({"amount": 5}, state, EventBus())
        self.assertEqual(target.hp_max, 35)
        self.assertEqual(target.hp_current, 25)
        self.assertEqual(len(target.hp_max_bonuses), 1)
        self.assertEqual(target.hp_max_bonuses[0]["amount"], 5)
        self.assertEqual(target.hp_max_bonuses[0]["named_effect"], "aid")

    def test_dedup_same_named_effect(self) -> None:
        caster = _make_actor("caster")
        target = _make_actor("ally", side="pc", hp=30, hp_max=30)
        state = _make_state([caster, target])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_aid", "named_effect": "aid"},
        }
        _hp_max_grant({"amount": 5}, state, EventBus())
        # Second cast of the same named effect — no stacking
        _hp_max_grant({"amount": 5}, state, EventBus())
        self.assertEqual(target.hp_max, 35)   # only +5, not +10
        self.assertEqual(len(target.hp_max_bonuses), 1)

    def test_upcast_scaling(self) -> None:
        # Cast at slot 4 (base 2) → +5 + 2*5 = +15
        caster = _make_actor("caster")
        target = _make_actor("ally", side="pc", hp=30, hp_max=30)
        state = _make_state([caster, target])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_aid", "named_effect": "aid",
                          "spell_slot_level": 2},
            "chosen_slot_level": 4,
        }
        _hp_max_grant({"amount": 5,
                         "amount_per_slot_above_base": 5},
                        state, EventBus())
        self.assertEqual(target.hp_max, 45)
        self.assertEqual(target.hp_current, 45)


# ============================================================================
# Layer 4: remove_hp_max_bonus
# ============================================================================

class RemoveHpMaxBonusTest(unittest.TestCase):

    def test_remove_lowers_max_and_caps_current(self) -> None:
        target = _make_actor("ally", hp=35, hp_max=35)
        target.hp_max_bonuses = [{
            "amount": 5, "source_id": "caster",
            "source_action_id": "a_aid", "named_effect": "aid",
        }]
        removed = remove_hp_max_bonus(target, named_effect="aid")
        self.assertEqual(removed, 5)
        self.assertEqual(target.hp_max, 30)
        # Current was 35, now capped to 30
        self.assertEqual(target.hp_current, 30)
        self.assertEqual(len(target.hp_max_bonuses), 0)

    def test_remove_does_not_raise_current_if_below_new_max(self) -> None:
        # Current HP was below the reduced max → unchanged
        target = _make_actor("ally", hp=12, hp_max=35)
        target.hp_max_bonuses = [{
            "amount": 5, "source_id": "c",
            "source_action_id": "a_aid", "named_effect": "aid",
        }]
        remove_hp_max_bonus(target, named_effect="aid")
        self.assertEqual(target.hp_max, 30)
        self.assertEqual(target.hp_current, 12)   # untouched

    def test_remove_nonmatching_is_noop(self) -> None:
        target = _make_actor("ally", hp=35, hp_max=35)
        target.hp_max_bonuses = [{
            "amount": 5, "named_effect": "aid",
            "source_action_id": "a_aid", "source_id": "c",
        }]
        removed = remove_hp_max_bonus(target, named_effect="heroes_feast")
        self.assertEqual(removed, 0)
        self.assertEqual(target.hp_max, 35)


# ============================================================================
# Layer 5: long rest clears bonuses
# ============================================================================

class LongRestClearsTest(unittest.TestCase):

    def test_long_rest_removes_aid_bonus(self) -> None:
        from engine.core.rest import apply_long_rest
        a = _make_actor("ally", hp=35, hp_max=35)
        a.hp_max_bonuses = [{
            "amount": 5, "named_effect": "aid",
            "source_action_id": "a_aid", "source_id": "c",
        }]
        state = _make_state([a])
        summary = apply_long_rest(a, state)
        # Bonus removed → base max 30, current restored to 30
        self.assertEqual(a.hp_max, 30)
        self.assertEqual(a.hp_current, 30)
        self.assertEqual(len(a.hp_max_bonuses), 0)
        self.assertEqual(summary.get("hp_max_bonus_cleared"), 5)


# ============================================================================
# Layer 6+7: multi-target group selection
# ============================================================================

class MultiTargetSelectionTest(unittest.TestCase):

    def test_picks_up_to_max_targets_most_wounded_first(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        # Four allies at varying HP fractions
        a1 = _make_actor("a1", side="pc", position=(1, 0),
                            hp=30, hp_max=30)   # 100%
        a2 = _make_actor("a2", side="pc", position=(1, 0),
                            hp=5, hp_max=30)    # 17% (most wounded)
        a3 = _make_actor("a3", side="pc", position=(1, 0),
                            hp=15, hp_max=30)   # 50%
        a4 = _make_actor("a4", side="pc", position=(1, 0),
                            hp=25, hp_max=30)   # 83%
        allies = [caster, a1, a2, a3, a4]
        state = _make_state(allies)
        group = pipeline._select_multi_target_group(
            _aid_action(), allies, caster, state)
        # max_targets=3 → 3 most-wounded: a2 (17%), a3 (50%), a4 (83%)
        self.assertEqual(len(group), 3)
        self.assertIn(a2, group)
        self.assertIn(a3, group)
        # The 100% ally (a1) and full-HP caster should be lowest
        # priority — at least a2 (most wounded) must be first
        self.assertEqual(group[0], a2)

    def test_respects_range(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        near = _make_actor("near", side="pc", position=(1, 0))   # 5 ft
        far = _make_actor("far", side="pc", position=(20, 0))    # 100 ft
        allies = [caster, near, far]
        state = _make_state(allies)
        group = pipeline._select_multi_target_group(
            _aid_action(), allies, caster, state)   # range_ft=30
        self.assertIn(near, group)
        self.assertNotIn(far, group)


# ============================================================================
# Layer 8: candidate emission
# ============================================================================

class CandidateEmissionTest(unittest.TestCase):

    def test_one_multi_target_candidate_emitted(self) -> None:
        caster = _make_actor("caster", side="pc", position=(0, 0),
                                actions=[_aid_action()])
        caster.spell_slots = {2: 2}   # needs a 2nd-level slot to cast
        a1 = _make_actor("a1", side="pc", position=(1, 0))
        a2 = _make_actor("a2", side="pc", position=(1, 0))
        enemy = _make_actor("enemy", side="enemy", position=(2, 0))
        state = _make_state([caster, a1, a2, enemy])
        candidates = pipeline.generate_candidates(caster, state,
                                                      slot="action")
        aid_candidates = [c for c in candidates
                            if c.get("action", {}).get("id") == "a_aid"]
        # Exactly ONE candidate (not one per ally)
        self.assertEqual(len(aid_candidates), 1)
        self.assertIn("targets", aid_candidates[0])
        # Group covers up to 3 allies (caster + a1 + a2 = 3)
        self.assertEqual(len(aid_candidates[0]["targets"]), 3)


# ============================================================================
# Layer 9: multi-target execution
# ============================================================================

class MultiTargetExecutionTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_execute_applies_to_all_targets(self) -> None:
        caster = _make_actor("caster", side="pc", position=(0, 0))
        caster.spell_slots = {2: 2}   # needs a 2nd-level slot to cast
        a1 = _make_actor("a1", side="pc", position=(1, 0),
                            hp=20, hp_max=30)
        a2 = _make_actor("a2", side="pc", position=(1, 0),
                            hp=25, hp_max=30)
        state = _make_state([caster, a1, a2])
        chosen = {
            "kind": "defensive_buff",
            "action": _aid_action(),
            "target": a1,
            "targets": [a1, a2],
            "actor": caster,
        }
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Both allies got +5 max + current
        self.assertEqual(a1.hp_max, 35)
        self.assertEqual(a1.hp_current, 25)
        self.assertEqual(a2.hp_max, 35)
        self.assertEqual(a2.hp_current, 30)


# ============================================================================
# Layer 10+12: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_multi_target_score_sums(self) -> None:
        from engine.ai.ehp_scoring import score_candidate
        caster = _make_actor("caster", side="pc")
        a1 = _make_actor("a1", side="pc", position=(1, 0))
        a2 = _make_actor("a2", side="pc", position=(1, 0))
        a3 = _make_actor("a3", side="pc", position=(1, 0))
        state = _make_state([caster, a1, a2, a3])
        candidate = {
            "kind": "defensive_buff",
            "action": _aid_action(),
            "target": a1,
            "targets": [a1, a2, a3],
            "actor": caster,
        }
        score = score_candidate(candidate, state)
        # 3 targets × 5 HP each = 15
        self.assertEqual(score, 15.0)

    def test_single_target_score_is_grant(self) -> None:
        from engine.ai.ehp_scoring import score_candidate
        caster = _make_actor("caster", side="pc")
        a1 = _make_actor("a1", side="pc", position=(1, 0))
        state = _make_state([caster, a1])
        candidate = {
            "kind": "defensive_buff",
            "action": _aid_action(),
            "target": a1,
            "actor": caster,
        }
        score = score_candidate(candidate, state)
        self.assertEqual(score, 5.0)

    def test_score_zero_when_target_already_has_aid(self) -> None:
        from engine.ai.ehp_scoring import score_candidate
        caster = _make_actor("caster", side="pc")
        a1 = _make_actor("a1", side="pc", position=(1, 0))
        a1.hp_max_bonuses = [{"amount": 5, "named_effect": "aid",
                                "source_action_id": "a_aid",
                                "source_id": "x"}]
        state = _make_state([caster, a1])
        candidate = {
            "kind": "defensive_buff",
            "action": _aid_action(),
            "target": a1,
            "actor": caster,
        }
        score = score_candidate(candidate, state)
        self.assertEqual(score, 0.0)


# ============================================================================
# Layer 11: YAML loads
# ============================================================================

class YamlTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_aid_loads(self) -> None:
        feature = self.registry.get("feature", "f_aid")
        self.assertEqual(feature["granted_by"]["class"], "c_paladin")
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["type"], "defensive_buff")
        self.assertEqual(tmpl["spell_slot_level"], 2)
        self.assertEqual(tmpl["slot"], "action")
        self.assertEqual(tmpl["max_targets"], 3)
        # Aid is NOT concentration
        self.assertNotIn("concentration", tmpl)
        self.assertEqual(tmpl["named_effect"], "aid")
        prims = [s["primitive"] for s in tmpl["pipeline"]]
        self.assertIn("hp_max_grant", prims)


if __name__ == "__main__":
    unittest.main()
