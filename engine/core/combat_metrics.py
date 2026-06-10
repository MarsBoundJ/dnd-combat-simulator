"""Per-round combat contribution ledger.

Post-processes a finished encounter's `state.event_log` into per-actor and
per-round contribution numbers — so we can SEE the combat effect of every
actor's actions (PCs and monsters) and answer "why did this fight take 40
rounds?" The same numbers feed PC-build / monster power-level calibration and
the Trusight per-sim metric buckets.

Captured per actor (realized from the log, not projected):
  - damage_dealt  : HP removed from the OPPOSING side (offensive eHP). Includes
                    reaction / OA / bonus-action damage (every `damage_dealt`
                    carries its dealer).
  - damage_taken  : HP lost to the opposing side.
  - attacks / hits / crits : from `attack_roll` results (whiff rate — catches
                    "everyone's missing" and any to-hit/AC bug).
  - heal_ehp      : HP restored to allies (attributed to the turn's actor,
                    since `healed` carries only the target).
  - control_ehp   : action-denial eHP — when an actor lands a control condition
                    on an enemy, credit the denied enemy's DPR × denial fraction
                    (1.0 for hard control, partial fractions for restrained/
                    prone/etc.). v1 credits at APPLICATION (~one round denied);
                    multi-round denial accounting is a documented follow-up.

The headline diagnostic is `per_round`: total eHP the PCs deliver to enemies
each round (damage + control) — divide the enemies' starting HP by it and you
get the floor on fight length. A 40-round fight = that per-round delivery is a
fraction of what the party should be putting out.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState
from engine.ai.defensive_ehp import (
    estimate_dpr, HARD_CONTROL_CONDITIONS, PARTIAL_CONTROL_CONDITIONS,
)

# attack_roll `result` values that count as a landed hit.
_HIT_RESULTS = {"hit", "crit", "critical"}
_CRIT_RESULTS = {"crit", "critical"}


# Tom Dunn's empirical encounter-difficulty bands ("Variability: Encounter
# Difficulty", The Finished Book — verified Jun 2026). d_iff = damage the PCs
# TOOK in the encounter / party total max HP. Dunn ESTIMATES d_iff via a
# 2-combatant rounds-ratio model; we measure the EMPIRICAL value from the
# realized log (actual gross damage taken). His win-probability anchors at our
# party tier: Hard(0.45) ~89%, Deadly(0.70) ~69%, d_iff=1.0 ~50%.
#
# Caveats carried with the metric:
#   - GROSS damage taken (healing lets PCs survive d_iff > 1; the metric is
#     incoming pressure, not net HP). Matches Dunn's numerator definition.
#   - Single-run d_iff is noisy (Tier-3 CV ~0.4); average across seeds for a
#     stable difficulty read.
#   - Dunn's bands were fit to 2014 monsters; 2024 monsters hit ~harder (esp.
#     legendary CR10+ ~+40% DPR / CR13+ ~+15% HP), so a 2024 encounter's d_iff
#     runs hotter than its XP-budget label implies.
DIFFICULTY_BANDS = (
    ("Trivial", 0.0, 0.15),
    ("Easy", 0.15, 0.30),
    ("Medium", 0.30, 0.45),
    ("Hard", 0.45, 0.70),
    ("Deadly", 0.70, 1.00),
    ("TPK", 1.00, float("inf")),
)


def classify_diff(d_iff: float) -> str:
    """Map an empirical d_iff to Dunn's difficulty band name."""
    for name, lo, hi in DIFFICULTY_BANDS:
        if lo <= d_iff < hi:
            return name
    return "TPK"


def _control_fraction(condition_id: str) -> float:
    """Action-denial fraction for a condition: 1.0 for full denial (stunned/
    paralyzed/incapacitated/...), the partial fraction for restrained/prone/
    etc., 0.0 if the condition isn't a control effect."""
    if condition_id in HARD_CONTROL_CONDITIONS:
        return 1.0
    return float(PARTIAL_CONTROL_CONDITIONS.get(condition_id, 0.0))


