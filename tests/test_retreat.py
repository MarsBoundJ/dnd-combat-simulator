"""Retreat dial v1 tests — DMG p48 algorithm + 5 presets.

Layers:
  1. Pure data — preset bundle table correctness
  2. Trigger evaluator — bloodied / ally-disparity / frightened
  3. Compound logic — Resolute needs Bloodied AND another trigger
  4. Mindless override — INT ≤ 2 / mindless_aggressor never flees
  5. WIS save — Cowardly often flees, Resolute rarely flees
  6. Runner integration — goblin in smoke encounter triggers + flees

Run via:
    python -m unittest tests.test_retreat
"""
from __future__ import annotations

import random
import unittest

from engine.ai import (
    RETREAT_PRESETS, get_retreat_bundle, check_retreat,
    resolve_retreat_preset_for_actor,
)
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Test helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy",
                hp: int = 50, hp_current: int | None = None,
                ac: int = 15, int_score: int = 10, wis_save: int = 0,
                actions: list[dict] | None = None,
                archetype: str | None = None,
                presets: dict | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": int_score, "save": (int_score - 10) // 2},
        "wis": {"score": 10 + 2 * wis_save, "save": wis_save},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    bp: dict = {}
    if archetype:
        bp["archetype"] = archetype
    if presets:
        bp["presets"] = presets
    if bp:
        template["behavior_profile"] = bp
    if template_extras:
        template.update(template_extras)
    actor = Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=hp if hp_current is None else hp_current,
                   hp_max=hp, ac=ac, abilities=abilities)
    return actor


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _apply_frightened(actor: Actor) -> None:
    """Mark the actor as Frightened (the retreat algorithm reads
    applied_conditions for the co_frightened marker)."""
    actor.applied_conditions.append({
        "condition_id": "co_frightened",
        "source_id": "test",
        "applied_at_round": 0,
        "duration": "until_combat_ends",
    })


# ============================================================================
# Preset bundle table
# ============================================================================

class PresetBundleTest(unittest.TestCase):

    def test_all_five_presets_in_table(self) -> None:
        self.assertEqual(set(RETREAT_PRESETS),
                          {"ftd", "resolute", "default", "cowardly",
                           "pacifist"})

    def test_ftd_has_no_bundle(self) -> None:
        self.assertIsNone(get_retreat_bundle("ftd"))

    def test_resolute_thresholds_per_spec(self) -> None:
        b = get_retreat_bundle("resolute")
        self.assertAlmostEqual(b.bloodied_pct, 0.35)
        self.assertAlmostEqual(b.ally_disparity_pct, 0.75)
        self.assertFalse(b.frightened_alone_sufficient)
        self.assertEqual(b.in_combat_dc, 8)

    def test_cowardly_thresholds_per_spec(self) -> None:
        b = get_retreat_bundle("cowardly")
        self.assertAlmostEqual(b.bloodied_pct, 0.60)
        # "1 ally falls" → small positive fraction (any ally down triggers)
        self.assertLess(b.ally_disparity_pct, 0.01)
        self.assertTrue(b.frightened_alone_sufficient)
        self.assertEqual(b.in_combat_dc, 13)

    def test_default_thresholds_per_spec(self) -> None:
        b = get_retreat_bundle("default")
        self.assertAlmostEqual(b.bloodied_pct, 0.50)
        self.assertAlmostEqual(b.ally_disparity_pct, 0.50)
        self.assertTrue(b.frightened_alone_sufficient)
        self.assertEqual(b.in_combat_dc, 10)


# ============================================================================
# Mindless override
# ============================================================================

class MindlessOverrideTest(unittest.TestCase):

    def test_int_2_never_flees(self) -> None:
        zombie = _make_actor("z", int_score=2, hp=10, hp_current=1,
                              presets={"retreat": "cowardly"})
        state = _state_with([zombie])
        rng = random.Random(0)
        # Even at 1/10 HP with Cowardly preset, INT 2 short-circuits
        self.assertIsNone(check_retreat(zombie, state, rng))

    def test_mindless_aggressor_archetype_never_flees(self) -> None:
        ooze = _make_actor("o", archetype="mindless_aggressor",
                            hp=10, hp_current=1, int_score=5,
                            presets={"retreat": "cowardly"})
        state = _state_with([ooze])
        rng = random.Random(0)
        self.assertIsNone(check_retreat(ooze, state, rng))

    def test_smart_creature_still_evaluates(self) -> None:
        smart = _make_actor("s", int_score=12, hp=10, hp_current=1,
                             presets={"retreat": "cowardly"})
        state = _state_with([smart])
        # With many seeds, at least one should produce a flee result.
        flees = sum(
            1 for s in range(50)
            if check_retreat(smart, state, random.Random(s)) is not None
        )
        self.assertGreater(flees, 0,
                            "Smart Cowardly creature at 1/10 HP should flee at "
                            "least sometimes")


