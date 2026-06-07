"""Per-fight EMPIRICAL difficulty (Tom Dunn's d_iff) across the adventuring day.

For each encounter in `adventuring_day.DAY`, runs a FRESH full party N times and
reports the average empirical d_iff (gross damage the PCs took / party total max
HP, from the contribution ledger), classified into Dunn's bands, alongside the
realized win rate and round count. Fresh party per fight isolates each
encounter's intrinsic difficulty from day attrition.

Why this matters: the 2024 XP-budget LABEL (Low/Moderate/High) and the realized
d_iff diverge because 2024 monsters hit harder than the 2014 baseline Dunn's
bands were fit to (esp. legendary CR10+ ~+40% DPR / CR13+ ~+15% HP). This tool
measures the gap — the calibration signal for recalibrating the day, and a
Trusight per-encounter difficulty asset.

Usage:
    python -m sims.day_difficulty [n_seeds] [pc_dial] [enemy_dial]
        n_seeds    : seeds 1..N per encounter (default 20)
        pc_dial    : party optimization dial 1-5 (default 3 = WoTC baseline)
        enemy_dial : monster optimization dial 1-5 (default 1)
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

from engine.loader import load_content
from engine.core.state import Encounter
from engine.core.runner import EncounterRunner
from engine.core.combat_metrics import build_contribution_ledger, classify_diff
import engine.primitives as primitives_module
from sims.adventuring_day import _build_party, _build_monsters, DAY

REPO = Path(__file__).resolve().parent.parent


def main():
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    pc_dial = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    enemy_dial = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    registry = load_content(REPO / "schema" / "content", validate=True,
                             schema_root=REPO / "schema" / "definitions")

    print(f"=== PER-FIGHT EMPIRICAL d_iff — {n_seeds} seeds, fresh party, "
          f"PC dial {pc_dial}, enemy dial {enemy_dial} ===")
    print("(d_iff = gross damage PCs took / party total HP; Dunn bands: "
          "Trivial<.15 Easy<.30 Medium<.45 Hard<.70 Deadly<1.0 TPK>=1.0)\n")
    print(f"{'encounter':26} {'avg d_iff':>9} {'band':>8} "
          f"{'rounds':>7} {'win%':>6}")
    day_diff = 0.0
    for name, monster_counts in DAY:
        diffs, rounds, wins = [], [], 0
        for seed in range(1, n_seeds + 1):
            party = _build_party(registry)
            monsters = _build_monsters(registry, monster_counts)
            primitives_module.set_rng(random.Random(seed))
            enc = Encounter(id="e", actors=party + monsters)
            runner = EncounterRunner.new(enc, seed=seed,
                                          content_registry=registry)
            primitives_module.set_rng(runner.rng)
            state = runner.run(seed=seed, encounters_remaining_today=0,
                               optimization_dials={"pc": pc_dial,
                                                   "enemy": enemy_dial})
            led = build_contribution_ledger(state)
            diffs.append(led["d_iff"])
            rounds.append(led["rounds"])
            if state.termination_reason == "side_pc_victory":
                wins += 1
        avg = sum(diffs) / n_seeds
        day_diff += avg
        print(f"{name[:26]:26} {avg:>9.2f} {classify_diff(avg):>8} "
              f"{sum(rounds) / n_seeds:>7.1f} {100 * wins / n_seeds:>5.0f}%")
    print(f"\nDAY cumulative d_iff (sum of per-fight avgs): {day_diff:.2f}")
    print("A fight's d_iff running HOTTER than its XP-budget label = the "
          "2024-monster-buff gap. Retune toward each fight's intended band.")


if __name__ == "__main__":
    main()
