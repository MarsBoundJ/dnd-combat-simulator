"""WS-F1 — per-actor / per-encounter metric buckets from a finished run's
event stream.

Library-only: `compute_metrics(events, *, roster=None)` walks a finished
encounter's event log (the list of `state.event_log` dict records) and returns
the aggregates the archive (WS-F3) will persist. No engine state is required —
the function consumes the *serialized* event stream so it can run against an
archived run, not just a live `CombatState`.

Buckets (the WS-F1 set):
  - damage dealt / taken (per actor + per side)
  - attacks / hits / crits / auto-misses → hit %
  - spell slots spent, broken down by slot level
  - healing done / received
  - control applications + control-rounds-denied (action-denial, fraction-
    weighted per condition)
  - movement: feet moved + move count (see the exposure note in the PR /
    docstring below — finer time-in-threat "exposure" isn't in the stream)
  - outcome taxonomy: victory / tpk / fled_enemy_alive / stalemate /
    mutual_destruction, with closeness = surviving-side HP fraction

Side-aware metrics (cross-side damage filtering, per-side totals, the outcome
taxonomy, closeness) require a `roster` mapping actor_id -> {side, hp_max,
name}. Without it the per-actor counters are still computed (damage is gross —
no cross-side filter) but the side split / outcome degrade to "unknown".

Read-only reuse of `engine.core.combat_metrics` helpers (hit/crit result sets,
control fractions, difficulty bands) — this module never mutates that one.
"""
from __future__ import annotations

from typing import Any

from engine.core.combat_metrics import (
    _HIT_RESULTS as HIT_RESULTS,
    _CRIT_RESULTS as CRIT_RESULTS,
    _control_fraction,
    classify_diff,
)

# Outcome result codes.
VICTORY = "victory"
TPK = "tpk"
FLED_ENEMY_ALIVE = "fled_enemy_alive"
STALEMATE = "stalemate"
MUTUAL_DESTRUCTION = "mutual_destruction"
UNKNOWN = "unknown"

PARTY_SIDE = "pc"


def _blank_actor(side: str | None, name: str | None) -> dict:
    return {
        "side": side,
        "name": name,
        "damage_dealt": 0.0,
        "damage_taken": 0.0,
        "attacks": 0,          # rolled attacks (had a d20)
        "hits": 0,
        "crits": 0,
        "auto_misses": 0,      # attempts that never rolled (out of range / cover)
        "hit_pct": 0.0,
        "spell_slots_spent": {},   # {level:int -> count}
        "spell_slots_total": 0,
        "healing_done": 0.0,
        "healing_received": 0.0,
        "control_applications": 0,     # control conditions imposed on foes
        "control_rounds_denied": 0.0,  # fraction-weighted action denial
        "feet_moved": 0.0,
        "moves": 0,
        "final_hp": None,      # reconstructed from the stream (None = untouched)
        "hp_max": None,
        "alive": None,
        "downed": None,
        "fled": False,
    }


