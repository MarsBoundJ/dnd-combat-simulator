"""Smoke test — proves the engine architecture works end-to-end.

Loads the SRD content + a Fighter-vs-Goblin encounter fixture, runs the
encounter to termination, asserts a sane outcome.

Run via:
    python -m unittest tests.test_smoke
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.cli import _build_encounter
from engine.core.runner import EncounterRunner
from engine.loader import load_content, load_yaml_file
from engine.reports import EncounterReport
from engine import primitives as primitives_module
import random


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
FIXTURE = Path(__file__).parent / "fixtures" / "smoke_encounter.yaml"


class SmokeTest(unittest.TestCase):
    """End-to-end smoke test: Fighter vs Goblin runs to completion."""

    def test_content_loads(self) -> None:
        """All schema/content YAML files load + lite-validate."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        counts = registry.count()
        self.assertGreaterEqual(counts["condition"], 15,
                                f"Expected 15+ conditions, got {counts['condition']}")
        self.assertGreaterEqual(counts["class"], 2)
        self.assertGreaterEqual(counts["subclass"], 2)
        self.assertGreaterEqual(counts["monster"], 1)
        self.assertGreaterEqual(counts["spell"], 3)

    def test_encounter_runs_to_termination(self) -> None:
        """Goblin vs Fighter terminates within MAX_ROUNDS."""
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        spec = load_yaml_file(FIXTURE)
        encounter = _build_encounter(spec, registry)

        # Seed for determinism
        primitives_module.set_rng(random.Random(42))
        runner = EncounterRunner.new(encounter, seed=42)
        primitives_module.set_rng(runner.rng)

        state = runner.run(seed=42)
        self.assertTrue(state.terminated, "Encounter must terminate")
        self.assertNotEqual(state.termination_reason, "round_cap_reached",
                            "Encounter should end well before round cap.")

    def test_fighter_likely_wins(self) -> None:
        """Statistically: Fighter AC 18 + 1d8+3 vs Goblin AC 15 + 1d6+2 — Fighter should win most of the time.

        Run 20 trials with different seeds; assert fighter wins majority.
        Validates the architecture handles random outcomes correctly across runs.
        """
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        spec = load_yaml_file(FIXTURE)

        fighter_wins = 0
        for seed in range(1, 21):
            encounter = _build_encounter(spec, registry)
            primitives_module.set_rng(random.Random(seed))
            runner = EncounterRunner.new(encounter, seed=seed)
            primitives_module.set_rng(runner.rng)
            state = runner.run(seed=seed)
            report = EncounterReport.from_state(state)
            if report.winning_side == "pc":
                fighter_wins += 1

        self.assertGreaterEqual(fighter_wins, 12,
                                f"Fighter should win majority of 20 trials, got {fighter_wins}/20")

    def test_report_serializable(self) -> None:
        """EncounterReport.to_json() produces valid JSON."""
        import json
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        spec = load_yaml_file(FIXTURE)
        encounter = _build_encounter(spec, registry)
        primitives_module.set_rng(random.Random(7))
        runner = EncounterRunner.new(encounter, seed=7)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=7)
        report = EncounterReport.from_state(state)
        # to_json must produce valid JSON
        as_json = report.to_json()
        parsed = json.loads(as_json)
        self.assertIn("encounter_id", parsed)
        self.assertIn("actors", parsed)


if __name__ == "__main__":
    unittest.main()