def _blank(side: str) -> dict:
    return {"side": side, "damage_dealt": 0.0, "damage_taken": 0.0,
            "attacks": 0, "hits": 0, "crits": 0,
            # auto_misses = attack attempts that never rolled a d20 (out of
            # range / total cover). A high count means the actor is FLAILING
            # at targets it can't reach — a reach/positioning failure, NOT bad
            # luck. Kept separate so hit% reflects only real rolls.
            "auto_misses": 0,
            "heal_ehp": 0.0, "control_ehp": 0.0,
            # Shapley attribution (engine/core/attribution.py):
            #   enablement_ehp    = damage credited to THIS actor for boosting
            #                       an ALLY's rolls (Web's advantage, Bless).
            #   enabled_by_others = the slice of this actor's OWN dealt damage
            #                       that allies' effects created.
            # attributed_offense (derived below) = damage_dealt −
            # enabled_by_others + enablement_ehp; sums across a side to the
            # side's realized damage (the closed-ledger property).
            "enablement_ehp": 0.0, "enabled_by_others": 0.0}


def build_contribution_ledger(state: CombatState) -> dict:
    """Walk `state.event_log` into a per-actor + per-round contribution ledger.
    Pure read — does not mutate state. Returns:

        {
          "rounds": int,
          "per_actor": {id: {side, damage_dealt, damage_taken, attacks, hits,
                             crits, heal_ehp, control_ehp, dpr}},
          "per_round": {round: {pc_damage, pc_control, enemy_damage}},
          "sides": {"pc": {...totals}, "enemy": {...totals}},
        }
    """
    actors = {a.id: a for a in state.encounter.actors}

    def side_of(aid: str) -> str:
        a = actors.get(aid)
        return getattr(a, "side", "?") if a else "?"

    per_actor: dict[str, dict] = {}

    def row(aid: str) -> dict:
        if aid not in per_actor:
            per_actor[aid] = _blank(side_of(aid))
        return per_actor[aid]

    per_round: dict[int, dict] = {}

    def rnd(r: int) -> dict:
        if r not in per_round:
            per_round[r] = {"pc_damage": 0.0, "pc_control": 0.0,
                            "enemy_damage": 0.0}
        return per_round[r]

    cur_round = 0
    cur_actor = None
    max_round = 0
    for e in state.event_log:
        ev = e.get("event")
        if ev == "turn_start":
            cur_round = int(e.get("round", cur_round))
            cur_actor = e.get("actor")
            max_round = max(max_round, cur_round)
            continue
        if ev == "attack_roll":
            aid = e.get("actor")
            if aid is None:
                continue
            r = row(aid)
            if "d20" not in e:
                # Auto-miss (out_of_range / total_cover) — never rolled. Track
                # separately so it doesn't deflate hit%; it's a reach signal.
                r["auto_misses"] += 1
                continue
            r["attacks"] += 1
            if e.get("result") in _HIT_RESULTS:
                r["hits"] += 1
            if e.get("result") in _CRIT_RESULTS:
                r["crits"] += 1
        elif ev == "damage_dealt":
            aid = e.get("actor")
            tid = e.get("target")
            amt = float(e.get("amount", 0))
            if aid is None or tid is None or amt <= 0:
                continue
            # Only count cross-side damage (ignore friendly fire / self for the
            # offensive/defensive split; it's rare and would muddy DPR).
            if side_of(aid) != side_of(tid):
                row(aid)["damage_dealt"] += amt
                row(tid)["damage_taken"] += amt
                bucket = rnd(cur_round)
                if side_of(aid) == "pc":
                    bucket["pc_damage"] += amt
                else:
                    bucket["enemy_damage"] += amt
                # Shapley attribution: route each enabler share to its source.
                # Only positive shares from a SAME-SIDE, non-self creature
                # move (the Cleric's Bless on the Fighter's hit). Shares
                # sourced by the attacker itself (Reckless) or by the enemy
                # side (target's own exposure, Shield's negative surplus)
                # stay with the executor — defensive attribution is a
                # documented v2 lane.
                attr = e.get("attribution")
                if attr:
                    for share in attr.get("shares") or []:
                        sid = share.get("source_id")
                        s_amt = float(share.get("amount", 0))
                        if (not sid or sid == aid or s_amt <= 0
                                or side_of(sid) != side_of(aid)):
                            continue
                        row(sid)["enablement_ehp"] += s_amt
                        row(aid)["enabled_by_others"] += s_amt
        elif ev == "healed":
            # `healed` carries only the target; attribute to the turn's actor.
            amt = float(e.get("amount", 0))
            tid = e.get("target")
            if amt <= 0 or cur_actor is None or tid is None:
                continue
            if side_of(cur_actor) == side_of(tid):
                row(cur_actor)["heal_ehp"] += amt
        elif ev == "condition_applied":
            src = e.get("source")
            tid = e.get("target")
            if src is None or tid is None:
                continue
            frac = _control_fraction(e.get("condition", ""))
            if frac <= 0 or side_of(src) == side_of(tid):
                continue   # not control, or applied to own side
            tgt = actors.get(tid)
            denied = estimate_dpr(tgt) if tgt else 0.0
            credit = denied * frac
            row(src)["control_ehp"] += credit
            if side_of(src) == "pc":
                rnd(cur_round)["pc_control"] += credit

    rounds = max(1, max_round)
    for aid, r in per_actor.items():
        r["dpr"] = round(r["damage_dealt"] / rounds, 1)
        # Cause-credited offense: own realized damage minus the slice allies
        # created, plus credit earned boosting allies. Per side this sums to
        # the side's realized damage_dealt (shares only move within a side).
        r["attributed_offense"] = (r["damage_dealt"] - r["enabled_by_others"]
                                   + r["enablement_ehp"])

    # Empirical encounter difficulty (Dunn's d_iff): gross damage the PC side
    # took / party total max HP, classified into his bands. The realized
    # measurement of the metric our XP-budget labels only estimate.
    pc_actors = [a for a in state.encounter.actors
                 if getattr(a, "side", None) == "pc"]
    pc_total_hp = sum(max(1, int(getattr(a, "hp_max", 0) or 0))
                      for a in pc_actors)
    pc_damage_taken = sum(r["damage_taken"] for r in per_actor.values()
                          if r["side"] == "pc")
    d_iff = (pc_damage_taken / pc_total_hp) if pc_total_hp else 0.0

    def side_totals(side: str) -> dict:
        rows = [r for r in per_actor.values() if r["side"] == side]
        return {
            "damage_dealt": sum(r["damage_dealt"] for r in rows),
            "control_ehp": sum(r["control_ehp"] for r in rows),
            "heal_ehp": sum(r["heal_ehp"] for r in rows),
            "attacks": sum(r["attacks"] for r in rows),
            "hits": sum(r["hits"] for r in rows),
        }

    return {
        "rounds": rounds,
        "per_actor": per_actor,
        "per_round": per_round,
        "sides": {"pc": side_totals("pc"), "enemy": side_totals("enemy")},
        "d_iff": d_iff,
        "difficulty_band": classify_diff(d_iff),
        "pc_total_hp": pc_total_hp,
        "pc_damage_taken": pc_damage_taken,
    }