# ============================================================================
# FtD preset
# ============================================================================

class FTDPresetTest(unittest.TestCase):

    def test_ftd_never_flees_regardless_of_state(self) -> None:
        zealot = _make_actor("z", hp=10, hp_current=1, int_score=10,
                              presets={"retreat": "ftd"})
        state = _state_with([zealot])
        for s in range(20):
            self.assertIsNone(check_retreat(zealot, state, random.Random(s)),
                               f"FtD never flees (seed {s})")


# ============================================================================
# Trigger evaluation
# ============================================================================

class BloodiedTriggerTest(unittest.TestCase):

    def test_above_bloodied_no_trigger(self) -> None:
        """Default preset bloodied = 50%; at 60% HP, no trigger."""
        actor = _make_actor("a", hp=10, hp_current=6, int_score=10,
                             presets={"retreat": "default"})
        state = _state_with([actor])
        self.assertIsNone(check_retreat(actor, state, random.Random(0)))

    def test_at_bloodied_triggers_and_rolls(self) -> None:
        """At 50% HP, Default preset triggers Bloodied. Whether the WIS
        save passes or fails is rng-dependent; verify retreat_triggered
        event lands on a flee outcome."""
        actor = _make_actor("a", hp=10, hp_current=5, int_score=10,
                             wis_save=-3,   # very bad save → likely fail
                             presets={"retreat": "default"})
        state = _state_with([actor])
        # Use many seeds, find one that flees
        flee_count = 0
        for s in range(50):
            actor.applied_conditions = []  # reset
            state.event_log = []
            if check_retreat(actor, state, random.Random(s)) is not None:
                flee_count += 1
                triggered = [e for e in state.event_log
                              if e["event"] == "retreat_triggered"]
                self.assertEqual(len(triggered), 1)
                self.assertIn("bloodied", triggered[0]["triggers"])
        self.assertGreater(flee_count, 10,
                            f"At 5/10 HP w/ -3 WIS save, should flee often "
                            f"(got {flee_count}/50)")


class AllyDisparityTriggerTest(unittest.TestCase):

    def test_no_allies_no_disparity_trigger(self) -> None:
        """Lone actor has no disparity signal — fraction is 0."""
        lone = _make_actor("a", hp=10, hp_current=10, int_score=10,
                            presets={"retreat": "cowardly"})
        state = _state_with([lone])
        # At full HP with no allies and no frightened → no trigger
        self.assertIsNone(check_retreat(lone, state, random.Random(0)))

    def test_one_of_two_allies_down_triggers_cowardly(self) -> None:
        """Cowardly preset triggers on ANY ally falling (ally_disparity_pct ≈ 0)."""
        actor = _make_actor("a", hp=10, hp_current=10, int_score=10,
                             wis_save=-5,   # poor save
                             presets={"retreat": "cowardly"})
        ally = _make_actor("ally", hp=10, hp_current=10, int_score=10)
        ally.is_dead = True
        ally.hp_current = 0
        state = _state_with([actor, ally])
        # Many seeds; some should flee due to ally_disparity trigger
        flees = 0
        for s in range(50):
            state.event_log = []
            if check_retreat(actor, state, random.Random(s)) is not None:
                flees += 1
        self.assertGreater(flees, 10,
                            f"Cowardly at full HP with ally down should flee "
                            f"often (got {flees}/50)")

    def test_default_50pct_disparity_needs_half_allies_down(self) -> None:
        """Default ally_disparity_pct = 0.50. 1 of 4 allies down (25%) → no trigger."""
        actor = _make_actor("a", hp=10, hp_current=10, int_score=10,
                             presets={"retreat": "default"})
        allies = [_make_actor(f"ally{i}", hp=10, int_score=10)
                   for i in range(4)]
        allies[0].is_dead = True
        allies[0].hp_current = 0
        state = _state_with([actor] + allies)
        # Only 1 of 4 allies (25%) down → no trigger from disparity, full HP
        self.assertIsNone(check_retreat(actor, state, random.Random(0)))