def compute_metrics(events: list[dict], *, roster: dict | None = None) -> dict:
    """Aggregate a finished run's event stream into metric buckets.

    Args:
      events: the run's event log — a list of dict records (state.event_log).
      roster: optional {actor_id: {"side": str, "hp_max": int, "name": str}}.
        Enables cross-side filtering, per-side totals, and the outcome taxonomy.

    Returns a dict with `rounds`, `per_actor`, `per_side`, and `outcome`.
    """
    roster = roster or {}

    def side_of(aid: str | None) -> str | None:
        if aid is None:
            return None
        info = roster.get(aid)
        return info.get("side") if info else None

    def name_of(aid: str | None) -> str | None:
        info = roster.get(aid) if aid is not None else None
        return info.get("name") if info else None

    per_actor: dict[str, dict] = {}

    def row(aid: str) -> dict:
        if aid not in per_actor:
            per_actor[aid] = _blank_actor(side_of(aid), name_of(aid))
        return per_actor[aid]

    # Seed rows for every rostered actor so non-participants still appear.
    for aid, info in roster.items():
        r = row(aid)
        r["hp_max"] = info.get("hp_max")

    final_hp: dict[str, float] = {}   # last authoritative HP seen per actor
    fled: set[str] = set()
    max_round = 0
    cur_actor: str | None = None

    for e in events:
        ev = e.get("event")

        if ev == "turn_start":
            cur_actor = e.get("actor")
            max_round = max(max_round, int(e.get("round", 0) or 0))

        elif ev == "attack_roll":
            aid = e.get("actor")
            if aid is None:
                continue
            r = row(aid)
            if "d20" not in e:
                # Auto-miss: out_of_range / total_cover / no line of effect.
                r["auto_misses"] += 1
                continue
            r["attacks"] += 1
            if e.get("result") in HIT_RESULTS:
                r["hits"] += 1
            if e.get("result") in CRIT_RESULTS:
                r["crits"] += 1

        elif ev == "damage_dealt":
            aid = e.get("actor")
            tid = e.get("target")
            amt = float(e.get("amount", 0) or 0)
            if amt > 0 and tid is not None:
                # Damage taken is always attributed to the target.
                row(tid)["damage_taken"] += amt
                # Damage dealt: cross-side only when sides are known (mirrors
                # combat_metrics); gross when no roster.
                if aid is not None:
                    sa, st = side_of(aid), side_of(tid)
                    if not roster or sa != st:
                        row(aid)["damage_dealt"] += amt
            if tid is not None and "target_hp_remaining" in e:
                final_hp[tid] = float(e["target_hp_remaining"])

        elif ev == "healed":
            amt = float(e.get("amount", 0) or 0)
            tid = e.get("target")
            if tid is not None:
                if amt > 0:
                    row(tid)["healing_received"] += amt
                    # `healed` carries only the target — attribute the credit to
                    # the turn's actor (the healer), cross-side-guarded.
                    if cur_actor is not None and (
                            not roster or side_of(cur_actor) == side_of(tid)):
                        row(cur_actor)["healing_done"] += amt
                if "hp_current" in e:
                    final_hp[tid] = float(e["hp_current"])

        elif ev == "revived":
            aid = e.get("actor")
            if aid is not None and "hp" in e:
                final_hp[aid] = float(e["hp"])

        elif ev == "spell_slot_consumed":
            aid = e.get("actor")
            lvl = e.get("slot_level")
            if aid is not None and lvl is not None:
                r = row(aid)
                r["spell_slots_spent"][int(lvl)] = (
                    r["spell_slots_spent"].get(int(lvl), 0) + 1)
                r["spell_slots_total"] += 1

        elif ev == "condition_applied":
            src = e.get("source")
            tid = e.get("target")
            if src is None or tid is None:
                continue
            frac = _control_fraction(e.get("condition", "") or "")
            if frac <= 0:
                continue
            # Only credit control imposed on the opposing side (when known).
            if roster and side_of(src) == side_of(tid):
                continue
            r = row(src)
            r["control_applications"] += 1
            r["control_rounds_denied"] += frac

        elif ev == "moved":
            aid = e.get("actor")
            if aid is not None:
                r = row(aid)
                r["feet_moved"] += float(e.get("ft", 0) or 0)
                r["moves"] += 1

        elif ev == "fled":
            aid = e.get("actor")
            if aid is not None:
                fled.add(aid)
                row(aid)["fled"] = True

        elif ev == "creature_dropped":
            cid = e.get("creature")
            if cid is not None:
                # A drop to 0 HP — authoritative unless a later heal/revive
                # event supersedes it (events are processed in order).
                final_hp[cid] = 0.0

    rounds = max(1, max_round)

    # ── finalize per-actor: hit%, liveness, final HP ────────────────────────
    for aid, r in per_actor.items():
        r["hit_pct"] = round(100.0 * r["hits"] / r["attacks"], 1) if r["attacks"] else 0.0
        fh = final_hp.get(aid)
        if fh is None:
            # Never took damage / healed — assume full HP if roster gives a max.
            fh = float(r["hp_max"]) if r["hp_max"] is not None else None
        r["final_hp"] = fh
        if fh is None:
            r["alive"] = None
            r["downed"] = None
        else:
            r["downed"] = fh <= 0
            r["alive"] = fh > 0
        r["fled"] = aid in fled

    per_side = _aggregate_sides(per_actor, roster) if roster else {}
    outcome = _classify_outcome(per_actor, per_side, roster, rounds)

    return {
        "rounds": rounds,
        "per_actor": per_actor,
        "per_side": per_side,
        "outcome": outcome,
    }


_SIDE_SUM_KEYS = (
    "damage_dealt", "damage_taken", "attacks", "hits", "crits", "auto_misses",
    "healing_done", "healing_received", "control_applications",
    "control_rounds_denied", "feet_moved", "moves", "spell_slots_total",
)


