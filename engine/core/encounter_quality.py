"""Encounter quality rubric — per-run and aggregate metrics for measuring
whether an encounter is "good": challenging but not TPK, not a slog, with
tension and forced adaptation.

Per-run metrics (from a single finished CombatState):
  - outcome          : WIN / LOSS / CAP (round cap reached)
  - rounds           : how many rounds the fight lasted
  - pc_deaths        : number of PCs who died
  - d_iff            : Dunn difficulty metric (gross damage taken / party HP)
  - tension          : how close the party came to TPK (min party HP ratio)
  - rounds_critical  : rounds where party HP was below 50%
  - swing_count      : momentum reversals (side-advantage flips)

Aggregate metrics (from N runs of the same encounter):
  - win_rate         : fraction of runs the party won
  - tpk_rate         : fraction of runs the party lost
  - death_rate       : fraction of runs with at least one PC death
  - median_rounds    : median fight length
  - mean_tension     : average tension across runs
  - quality_grade    : A-F grade summarizing overall encounter quality

Quality grading:
  A = sweet spot (win 65-80%, death 15-40%, TPK <5%, not a slog)
  B = good (win 55-85%, death 10-50%, TPK <10%)
  C = acceptable (win 40-90%, death 5-60%, TPK <15%)
  D = problematic (outside C bands)
  F = broken (win <20% or >95%, TPK >25%, or median >20 rounds)
"""
from __future__ import annotations

from engine.core.state import CombatState


