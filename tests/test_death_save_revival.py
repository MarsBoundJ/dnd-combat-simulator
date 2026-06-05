"""Death-save revival on heal (Stage 2).

Any positive healing on a dying ally brings it back to consciousness at that
HP and clears the death-save tally. Heals can TARGET a dying ally (it's added
to the heal candidate pool though it's not is_alive), and the heal scorer
values reviving a downed ally at maximum desperation so the AI will pick it.

Run via:
    python -m unittest tests.test_death_save_revival
"""
from __future__ import annotations

import random
import unittest

from engine.core import death_saves as ds
from engine.core.events import EventBus
from engine.core.pipeline import generate_candidates, execute as pipeline_execute
from engine.ai.defensive_ehp import defensive_ehp_healing
from engine.core.state import Actor, Encounter, CombatState
from engine.primitives import PrimitiveRegistry
import engine.primitives as primitives_module


def _actor(actor_id, side="pc", hp=40, hp_max=40, actions=None,
           spell_slots=None):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "cr": {"proficiency_bonus": 2},
                           "actions": actions or []},
                 side=side, hp_current=hp, hp_max=hp_max, ac=12,
                 position=(0, 0), abilities=ab,
                 spell_slots=dict(spell_slots or {}))


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


_CURE = {"id": "a_cure_wounds", "name": "Cure Wounds", "type": "heal",
         "slot": "action", "spell_slot_level": 1, "range_ft": 60,
         "pipeline": [{"primitive": "heal",
                       "params": {"target": "current_target",
                                  "dice": "", "modifier": 12}}]}


def _downed(actor, state):
    actor.hp_current = 0
    ds.enter_dying(actor, state)


class RevivalPrimitiveTest(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_heal_revives_dying_ally(self):
        cleric = _actor("cleric", actions=[_CURE], spell_slots={1: 3})
        downed = _actor("downed", hp=0, hp_max=40)
        st = _state([cleric, downed])
        _downed(downed, st)
        self.assertTrue(downed.is_dying)
        chosen = {"kind": "heal", "action": _CURE, "target": downed,
                  "actor": cleric}
        pipeline_execute(chosen, st, EventBus(),
                         PrimitiveRegistry.with_defaults())
        self.assertFalse(downed.is_dying)
        self.assertFalse(downed.is_dead)
        self.assertEqual(downed.hp_current, 12)        # revived AT heal amount
        self.assertTrue(downed.is_alive())
        self.assertEqual(downed.death_save_failures, 0)

    def test_zero_heal_does_not_revive(self):
        downed = _actor("downed", hp=0, hp_max=40)
        st = _state([downed])
        _downed(downed, st)
        st.current_attack = {"target": downed}
        primitives_module._heal(
            {"target": "current_target", "dice": "", "modifier": 0},
            st, EventBus())
        self.assertTrue(downed.is_dying)        # 0 healing -> still down
        self.assertEqual(downed.hp_current, 0)


class RevivalCandidateAndScoringTest(unittest.TestCase):
    def test_dying_ally_is_a_heal_candidate(self):
        cleric = _actor("cleric", actions=[_CURE], spell_slots={1: 3})
        downed = _actor("downed", hp=0, hp_max=40)
        st = _state([cleric, downed])
        _downed(downed, st)
        heal_targets = {c["target"].id for c in generate_candidates(cleric, st)
                        if c.get("kind") == "heal"}
        self.assertIn("downed", heal_targets)   # downed ally targetable

    def test_heal_scores_dying_ally_positive(self):
        cleric = _actor("cleric", actions=[_CURE], spell_slots={1: 3})
        downed = _actor("downed", hp=0, hp_max=40)
        st = _state([cleric, downed])
        _downed(downed, st)
        score = defensive_ehp_healing(cleric, downed, _CURE, st)
        self.assertGreater(score, 0.0)

    def test_truly_dead_ally_scores_zero(self):
        cleric = _actor("cleric", actions=[_CURE], spell_slots={1: 3})
        dead = _actor("dead", hp=0, hp_max=40)
        dead.is_dead = True
        st = _state([cleric, dead])
        self.assertEqual(defensive_ehp_healing(cleric, dead, _CURE, st), 0.0)


def _weapon(dmg_dice, bonus):
    return {"id": "a_w", "type": "weapon_attack", "reach_ft": 5,
            "pipeline": [{"primitive": "attack_roll",
                          "params": {"bonus": bonus}},
                         {"primitive": "damage",
                          "params": {"dice": dmg_dice, "modifier": 0,
                                     "type": "slashing"}}]}


class RevivalPriorityTest(unittest.TestCase):
    """Stage 3: reviving a downed ally is valued above topping off a healthy
    one and scales with the revived ally's DPR (revive the bigger threat)."""

    def test_revive_beats_conscious_topoff_at_same_missing_hp(self):
        cleric = _actor("cleric", actions=[_CURE], spell_slots={1: 3})
        # Both at ~0 HP fraction (same desperation + missing), but one is
        # DYING (revivable combatant) and one is conscious at 1 HP.
        dying = _actor("dying", hp=0, hp_max=40, actions=[_weapon("2d6", 5)])
        conscious = _actor("hurt", hp=1, hp_max=40, actions=[_weapon("2d6", 5)])
        st = _state([cleric, dying, conscious])
        ds.enter_dying(dying, st)
        revive_score = defensive_ehp_healing(cleric, dying, _CURE, st)
        topoff_score = defensive_ehp_healing(cleric, conscious, _CURE, st)
        self.assertGreater(revive_score, topoff_score)

    def test_revival_bonus_scales_with_dpr(self):
        cleric = _actor("cleric", actions=[_CURE], spell_slots={1: 3})
        bruiser = _actor("bruiser", hp=0, hp_max=40, actions=[_weapon("4d6", 8)])
        squishy = _actor("squishy", hp=0, hp_max=40, actions=[_weapon("1d4", 2)])
        st = _state([cleric, bruiser, squishy])
        ds.enter_dying(bruiser, st)
        ds.enter_dying(squishy, st)
        self.assertGreater(
            defensive_ehp_healing(cleric, bruiser, _CURE, st),
            defensive_ehp_healing(cleric, squishy, _CURE, st))


if __name__ == "__main__":
    unittest.main()
