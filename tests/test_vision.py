"""Vision system v1 tests (PR #47).

Layers:
  1. can_actor_see default — True for any two actors with no
     visibility-altering conditions
  2. Invisible target → not seen by anyone
  3. Blinded observer → sees no one
  4. Both → still False (intersection)
  5. has_condition / is_invisible / is_blinded helpers
  6. _eval_when wiring: attacker_can_see(self) / target_can_see(self)
     atoms resolve correctly
  7. Reaction conditions: Counterspell skipped against invisible
     caster; Hellish Rebuke skipped when attacker invisible;
     Protection skipped when attacker invisible
  8. Co_invisible.yaml when-clauses still fire correctly through the
     new evaluator (regression — pre-PR #47 these worked by
     coincidence because the predicates were unknown atoms returning
     False; the new impl computes correctly)

Run via:
    python -m unittest tests.test_vision
"""
from __future__ import annotations

import unittest

from engine.core.state import Actor, Encounter, CombatState
from engine.core.vision import (
    can_actor_see, has_condition, is_invisible, is_blinded,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, side="pc", position=(0, 0),
                applied_conditions=None) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": []}
    actor = Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=20, hp_max=20, ac=14,
                   speed={"walk": 30}, position=position,
                   abilities=abilities)
    if applied_conditions:
        actor.applied_conditions = list(applied_conditions)
    return actor


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Condition helpers
# ============================================================================

class ConditionHelperTest(unittest.TestCase):

    def test_has_condition_yes(self) -> None:
        a = _make_actor("a", applied_conditions=[
            {"condition_id": "co_invisible"}])
        self.assertTrue(has_condition(a, "co_invisible"))

    def test_has_condition_no(self) -> None:
        a = _make_actor("a")
        self.assertFalse(has_condition(a, "co_invisible"))

    def test_is_invisible_yes(self) -> None:
        a = _make_actor("a", applied_conditions=[
            {"condition_id": "co_invisible"}])
        self.assertTrue(is_invisible(a))

    def test_is_invisible_no(self) -> None:
        a = _make_actor("a")
        self.assertFalse(is_invisible(a))

    def test_is_blinded_yes(self) -> None:
        a = _make_actor("a", applied_conditions=[
            {"condition_id": "co_blinded"}])
        self.assertTrue(is_blinded(a))


# ============================================================================
# can_actor_see
# ============================================================================

class CanActorSeeTest(unittest.TestCase):

    def test_default_true(self) -> None:
        a = _make_actor("a")
        b = _make_actor("b")
        state = _state_with([a, b])
        self.assertTrue(can_actor_see(a, b, state))
        self.assertTrue(can_actor_see(b, a, state))

    def test_invisible_target_not_seen(self) -> None:
        observer = _make_actor("obs")
        target = _make_actor("target", applied_conditions=[
            {"condition_id": "co_invisible"}])
        state = _state_with([observer, target])
        self.assertFalse(can_actor_see(observer, target, state))
        # But target still "sees" observer normally
        self.assertTrue(can_actor_see(target, observer, state))

    def test_blinded_observer_sees_nothing(self) -> None:
        observer = _make_actor("obs", applied_conditions=[
            {"condition_id": "co_blinded"}])
        target = _make_actor("target")
        state = _state_with([observer, target])
        self.assertFalse(can_actor_see(observer, target, state))
        # Target still sees observer (the Blinded creature)
        self.assertTrue(can_actor_see(target, observer, state))

    def test_blinded_and_invisible_intersection(self) -> None:
        """Blinded observer + Invisible target: still can't see."""
        observer = _make_actor("obs", applied_conditions=[
            {"condition_id": "co_blinded"}])
        target = _make_actor("target", applied_conditions=[
            {"condition_id": "co_invisible"}])
        state = _state_with([observer, target])
        self.assertFalse(can_actor_see(observer, target, state))

    def test_actor_always_sees_self(self) -> None:
        """An actor always 'sees' themselves for query purposes —
        needed for self-targeted modifier when-clauses on Invisible
        creatures (they don't gate on whether they see themselves)."""
        a = _make_actor("a", applied_conditions=[
            {"condition_id": "co_invisible"}])
        state = _state_with([a])
        self.assertTrue(can_actor_see(a, a, state))

    def test_none_actors_return_false(self) -> None:
        state = _state_with([])
        self.assertFalse(can_actor_see(None, None, state))


# ============================================================================
# _eval_when integration — attacker_can_see / target_can_see atoms
# ============================================================================

class EvalWhenVisionPredicatesTest(unittest.TestCase):

    def test_attacker_can_see_self_true_by_default(self) -> None:
        """attacker_can_see(self) where attacker is not Blinded and
        owner (self) is not Invisible → True."""
        from engine.core.modifiers import _eval_when
        owner = _make_actor("owner")
        attacker = _make_actor("attacker", side="enemy")
        state = _state_with([owner, attacker])
        result = _eval_when("attacker_can_see(self)",
                              owner=owner, attacker=attacker,
                              target=owner, state=state)
        self.assertTrue(result)

    def test_attacker_can_see_self_false_when_owner_invisible(self) -> None:
        """attacker_can_see(self) where owner has co_invisible → False
        (attacker can't see the invisible target)."""
        from engine.core.modifiers import _eval_when
        owner = _make_actor("owner", applied_conditions=[
            {"condition_id": "co_invisible"}])
        attacker = _make_actor("attacker", side="enemy")
        state = _state_with([owner, attacker])
        result = _eval_when("attacker_can_see(self)",
                              owner=owner, attacker=attacker,
                              target=owner, state=state)
        self.assertFalse(result)

    def test_NOT_attacker_can_see_self_true_when_invisible(self) -> None:
        """Verifies co_invisible's actual when-clause works:
        target_is_self AND NOT attacker_can_see(self) → True when the
        Invisible owner is being attacked."""
        from engine.core.modifiers import _eval_when
        owner = _make_actor("owner", applied_conditions=[
            {"condition_id": "co_invisible"}])
        attacker = _make_actor("attacker", side="enemy")
        state = _state_with([owner, attacker])
        result = _eval_when(
            "target_is_self AND NOT attacker_can_see(self)",
            owner=owner, attacker=attacker,
            target=owner, state=state,
        )
        self.assertTrue(result)


