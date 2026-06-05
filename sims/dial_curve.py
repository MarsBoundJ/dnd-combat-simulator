"""Adventuring-day power-level CURVE across the optimization dial.

Runs the full calibrated day at PC dials 1-5 (monsters held at a baseline dial,
default 1) over N seeds, and reports how the day outcome scales with party
play-skill: average encounters cleared, % that reach the dragon, % that survive
the whole day. This is the Trusight-shaped output — a build's/day's power level
depends on HOW WELL it's played, and now we can quantify that dependence.

Usage:
    python sims/dial_curve.py [n_seeds] [enemy_dial]
        n_seeds    : seeds 1..N per dial (default 10)
        enemy_dial : monster dial held fixed across the sweep (default 1)
"""
from __future__ import annotations

import sys
from pathlib import Path

from engine.loader import load_content
from sims.adventuring_day import run_day, DAY

REPO = Path(__file__).resolve().parent.parent


def main():
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    enemy_dial = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    registry = load_content(REPO / "schema" / "content", validate=True,
                             schema_root=REPO / "schema" / "definitions")
    n_enc = len(DAY)

    print(f"=== ADVENTURING-DAY DIAL CURVE — {n_seeds} seeds/dial, "
          f"enemy dial held at {enemy_dial} ===")
    print(f"(day = {n_enc} encounters: Low -> 4x Moderate -> High climax)\n")
    print(f"{'PC dial':>7} {'avg cleared':>12} {'reach dragon':>13} "
          f"{'survive day':>12}")
    for pc_dial in (1, 2, 3, 4, 5):
        cleared_total = 0
        reached = 0
        survived = 0
        for seed in range(1, n_seeds + 1):
            res = run_day(registry, seed, pc_dial=pc_dial, enemy_dial=enemy_dial)
            cleared_total += res["cleared"]
            reached += 1 if res["reached_dragon"] else 0
            survived += 1 if res["survived"] else 0
        print(f"{pc_dial:>7} {cleared_total / n_seeds:>11.1f}/{n_enc} "
              f"{100 * reached / n_seeds:>11.0f}% {100 * survived / n_seeds:>11.0f}%")
    print("\nHigher PC dial = more focus-fire (when warranted) = deeper into "
          "the day. Enemy dial is the 'WoTC baseline vs optimal' knob.")


if __name__ == "__main__":
    main()