class FrightenedTriggerTest(unittest.TestCase):

    def test_default_frightened_alone_triggers(self) -> None:
        """Default preset: frightened_alone_sufficient=True."""
        actor = _make_actor("a", hp=10, hp_current=10, int_score=10,
                             wis_save=-5,
                             presets={"retreat": "default"})
        _apply_frightened(actor)
        state = _state_with([actor])
        # With many seeds, at least some should flee
        flees = sum(
            1 for s in range(50)
            if check_retreat(actor, state, random.Random(s)) is not None
        )
        self.assertGreater(flees, 10,
                            f"Default Frightened-alone should trigger flees "
                            f"often (got {flees}/50)")

    def test_resolute_frightened_alone_does_not_trigger(self) -> None:
        """Resolute: must also be Bloodied or have ally disparity. Frightened
        ALONE (full HP, no fallen allies) should not trigger."""
        actor = _make_actor("a", hp=10, hp_current=10, int_score=10,
                             wis_save=-5,
                             presets={"retreat": "resolute"})
        _apply_frightened(actor)
        state = _state_with([actor])
        # Even with bad WIS save and many seeds, NEVER flees because
        # Resolute requires Bloodied AND another trigger
        for s in range(50):
            self.assertIsNone(check_retreat(actor, state, random.Random(s)),
                               f"Resolute Frightened-alone should never flee "
                               f"(seed {s})")

    def test_resolute_bloodied_and_frightened_triggers(self) -> None:
        """Resolute: Bloodied (35% threshold) + Frightened should trigger."""
        actor = _make_actor("a", hp=10, hp_current=3, int_score=10,
                             wis_save=-5,   # poor save
                             presets={"retreat": "resolute"})
        _apply_frightened(actor)
        state = _state_with([actor])
        flees = sum(
            1 for s in range(50)
            if check_retreat(actor, state, random.Random(s)) is not None
        )
        self.assertGreater(flees, 10,
                            f"Resolute Bloodied+Frightened with -5 WIS save "
                            f"should flee sometimes (got {flees}/50)")


# ============================================================================
# WIS save mechanics — Resolute resists, Cowardly often flees
# ============================================================================

class WisSaveOutcomeTest(unittest.TestCase):

    def test_resolute_low_dc_rarely_flees_at_threshold(self) -> None:
        """Resolute DC = 8 (easy save). With +3 WIS save, average creature
        passes ~80%. Need ally-disparity AND bloodied to even roll."""
        actor = _make_actor("a", hp=10, hp_current=3, int_score=10,
                             wis_save=3,   # decent save
                             presets={"retreat": "resolute"})
        ally = _make_actor("ally", hp=10, int_score=10)
        ally.is_dead = True; ally.hp_current = 0
        # Need 4 allies total so disparity = 1/4 < 75% — make 3 more dead
        ally2 = _make_actor("ally2", hp=10, int_score=10)
        ally2.is_dead = True; ally2.hp_current = 0
        ally3 = _make_actor("ally3", hp=10, int_score=10)
        ally3.is_dead = True; ally3.hp_current = 0
        ally4 = _make_actor("ally4", hp=10, int_score=10)  # alive
        state = _state_with([actor, ally, ally2, ally3, ally4])
        # 3/4 = 75% disparity (just meets > threshold)
        flees = sum(
            1 for s in range(100)
            if check_retreat(actor, state, random.Random(s)) is not None
        )
        # Resolute DC 8 + WIS+3 → need 5+ on d20 = 80% save success
        # Expect flees ~20%. Tolerance ±10pp.
        rate = flees / 100
        self.assertLess(rate, 0.40,
                          f"Resolute should resist most rolls (got {rate})")

    def test_cowardly_high_dc_often_flees(self) -> None:
        """Cowardly DC = 13 (hard save). With -1 WIS save, ~30% save success;
        70% flee rate. At 5/10 HP (50% < 60% bloodied threshold) triggers."""
        actor = _make_actor("a", hp=10, hp_current=5, int_score=10,
                             wis_save=-1,
                             presets={"retreat": "cowardly"})
        state = _state_with([actor])
        flees = sum(
            1 for s in range(100)
            if check_retreat(actor, state, random.Random(s)) is not None
        )
        # Cowardly DC 13 + WIS-1 → need 14+ on d20 = 35% save success
        # → ~65% flee rate. Tolerance ±15pp.
        rate = flees / 100
        self.assertGreater(rate, 0.45,
                            f"Cowardly with poor save should flee often "
                            f"(got {rate})")
        self.assertLess(rate, 0.85)


# ============================================================================
# Preset resolution from actor template + archetype
# ============================================================================

