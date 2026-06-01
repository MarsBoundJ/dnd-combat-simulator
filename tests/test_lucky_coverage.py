"""Lucky on remaining d20 sites tests (PR #95).

Closes the PR #75 residue. Halfling Lucky was originally wired at
three sites (_attack_roll, _forced_save, recurring_save). Five more
d20 roll sites existed in the engine where Lucky should apply per RAW
but didn't:

  1. Initiative roll (DEX ability check)
  2. Counterspell ability check (INT ability check)
  3. Concentration save (CON saving throw)
  4. Hide stealth check (DEX ability check)
  5. Search perception check (WIS ability check)

This PR adds Lucky to all five. The retreat WIS save (engine.ai.
retreat) is an AI-behavior trigger, not a RAW combat math roll, so
it's intentionally deferred — Lucky's intent is "reroll a nat-1 on
a roll the player cares about," and AI-internal saves don't fit.

Layers:
  1. Initiative: Halfling with nat-1 rerolls
  2. Initiative: non-Halfling with nat-1 keeps the 1
  3. Counterspell ability check: Halfling rerolls nat-1
  4. Counterspell: non-Halfling keeps the 1
  5. Concentration save: Halfling rerolls nat-1
  6. Concentration save: non-Halfling keeps the 1
  7. Hide stealth check: Halfling rerolls nat-1
  8. Hide: non-Halfling keeps the 1
  9. Search perception check: Halfling rerolls nat-1
 10. Search: non-Halfling keeps the 1

Each pair (Halfling / non-Halfling) uses a seeded RNG that produces
a nat-1 on the first roll, then a higher value on the reroll. This
makes the test deterministic without depending on probabilities.
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0),
                  is_halfling=False, abilities=None, hp=30,
                  combat=None):
    abs_default = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 14, "save": 2},
        "int": {"score": 14, "save": 2},
        "wis": {"score": 14, "save": 2},
        "cha": {"score": 10, "save": 0},
    }
    if abilities:
        abs_default.update(abilities)
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abs_default,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
        "combat": combat or {"initiative": {"modifier": 2}},
    }
    racial_traits = ["t_lucky"] if is_halfling else []
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=14,
        speed={"walk": 30}, position=position,
        abilities=abs_default,
        racial_traits=racial_traits,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


class _ScriptedRng:
    """Mock RNG returning a fixed sequence of d20 values. Lets tests
    deterministically force nat-1 + reroll sequences."""

    def __init__(self, values):
        self._values = list(values)
        self._idx = 0

    def randint(self, lo, hi):
        if self._idx < len(self._values):
            v = self._values[self._idx]
            self._idx += 1
            return v
        # Exhausted scripted values — fall back to a safe default
        return (lo + hi) // 2

    def random(self):
        return 0.5


# ============================================================================
# Site 1: Initiative
# ============================================================================

class InitiativeLuckyTest(unittest.TestCase):

    def _run_initiative(self, actor, rng_values):
        from engine.core.runner import EncounterRunner
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry
        state = _make_state([actor])
        runner = EncounterRunner(
            encounter=state.encounter,
            event_bus=EventBus(),
            primitives=PrimitiveRegistry.with_defaults(),
            rng=_ScriptedRng(rng_values),
        )
        runner.roll_initiative(state)
        return actor.initiative

    def test_halfling_rerolls_nat_1_initiative(self) -> None:
        # First roll = 1, reroll = 15. With init_mod +2, final = 17
        halfling = _make_actor("h", is_halfling=True,
                                  combat={"initiative": {"modifier": 2}})
        result = self._run_initiative(halfling, [1, 15])
        self.assertEqual(result, 17)

    def test_non_halfling_keeps_nat_1_initiative(self) -> None:
        # First (only) roll = 1, no reroll. Final = 1 + 2 = 3
        human = _make_actor("h", is_halfling=False,
                               combat={"initiative": {"modifier": 2}})
        result = self._run_initiative(human, [1, 15])
        self.assertEqual(result, 3)


# ============================================================================
# Site 2: Counterspell ability check
# ============================================================================

class CounterspellLuckyTest(unittest.TestCase):
    """2024 Counterspell: TARGET caster makes CON save vs counterspeller's
    spell DC. Lucky fires on the target's d20 (not the counterspeller's)."""

    def _resolve_counterspell(self, counterspeller, target_caster,
                                 target_level, rng_values):
        from engine.primitives import _counterspell_resolve
        state = _make_state([counterspeller, target_caster])
        state.current_attack = {
            "actor": counterspeller, "target": target_caster,
            "action": {"id": "a_counterspell"},
        }
        state.cast_cancelled = False
        state.current_attack["reaction_event_data"] = {
            "caster": target_caster,
            "action": {"id": "a_fireball"},
            "spell_slot_level": target_level,
        }
        from engine.core.events import EventBus
        import engine.primitives as primitives_module
        old_rng = primitives_module._rng
        primitives_module._rng = _ScriptedRng(rng_values)
        try:
            _counterspell_resolve({}, state, EventBus())
        finally:
            primitives_module._rng = old_rng
        return state

    def test_halfling_target_rerolls_nat_1_con_save(self) -> None:
        # Counterspeller DC = 8 + 2(INT mod) + 2(PB) = 12.
        # Halfling target CON save +2, rolls nat 1 → reroll 20.
        # Total = 20 + 2 = 22 ≥ 12 → save succeeds → spell resisted.
        wizard = _make_actor("wiz", side="pc")
        halfling_target = _make_actor("h", side="enemy",
                                         is_halfling=True)
        state = self._resolve_counterspell(wizard, halfling_target, 4,
                                              [1, 20])
        events = [e for e in state.event_log
                    if e.get("event") == "counterspell_resolved"]
        self.assertEqual(events[-1]["outcome"], "resisted")

    def test_non_halfling_target_keeps_nat_1_con_save(self) -> None:
        # Same setup but non-Halfling target — keeps the 1.
        # Total = 1 + 2 = 3 < 12 → save fails → spell countered.
        wizard = _make_actor("wiz", side="pc")
        human_target = _make_actor("h", side="enemy",
                                      is_halfling=False)
        state = self._resolve_counterspell(wizard, human_target, 4,
                                              [1, 20])
        events = [e for e in state.event_log
                    if e.get("event") == "counterspell_resolved"]
        self.assertEqual(events[-1]["outcome"], "countered")


# ============================================================================
# Site 3: Concentration save
# ============================================================================

class ConcentrationSaveLuckyTest(unittest.TestCase):

    def _run_concentration_save(self, target, damage, rng_values):
        from engine.core.concentration import attempt_concentration_save
        state = _make_state([target])
        # Set up concentration
        target.concentration_on = {
            "action_id": "a_bless",
            "caster_id": target.id,
            "applied_at_round": 1,
        }
        rng = _ScriptedRng(rng_values)
        attempt_concentration_save(target, damage, state, rng)
        return state, target

    def test_halfling_rerolls_nat_1_concentration(self) -> None:
        # CON save vs DC 10 (damage 5 → ceil(5/2)=3, but max 10).
        # First roll = 1, reroll = 18. CON save +2. Final = 20.
        halfling = _make_actor("h", is_halfling=True)
        state, target = self._run_concentration_save(halfling, 5, [1, 18])
        events = [e for e in state.event_log
                    if e.get("event") == "concentration_save"]
        self.assertEqual(events[-1]["outcome"], "success")
        # Concentration still held
        self.assertIsNotNone(target.concentration_on)

    def test_non_halfling_keeps_nat_1_concentration(self) -> None:
        human = _make_actor("h", is_halfling=False)
        state, target = self._run_concentration_save(human, 5, [1, 18])
        events = [e for e in state.event_log
                    if e.get("event") == "concentration_save"]
        self.assertEqual(events[-1]["outcome"], "fail")
        # Concentration dropped
        self.assertIsNone(target.concentration_on)


# ============================================================================
# Site 4: Hide stealth check
# ============================================================================

class HideLuckyTest(unittest.TestCase):

    def _run_hide(self, actor, rng_values, *, with_obscurement=True):
        from engine.core.pipeline import _execute_hide
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry
        import engine.primitives as primitives_module

        state = _make_state([actor])
        # Hide requires obscurement OR cover. Set the actor to be in
        # heavy obscurement via a zone.
        if with_obscurement:
            state.encounter.environment = {
                "heavily_obscured_zones": [{
                    "shape": "sphere",
                    "center": [actor.position[0], actor.position[1]],
                    "radius_ft": 5,
                }],
            }
        # Mock the module RNG (pipeline uses primitives_module._rng)
        old_rng = primitives_module._rng
        primitives_module._rng = _ScriptedRng(rng_values)
        try:
            _execute_hide(actor, {"id": "a_hide", "type": "hide"},
                            state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        finally:
            primitives_module._rng = old_rng
        return state

    def test_halfling_rerolls_nat_1_hide(self) -> None:
        # DC 15. First roll = 1, reroll = 18. Stealth mod = +2 (DEX)
        # Total = 20 → success
        halfling = _make_actor("h", is_halfling=True)
        state = self._run_hide(halfling, [1, 18])
        events = [e for e in state.event_log
                    if e.get("event") == "hide_attempted"]
        self.assertEqual(events[-1]["outcome"], "success")
        # Sanity: Halfling fixture configured with t_lucky

    def test_non_halfling_keeps_nat_1_hide(self) -> None:
        human = _make_actor("h", is_halfling=False)
        state = self._run_hide(human, [1, 18])
        events = [e for e in state.event_log
                    if e.get("event") == "hide_attempted"]
        self.assertEqual(events[-1]["outcome"], "failed")


# ============================================================================
# Site 5: Search perception check
# ============================================================================

class SearchLuckyTest(unittest.TestCase):

    def _run_search(self, actor, hider, stealth_total, rng_values):
        from engine.core.pipeline import _execute_search
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry
        import engine.primitives as primitives_module

        # Hider has the Hide-source co_invisible condition with the
        # recorded stealth_total. Search rolls Perception vs that.
        hider.applied_conditions.append({
            "condition_id": "co_invisible",
            "source_id": hider.id,
            "source_action_id": "a_hide",
            "stealth_total": stealth_total,
        })
        state = _make_state([actor, hider])
        # _execute_search uses primitives_module._rng for its dice
        old_rng = primitives_module._rng
        primitives_module._rng = _ScriptedRng(rng_values)
        try:
            _execute_search(actor, {"id": "a_search", "type": "search"},
                              state, EventBus(),
                              PrimitiveRegistry.with_defaults())
        finally:
            primitives_module._rng = old_rng
        return state

    def test_halfling_rerolls_nat_1_search(self) -> None:
        # Perception mod +2 (WIS), hider stealth_total = 15.
        # First roll = 1, reroll = 18. Total = 20 → finds hider.
        halfling = _make_actor("seeker", is_halfling=True, side="pc")
        hider = _make_actor("hider", side="enemy", position=(1, 0))
        state = self._run_search(halfling, hider, 15, [1, 18])
        events = [e for e in state.event_log
                    if e.get("event") == "search_check"]
        self.assertEqual(events[-1]["outcome"], "success")

    def test_non_halfling_keeps_nat_1_search(self) -> None:
        human = _make_actor("seeker", is_halfling=False, side="pc")
        hider = _make_actor("hider", side="enemy", position=(1, 0))
        state = self._run_search(human, hider, 15, [1, 18])
        events = [e for e in state.event_log
                    if e.get("event") == "search_check"]
        self.assertEqual(events[-1]["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