def _aggregate_sides(per_actor: dict, roster: dict) -> dict:
    sides: dict[str, dict] = {}
    # Every roster side appears (even if it never acted).
    for info in roster.values():
        sides.setdefault(info.get("side"), _blank_side())
    for aid, r in per_actor.items():
        s = r["side"]
        if s is None:
            continue
        bucket = sides.setdefault(s, _blank_side())
        for k in _SIDE_SUM_KEYS:
            bucket[k] += r[k]
        bucket["starting_count"] += 1
        if r["alive"]:
            bucket["alive_count"] += 1
        hpmax = r["hp_max"] or 0
        bucket["max_hp"] += hpmax
        fh = r["final_hp"]
        bucket["final_hp"] += (fh if fh is not None else hpmax)
    for s, bucket in sides.items():
        bucket["hit_pct"] = (round(100.0 * bucket["hits"] / bucket["attacks"], 1)
                             if bucket["attacks"] else 0.0)
        bucket["hp_fraction"] = (round(bucket["final_hp"] / bucket["max_hp"], 4)
                                 if bucket["max_hp"] else 0.0)
    return sides


def _blank_side() -> dict:
    b = {k: 0.0 for k in _SIDE_SUM_KEYS}
    b.update({"starting_count": 0, "alive_count": 0,
              "final_hp": 0.0, "max_hp": 0.0})
    return b


def _classify_outcome(per_actor: dict, per_side: dict, roster: dict,
                      rounds: int) -> dict:
    """Outcome taxonomy + closeness from reconstructed liveness.

    PC-centric when a `pc` side is present (victory/tpk/fled_enemy_alive/
    stalemate/mutual_destruction); otherwise a generic side-winner read.
    """
    base = {"result": UNKNOWN, "winning_side": None, "rounds": rounds,
            "closeness": {"surviving_side": None, "hp_fraction": None,
                          "per_side_hp_fraction": {}}}
    if not roster:
        return base

    sides = sorted({r["side"] for r in per_actor.values() if r["side"]}
                   | set(per_side.keys()))
    # alive (on the field) = has an alive, non-fled member.
    def alive_on_field(side: str) -> bool:
        return any(r["alive"] and not r["fled"]
                   for r in per_actor.values() if r["side"] == side)

    def fled_any(side: str) -> bool:
        return any(r["fled"] for r in per_actor.values() if r["side"] == side)

    per_side_frac = {s: per_side[s]["hp_fraction"] for s in per_side}
    base["closeness"]["per_side_hp_fraction"] = per_side_frac

    def closeness_for(side: str | None) -> dict:
        return {"surviving_side": side,
                "hp_fraction": per_side_frac.get(side) if side else None,
                "per_side_hp_fraction": per_side_frac}

    if PARTY_SIDE in sides:
        enemy_sides = [s for s in sides if s != PARTY_SIDE]
        pc_up = alive_on_field(PARTY_SIDE)
        pc_fled = fled_any(PARTY_SIDE)
        enemy_up = any(alive_on_field(s) for s in enemy_sides)

        if not pc_up and not enemy_up:
            return {**base, "result": MUTUAL_DESTRUCTION, "winning_side": None,
                    "closeness": closeness_for(None)}
        if pc_up and not enemy_up:
            return {**base, "result": VICTORY, "winning_side": PARTY_SIDE,
                    "closeness": closeness_for(PARTY_SIDE)}
        if not pc_up and enemy_up:
            # Party off the field while enemies live: fled if anyone retreated,
            # otherwise a true wipe (TPK).
            win = enemy_sides[0] if len(enemy_sides) == 1 else "enemy"
            result = FLED_ENEMY_ALIVE if pc_fled else TPK
            return {**base, "result": result, "winning_side": win,
                    "closeness": closeness_for(win)}
        # both up → unresolved within the round cap
        return {**base, "result": STALEMATE, "winning_side": None,
                "closeness": closeness_for(None)}

    # No party side — generic winner read.
    up = [s for s in sides if alive_on_field(s)]
    if len(up) == 1:
        return {**base, "result": VICTORY, "winning_side": up[0],
                "closeness": closeness_for(up[0])}
    if not up:
        return {**base, "result": MUTUAL_DESTRUCTION,
                "closeness": closeness_for(None)}
    return {**base, "result": STALEMATE, "closeness": closeness_for(None)}


def roster_from_actors(actors) -> dict:
    """Build a roster mapping from live `Actor` objects (id -> {side, hp_max,
    name}). Convenience for callers that still have the encounter in hand
    (tests, the integration lane). Pure read of public Actor attributes."""
    return {
        a.id: {"side": getattr(a, "side", None),
               "hp_max": getattr(a, "hp_max", None),
               "name": getattr(a, "name", a.id)}
        for a in actors
    }


def difficulty_band(metrics: dict) -> str | None:
    """Empirical encounter-difficulty band (Dunn's d_iff) for the party side,
    reusing combat_metrics.classify_diff. None if the party HP isn't known.
    d_iff = PC damage taken / PC total max HP."""
    pc = metrics.get("per_side", {}).get(PARTY_SIDE)
    if not pc or not pc.get("max_hp"):
        return None
    return classify_diff(pc["damage_taken"] / pc["max_hp"])