# ============================================================================
# Reaction conditions respect visibility (RAW "you can see" gates)
# ============================================================================

class ReactionConditionsRespectVisibilityTest(unittest.TestCase):

    def test_counterspell_skipped_against_invisible_caster(self) -> None:
        """RAW: Counterspell requires you to see the caster."""
        from engine.core.reactions import _reaction_condition_satisfied
        counterspeller = _make_actor("cs", side="pc", position=(0, 0))
        # Enemy caster is Invisible
        invisible_caster = _make_actor(
            "ic", side="enemy", position=(5, 5),
            applied_conditions=[{"condition_id": "co_invisible"}])
        state = _state_with([counterspeller, invisible_caster])
        ed = {"caster": invisible_caster, "spell_slot_level": 3,
              "action": {}}
        self.assertFalse(_reaction_condition_satisfied(
            "enemy_casting_spell_within_60_ft", counterspeller, ed, state),
            "Counterspell should not fire when caster is Invisible")

    def test_hellish_rebuke_skipped_against_invisible_attacker(self) -> None:
        """RAW: HR requires you to see the creature that damaged you."""
        from engine.core.reactions import _reaction_condition_satisfied
        warlock = _make_actor("w", side="pc")
        invisible_attacker = _make_actor(
            "att", side="enemy",
            applied_conditions=[{"condition_id": "co_invisible"}])
        state = _state_with([warlock, invisible_attacker])
        ed = {"target_id": "w", "attacker": invisible_attacker}
        self.assertFalse(_reaction_condition_satisfied(
            "damage_taken_by_self_from_attacker", warlock, ed, state),
            "Hellish Rebuke should not fire when attacker is Invisible")

    def test_protection_skipped_against_invisible_attacker(self) -> None:
        """RAW: Protection requires you to see the attacking creature."""
        from engine.core.reactions import _reaction_condition_satisfied
        protector = _make_actor("p", side="pc", position=(0, 0))
        ally = _make_actor("a", side="pc", position=(0, 1))
        invisible_attacker = _make_actor(
            "att", side="enemy", position=(0, 2),
            applied_conditions=[{"condition_id": "co_invisible"}])
        state = _state_with([protector, ally, invisible_attacker])
        ed = {"target": ally, "actor": invisible_attacker}
        self.assertFalse(_reaction_condition_satisfied(
            "attack_against_ally_within_5_ft", protector, ed, state),
            "Protection should not fire when attacker is Invisible")

    def test_counterspell_still_fires_against_visible_caster(self) -> None:
        """Regression: visible enemy caster still triggers Counterspell."""
        from engine.core.reactions import _reaction_condition_satisfied
        counterspeller = _make_actor("cs", side="pc", position=(0, 0))
        visible_caster = _make_actor(
            "vc", side="enemy", position=(5, 5))   # no conditions
        state = _state_with([counterspeller, visible_caster])
        ed = {"caster": visible_caster, "spell_slot_level": 3,
              "action": {}}
        self.assertTrue(_reaction_condition_satisfied(
            "enemy_casting_spell_within_60_ft", counterspeller, ed, state))

    def test_blinded_counterspeller_doesnt_counter(self) -> None:
        """Blinded counterspeller can't see anyone → no Counterspell."""
        from engine.core.reactions import _reaction_condition_satisfied
        blinded_cs = _make_actor(
            "cs", side="pc", position=(0, 0),
            applied_conditions=[{"condition_id": "co_blinded"}])
        caster = _make_actor("c", side="enemy", position=(5, 5))
        state = _state_with([blinded_cs, caster])
        ed = {"caster": caster, "spell_slot_level": 3, "action": {}}
        self.assertFalse(_reaction_condition_satisfied(
            "enemy_casting_spell_within_60_ft", blinded_cs, ed, state),
            "Blinded counterspeller can't see the caster")


# ============================================================================
# Existing reaction tests still pass (regression)
# ============================================================================

class ExistingReactionConditionsRegressionTest(unittest.TestCase):
    """Pin that the existing reaction conditions (PR #45/#46) still
    work for non-Invisible / non-Blinded creatures."""

    def test_shield_would_help_unaffected_by_vision(self) -> None:
        """Shield's condition doesn't have a vision gate — works
        regardless of Invisible / Blinded status."""
        from engine.core.reactions import _reaction_condition_satisfied
        wizard = _make_actor("wiz", applied_conditions=[
            {"condition_id": "co_blinded"}])
        state = _state_with([wizard])
        ed = {"target": wizard, "total": 18, "current_ac": 15}
        self.assertTrue(_reaction_condition_satisfied(
            "shield_would_help", wizard, ed, state),
            "Blinded wizard can still Shield (RAW: Shield triggers on "
            "being hit by an attack roll — no vision requirement)")


if __name__ == "__main__":
    unittest.main()
