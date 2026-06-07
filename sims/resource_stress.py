"""Resource-model stress test — a deliberately SLOT-BINDING adventuring day.

The calibrated 2024 day (adventuring_day.DAY) doesn't stress an L13 party's
slots: they end it with ~45% of slots unused (right in Tabletop Builds' optimal
"end with 1/3-1/2" band), so the conservation dial barely matters there. This
sim builds a LONGER, front-loaded day where slots actually BIND, to validate
that the dial-gated conservation model (engine.core.spell_slots.candidate_slot_
cost x conservation_strength) produces the predicted behaviour:

  - dial 1 (impact-maximizer): novas slots on the EASY early fights → arrives
    at the Hard/Deadly finale DRY → worse depth/survival.
  - dial 5 (perfect conserver): rations the easy fights (cantrips / weapons) →
    saves slots for the finale → reaches deeper / survives more.

If conservation is doing its job, finale-reach / survival should RISE with the
dial here (unlike the 4-fight calibrated day, where slots don't bind).

The day: many survivable Easy/Medium fights (slot-draining but low-lethality)
building to a Hard fight + the Deadly Bronze Dragon finale, with short rests
(restore HP via Hit Dice, NOT spell slots) so the party stays alive long enough
for slot scarcity — not HP — to be the binding constraint at the finale.

FINDINGS (2026-06, 20 seeds) — this test did NOT produce a slot-binding regime,
and *why* is the result:
  1. The L13 party never reaches the finale: it wipes around fight 3 on
     HP / HIT-DICE attrition (~24 of ~51 slots still in hand). The binding
     adventuring-day resource for a mid-tier 2024 party is HP-RECOVERY capacity
     (hit dice + healing), NOT offensive spell slots.
  2. Root cause the conservation DIAL barely changes behaviour: the slot
     opportunity cost (~6 eHP for a L5 slot) is tiny next to spell value
     (~50-90 eHP), so even a dial-5 "perfect conserver" dumps its top slot on a
     trivial fight. The model subtracts a flat small cost; it never asks the
     conserver's real question — "is this slot NECESSARY to win THIS fight (vs
     a cantrip)?" Real conservation needs MARGINAL-value reasoning, not a flat
     opportunity-cost subtraction.
Kept as the diagnostic that established both points.

Usage:
    python -m sims.resource_stress [n_seeds] [enemy_dial]
"""
from __future__ import annotations

import sys
from pathlib import Path

from engine.loader import load_content
from sims.adventuring_day import run_day

REPO = Path(__file__).resolve().parent.parent

# Front-loaded slot-drain → Hard/Deadly finale. Early fights are Easy/Medium
# (per the measured d_iff in adventuring_day) so the party survives to the
# finale; the question is whether it arrives with slots to spend.
STRESS_DAY = [
    ("Patrol 1",       [("m_wyvern", 2), ("m_manticore", 2)]),   # Easy   ~0.17
    ("Patrol 2",       [("m_vampire_spawn", 4)]),                # Trivial ~0.09
    ("Giant scouts",   [("m_fire_giant", 2)]),                   # Medium ~0.44
    # --- short rest (HP only) ---
    ("Patrol 3",       [("m_wyvern", 3)]),                       # Trivial ~0.14
    ("Giant patrol",   [("m_fire_giant", 2)]),                   # Medium ~0.44
    # --- short rest (HP only) ---
    ("Giant vanguard", [("m_fire_giant", 2), ("m_wyvern", 1)]),  # Hard   ~0.64
    ("FINALE: Bronze Dragon", [("m_adult_bronze_dragon", 1)]),   # Deadly ~1.10
]
STRESS_SHORT_REST_AFTER = {2, 4}   # short-rest after the two Medium fights
N_ENC = len(STRESS_DAY)


def main():
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    enemy_dial = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    registry = load_content(REPO / "schema" / "content", validate=True,
                             schema_root=REPO / "schema" / "definitions")

    print(f"=== RESOURCE-STRESS DIAL CURVE — {n_seeds} seeds, "
          f"slot-binding {N_ENC}-fight day, enemy dial {enemy_dial} ===")
    print("(does conservation help when slots actually BIND? finale-reach / "
          "survival should rise with the dial)\n")
    print(f"{'PC dial':>7} {'avg cleared':>12} {'reach finale':>13} "
          f"{'survive':>8} {'slots left @finale':>18}")
    for pc_dial in (1, 2, 3, 4, 5):
        cleared = reached = survived = 0
        slots_at_finale = 0.0
        for seed in range(1, n_seeds + 1):
            res = run_day(registry, seed, pc_dial=pc_dial, enemy_dial=enemy_dial,
                          day=STRESS_DAY, short_rest_after=STRESS_SHORT_REST_AFTER)
            cleared += res["cleared"]
            reached += 1 if res["reached_dragon"] else 0
            survived += 1 if res["survived"] else 0
            # slots remaining entering the finale = slots_left of the
            # second-to-last row that ran (or last row reached).
            reached_rows = res["rows"]
            if len(reached_rows) >= N_ENC:
                slots_at_finale += reached_rows[-1]["slots_left"] \
                    + reached_rows[-1]["slots_spent"]   # pre-finale count
        print(f"{pc_dial:>7} {cleared / n_seeds:>11.1f}/{N_ENC} "
              f"{100 * reached / n_seeds:>11.0f}% {100 * survived / n_seeds:>7.0f}% "
              f"{slots_at_finale / n_seeds:>18.1f}")
    print("\nIf the dial-gated conservation model works WHERE SLOTS BIND, the "
          "higher dials reach the finale + survive more (they saved slots the "
          "impact-maximizer burned on trash fights).")


if __name__ == "__main__":
    main()