def analyze_run(state: CombatState) -> dict:
    """Extract per-run quality metrics from a finished encounter."""
    pcs = [a for a in state.encounter.actors if a.side == "pc"]
    pc_ids = {p.id for p in pcs}
    pc_total_hp = sum(max(1, p.hp_max) for p in pcs)

    reason = state.termination_reason
    if reason == "side_pc_victory":
        outcome = "WIN"
    elif reason == "side_enemy_victory":
        outcome = "LOSS"
    else:
        outcome = "CAP"

    pc_deaths = sum(1 for p in pcs if p.is_dead)

    # Reconstruct party HP curve from the event log to compute tension.
    # Start at full HP, track damage/healing as events arrive.
    hp = {p.id: float(p.hp_max) for p in pcs}
    min_party_hp = float(pc_total_hp)
    cur_round = 0
    rounds_critical = 0
    round_min_hp = float(pc_total_hp)

    # Per-round side advantage for swing detection: positive = party ahead,
    # negative = enemy ahead. A swing is a sign flip between rounds.
    side_advantage_by_round: dict[int, float] = {}
    pc_dmg_this_round = 0.0
    enemy_dmg_this_round = 0.0

    def _actor_side(aid):
        for a in state.encounter.actors:
            if a.id == aid:
                return a.side
        return "?"

    for e in state.event_log:
        ev = e.get("event")
        if ev == "turn_start":
            prev_round = cur_round
            cur_round = int(e.get("round", cur_round))
            if cur_round != prev_round and prev_round > 0:
                if round_min_hp < 0.5 * pc_total_hp:
                    rounds_critical += 1
                side_advantage_by_round[prev_round] = (
                    pc_dmg_this_round - enemy_dmg_this_round)
                pc_dmg_this_round = 0.0
                enemy_dmg_this_round = 0.0
                round_min_hp = sum(hp.values())
        elif ev == "damage_dealt":
            tid = e.get("target")
            aid = e.get("actor")
            amt = float(e.get("amount", 0))
            if tid in pc_ids:
                hp[tid] = max(0.0, hp[tid] - amt)
                party_hp_now = sum(hp.values())
                min_party_hp = min(min_party_hp, party_hp_now)
                round_min_hp = min(round_min_hp, party_hp_now)
            if aid and _actor_side(aid) == "pc" and _actor_side(tid) != "pc":
                pc_dmg_this_round += amt
            elif aid and _actor_side(aid) != "pc" and tid in pc_ids:
                enemy_dmg_this_round += amt
        elif ev == "healed":
            tid = e.get("target")
            amt = float(e.get("amount", 0))
            if tid in pc_ids:
                pid_max = next((p.hp_max for p in pcs if p.id == tid), 0)
                hp[tid] = min(float(pid_max), hp[tid] + amt)

    # Finalize last round
    if cur_round > 0:
        if round_min_hp < 0.5 * pc_total_hp:
            rounds_critical += 1
        side_advantage_by_round[cur_round] = (
            pc_dmg_this_round - enemy_dmg_this_round)

    tension = 1.0 - (min_party_hp / pc_total_hp) if pc_total_hp > 0 else 0.0

    # Swing count: how many times did the "who's winning" sign flip?
    swing_count = 0
    prev_sign = 0
    for r in sorted(side_advantage_by_round):
        adv = side_advantage_by_round[r]
        sign = 1 if adv > 0 else (-1 if adv < 0 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            swing_count += 1
        if sign != 0:
            prev_sign = sign

    from engine.core.combat_metrics import build_contribution_ledger
    ledger = build_contribution_ledger(state)

    return {
        "outcome": outcome,
        "rounds": state.round,
        "pc_deaths": pc_deaths,
        "d_iff": ledger["d_iff"],
        "difficulty_band": ledger["difficulty_band"],
        "tension": tension,
        "rounds_critical": rounds_critical,
        "swing_count": swing_count,
    }


def aggregate_runs(runs: list[dict]) -> dict:
    """Aggregate per-run quality metrics into encounter-level stats."""
    n = len(runs)
    if n == 0:
        return {"n": 0, "quality_grade": "F"}

    wins = sum(1 for r in runs if r["outcome"] == "WIN")
    losses = sum(1 for r in runs if r["outcome"] == "LOSS")
    caps = sum(1 for r in runs if r["outcome"] == "CAP")
    deaths = sum(1 for r in runs if r["pc_deaths"] > 0)
    all_rounds = [r["rounds"] for r in runs]
    all_tension = [r["tension"] for r in runs]
    all_swings = [r["swing_count"] for r in runs]
    all_diff = [r["d_iff"] for r in runs]

    win_rate = wins / n
    tpk_rate = losses / n
    death_rate = deaths / n
    median_rounds = sorted(all_rounds)[n // 2]
    mean_tension = sum(all_tension) / n
    mean_swings = sum(all_swings) / n
    mean_diff = sum(all_diff) / n

    grade = _quality_grade(win_rate, tpk_rate, death_rate,
                           median_rounds, mean_tension)

    return {
        "n": n,
        "win_rate": win_rate,
        "tpk_rate": tpk_rate,
        "death_rate": death_rate,
        "cap_rate": caps / n,
        "median_rounds": median_rounds,
        "mean_rounds": sum(all_rounds) / n,
        "mean_tension": mean_tension,
        "mean_swings": mean_swings,
        "mean_d_iff": mean_diff,
        "quality_grade": grade,
    }


def _quality_grade(win_rate: float, tpk_rate: float, death_rate: float,
                   median_rounds: int, mean_tension: float) -> str:
    """A-F grade summarizing encounter quality."""
    # F: broken
    if win_rate < 0.20 or win_rate > 0.95 or tpk_rate > 0.25:
        return "F"
    if median_rounds > 20:
        return "F"
    # D: problematic
    if win_rate < 0.40 or win_rate > 0.90:
        return "D"
    if tpk_rate > 0.15 or death_rate < 0.05 or death_rate > 0.60:
        return "D"
    # C: acceptable
    if win_rate < 0.55 or win_rate > 0.85:
        return "C"
    if tpk_rate > 0.10 or death_rate < 0.10 or death_rate > 0.50:
        return "C"
    # A: sweet spot
    if (0.65 <= win_rate <= 0.80
            and 0.15 <= death_rate <= 0.40
            and tpk_rate < 0.05
            and mean_tension >= 0.3
            and median_rounds <= 15):
        return "A"
    # B: good
    return "B"


def format_quality(agg: dict) -> str:
    """Human-readable summary of aggregate encounter quality."""
    if agg["n"] == 0:
        return "No runs to evaluate."
    lines = [
        f"Encounter Quality Report  ({agg['n']} runs)",
        f"  Grade:         {agg['quality_grade']}",
        f"  Win rate:      {agg['win_rate']:.0%}",
        f"  TPK rate:      {agg['tpk_rate']:.0%}",
        f"  Death rate:    {agg['death_rate']:.0%}  (runs with >= 1 PC death)",
        f"  Cap rate:      {agg['cap_rate']:.0%}  (hit round limit)",
        f"  Rounds:        median {agg['median_rounds']}  "
        f"mean {agg['mean_rounds']:.1f}",
        f"  Tension:       {agg['mean_tension']:.2f}  "
        f"(0 = trivial, 1 = near-TPK)",
        f"  Swings/fight:  {agg['mean_swings']:.1f}  (momentum reversals)",
        f"  d_iff:         {agg['mean_d_iff']:.2f}",
    ]
    return "\n".join(lines)