class ResolvePresetTest(unittest.TestCase):

    def test_explicit_preset_overrides_archetype(self) -> None:
        actor = _make_actor("a", archetype="cowardly_skirmisher",
                             presets={"retreat": "ftd"})
        self.assertEqual(resolve_retreat_preset_for_actor(actor), "ftd")

    def test_cowardly_skirmisher_archetype_defaults_to_cowardly(self) -> None:
        actor = _make_actor("a", archetype="cowardly_skirmisher")
        self.assertEqual(resolve_retreat_preset_for_actor(actor), "cowardly")

    def test_apex_predator_archetype_defaults_to_resolute(self) -> None:
        actor = _make_actor("a", archetype="apex_predator")
        self.assertEqual(resolve_retreat_preset_for_actor(actor), "resolute")

    def test_mindless_aggressor_archetype_defaults_to_ftd(self) -> None:
        actor = _make_actor("a", archetype="mindless_aggressor")
        self.assertEqual(resolve_retreat_preset_for_actor(actor), "ftd")


# ============================================================================
# Event log shape
# ============================================================================

class EventLogShapeTest(unittest.TestCase):

    def test_flee_logs_triggered_save_and_returns_dict(self) -> None:
        actor = _make_actor("a", hp=10, hp_current=1, int_score=10,
                             wis_save=-5,  # near-guaranteed flee
                             presets={"retreat": "cowardly"})
        state = _state_with([actor])
        # Find a seed that produces a flee
        result = None
        for s in range(50):
            state.event_log = []
            result = check_retreat(actor, state, random.Random(s))
            if result is not None:
                break
        self.assertIsNotNone(result, "Should have found a flee in 50 seeds")
        self.assertIn("preset", result)
        self.assertEqual(result["preset"], "cowardly")
        self.assertIn("bloodied", result["triggers"])

        # Event log should contain retreat_triggered + retreat_save
        events = [e["event"] for e in state.event_log]
        self.assertIn("retreat_triggered", events)
        self.assertIn("retreat_save", events)
        # retreat_save outcome should be 'fail'
        save_event = next(e for e in state.event_log
                           if e["event"] == "retreat_save")
        self.assertEqual(save_event["outcome"], "fail")

    def test_pass_save_does_not_return_retreat(self) -> None:
        """Successful WIS save → no retreat returned; events still log
        the trigger + save outcome."""
        actor = _make_actor("a", hp=10, hp_current=5, int_score=10,
                             wis_save=20,  # auto-pass DC 13
                             presets={"retreat": "cowardly"})
        state = _state_with([actor])
        result = check_retreat(actor, state, random.Random(0))
        self.assertIsNone(result, "+20 save should always pass DC 13")
        # But the trigger event still logged
        events = [e["event"] for e in state.event_log]
        self.assertIn("retreat_triggered", events)
        self.assertIn("retreat_save", events)


# ============================================================================
# Runner integration — smoke encounter goblin flees
# ============================================================================

class RunnerRetreatIntegrationTest(unittest.TestCase):

    def test_smoke_encounter_goblin_can_flee(self) -> None:
        """Run the smoke encounter at a seed known to trigger flee, verify
        the goblin escapes alive with a 'fled' event in the log."""
        import random as _random
        from pathlib import Path
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner
        from engine.cli import _build_encounter
        from engine.loader import load_content, load_yaml_file

        repo_root = Path(__file__).parent.parent
        content_root = repo_root / "schema" / "content"
        schema_root = repo_root / "schema" / "definitions"
        fixture = Path(__file__).parent / "fixtures" / "smoke_encounter.yaml"

        registry = load_content(content_root, validate=True,
                                  schema_root=schema_root)

        # Try several seeds; at least one should produce a flee outcome
        found_flee = False
        for seed in (5, 7, 17, 42, 1, 2, 3, 4, 6, 8):
            spec = load_yaml_file(fixture)
            encounter = _build_encounter(spec, registry)
            primitives_module.set_rng(_random.Random(seed))
            runner = EncounterRunner.new(encounter, seed=seed,
                                           content_registry=registry)
            primitives_module.set_rng(runner.rng)
            state = runner.run(seed=seed)

            fled_events = [e for e in state.event_log
                            if e.get("event") == "fled"
                            and e.get("actor") == "goblin_1"]
            if fled_events:
                found_flee = True
                # Verify flee event has telemetry fields
                ev = fled_events[0]
                self.assertEqual(ev.get("preset"), "cowardly")
                self.assertIn("bloodied", ev.get("triggers", []))
                # Verify the goblin is alive but fled
                goblin = next(a for a in encounter.actors if a.id == "goblin_1")
                self.assertTrue(goblin.is_fled)
                self.assertFalse(goblin.is_dead)
                self.assertGreater(goblin.hp_current, 0)
                break

        self.assertTrue(found_flee,
                         "Cowardly goblin should flee in at least one seed "
                         "out of 10 tries")


if __name__ == "__main__":
    unittest.main()
