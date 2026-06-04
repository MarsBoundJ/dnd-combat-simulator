"""Monte Carlo over the run-3 boss encounter — quantify the variance and
the squishy-alpha-death finding before deciding on a fix.

Runs N seeds of the spread-formation Tier-3 party vs Adult Red Dragon (the
full positioning + spell stack), and reports:
  - outcome split (party win / dragon win / round-cap)
  - rounds + party-damage + dragon-final-HP distribution
  - PER-PC death-round histogram (the alpha-death signal: how often does the
    Wizard/Bard die by round 2?)

Usage: python sims/boss_montecarlo.py [N]   (default 60)
"""
from __future__ import annotations

import statistics
import sys

from sims.run_boss_sim import build_and_run


def _summarize(state, actors):
    pcs = [a for a in actors if a.side == "pc"]
    dragon = next(a for a in actors if a.side == "enemy")

    # Per-PC death round: track current round; record the round of the last
    # damage that left a (finally-dead) PC at 0. Survivors -> None.
    cur = 0
    last_dmg_round = {a.id: None for a in pcs}
    party_dmg = 0
    for e in state.event_log:
        if e.get("event") == "turn_start":
            cur = e.get("round", cur)
        elif e.get("event") == "damage_dealt":
            tgt = e.get("target")
            if tgt in last_dmg_round and e.get("target_hp_remaining") == 0:
                last_dmg_round[tgt] = cur
            if tgt == dragon.id and e.get("actor") in {p.id for p in pcs}:
                party_dmg += e.get("amount", 0)

    death_round = {}
    for p in pcs:
        if p.is_dead:
            death_round[p.id] = last_dmg_round[p.id] or cur
        else:
            death_round[p.id] = None   # survived (alive or fled)

    reason = state.termination_reason
    if reason == "side_pc_victory":
        outcome = "WIN"
    elif reason == "side_enemy_victory":
        outcome = "LOSS"
    else:
        outcome = "CAP"
    return {
        "outcome": outcome, "rounds": state.round, "party_dmg": party_dmg,
        "dragon_hp": dragon.hp_current, "death_round": death_round,
        "pc_ids": [p.id for p in pcs],
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    runs = []
    for seed in range(1, n + 1):
        state, actors = build_and_run(seed)
        runs.append(_summarize(state, actors))

    outcomes = {"WIN": 0, "LOSS": 0, "CAP": 0}
    for r in runs:
        outcomes[r["outcome"]] += 1
    dmg = sorted(r["party_dmg"] for r in runs)
    rounds = [r["rounds"] for r in runs]
    dragon_hp = sorted(r["dragon_hp"] for r in runs)
    pc_ids = runs[0]["pc_ids"]

    print(f"=== BOSS MONTE CARLO — {n} seeds (spread formation, full stack) ===\n")
    print(f"Outcomes:  WIN {outcomes['WIN']} ({100*outcomes['WIN']//n}%)  |  "
          f"LOSS {outcomes['LOSS']} ({100*outcomes['LOSS']//n}%)  |  "
          f"round-cap {outcomes['CAP']} ({100*outcomes['CAP']//n}%)")
    print(f"Rounds:    min {min(rounds)}  median {int(statistics.median(rounds))}  max {max(rounds)}")
    print(f"Party dmg: min {dmg[0]}  median {int(statistics.median(dmg))}  "
          f"mean {int(statistics.mean(dmg))}  max {dmg[-1]}")
    print(f"Dragon HP at end (of 256): min {dragon_hp[0]}  "
          f"median {int(statistics.median(dragon_hp))}  max {dragon_hp[-1]}")
    print()
    print("PC death-round distribution (R1/R2 = alpha-death; — = survived):")
    print(f"  {'pc':<18} {'R1':>4} {'R2':>4} {'R3+':>5} {'survived':>9} {'avg death rd':>13}")
    for pid in pc_ids:
        r1 = sum(1 for r in runs if r["death_round"][pid] == 1)
        r2 = sum(1 for r in runs if r["death_round"][pid] == 2)
        r3 = sum(1 for r in runs if (r["death_round"][pid] or 0) >= 3)
        surv = sum(1 for r in runs if r["death_round"][pid] is None)
        deaths = [r["death_round"][pid] for r in runs if r["death_round"][pid]]
        avg = f"{statistics.mean(deaths):.1f}" if deaths else "-"
        print(f"  {pid:<18} {r1:>4} {r2:>4} {r3:>5} {surv:>9} {avg:>13}")


if __name__ == "__main__":
    main()