def format_ledger(state: CombatState, ledger: dict | None = None) -> str:
    """A human-readable summary of the contribution ledger for sim output."""
    led = ledger if ledger is not None else build_contribution_ledger(state)
    rounds = led["rounds"]
    lines = [f"rounds: {rounds}   outcome: {state.termination_reason}", ""]
    lines.append(f"{'actor':20} {'side':6} {'dmg':>7} {'attr':>7} {'dpr':>6} "
                 f"{'atk':>4} {'hit%':>5} {'oor':>4} {'ctrl_eHP':>9} "
                 f"{'heal_eHP':>9} {'enab_eHP':>9}")
    for aid, r in sorted(led["per_actor"].items(),
                         key=lambda kv: (kv[1]["side"], -kv[1]["damage_dealt"])):
        hitpct = (100 * r["hits"] / r["attacks"]) if r["attacks"] else 0.0
        lines.append(
            f"{aid:20} {r['side']:6} {r['damage_dealt']:>7.0f} "
            f"{r['attributed_offense']:>7.0f} {r['dpr']:>6.1f} "
            f"{r['attacks']:>4} {hitpct:>4.0f}% {r['auto_misses']:>4} "
            f"{r['control_ehp']:>9.0f} {r['heal_ehp']:>9.0f} "
            f"{r['enablement_ehp']:>9.0f}")
    pc, en = led["sides"]["pc"], led["sides"]["enemy"]
    pc_per_round = (pc["damage_dealt"] + pc["control_ehp"]) / rounds
    en_per_round = en["damage_dealt"] / rounds
    lines += [
        "",
        f"PC offensive eHP/round (dmg+ctrl): {pc_per_round:6.1f}",
        f"Enemy damage/round:                {en_per_round:6.1f}",
        f"d_iff (dmg taken / party HP):      {led['d_iff']:6.2f} "
        f"({led['difficulty_band']})",
    ]
    return "\n".join(lines)
