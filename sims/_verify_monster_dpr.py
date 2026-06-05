"""Verify monster output on the enc-0 Low fight (fresh party).

Two checks (Phil, 2026-06-05):
  1. DPR sanity — each monster's MEASURED damage/active-round vs ~25% of its
     MAX round damage (avg hit ~50% of max dice x ~50% to-hit ~= 25% of max,
     across all its attacks). Measured should land roughly in that band; way
     over = over-firing / over-hitting bug, way under = something suppressing.
  2. Accounting — replay the event log applying damage + heals + temp-HP to
     each PC and confirm the reconstructed HP equals the actual final HP, so
     "PC HP reduction matches the damage monsters dealt" (no double-count or
     phantom loss).

Usage: python sims/_verify_monster_dpr.py [seed]   (default 1; dial 1, fresh)
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import engine.primitives as primitives_module
from engine.cli import _build_actor
from engine.core.runner import EncounterRunner
from engine.core.state import Encounter
from engine.loader import load_content
from sims.adventuring_day import _build_party, _build_monsters, DAY

REPO = Path(__file__).resolve().parent.parent


def _dice_max(expr) -> int:
    """Max of an 'NdM' (or 'NdM+K') dice expr. 0 if empty."""
    if not expr:
        return 0
    s = str(expr).split("+")[0].strip()
    if "d" not in s:
        try:
            return int(s)
        except ValueError:
            return 0
    n, m = s.split("d")
    return int(n or 1) * int(m)


def _action_max_damage(action: dict) -> int:
    """Max damage an action can deal in one use: every `damage` step (incl.
    forced_save on_fail / on_success riders) at max dice + modifier."""
    total = 0

    def _walk(steps):
        nonlocal total
        for step in steps or []:
            prim = step.get("primitive")
            params = step.get("params") or {}
            if prim == "damage":
                total += _dice_max(params.get("dice")) + int(params.get("modifier", 0))
            elif prim == "forced_save":
                _walk(params.get("on_fail"))
                _walk(params.get("on_success"))
    _walk(action.get("pipeline"))
    return total


def _max_round_damage(template: dict) -> int:
    """Max damage/round: the multiattack (count attacks cycling its
    sub_actions) if present, else the single highest-damage attack action."""
    actions = template.get("actions") or []
    by_id = {a.get("id"): a for a in actions}
    multi = next((a for a in actions if a.get("type") == "multiattack"), None)
    if multi:
        count = int(multi.get("count", 1))
        subs = multi.get("sub_actions") or []
        if subs:
            return sum(_action_max_damage(by_id.get(subs[i % len(subs)], {}))
                       for i in range(count))
    # No multiattack — highest single attack/save action.
    best = 0
    for a in actions:
        if a.get("type") in ("weapon_attack", "save_attack", "aoe_attack"):
            best = max(best, _action_max_damage(a))
    return best


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    reg = load_content(REPO / "schema" / "content", validate=True,
                        schema_root=REPO / "schema" / "definitions")
    party = _build_party(reg)
    pc_ids = {p.id for p in party}
    pc_start = {p.id: p.hp_current for p in party}
    name, counts = DAY[0]                       # enc 0 = the Low warm-up
    mons = _build_monsters(reg, counts)
    enemy_ids = {m.id for m in mons}
    enc = Encounter(id="low", actors=party + mons)
    r = EncounterRunner.new(enc, seed=seed, content_registry=reg)
    primitives_module.set_rng(r.rng)
    st = r.run(seed=seed, optimization_dials={"pc": 1, "enemy": 1})

    # --- DPR check ---
    dmg_to_pcs = defaultdict(float)
    active_rounds = defaultdict(set)
    cur = None
    rnd = 0
    for e in st.event_log:
        ev = e.get("event")
        if ev == "turn_start":
            cur = e.get("actor")
            rnd = e.get("round")
            if cur in enemy_ids:
                active_rounds[cur].add(rnd)
        elif ev == "damage_dealt" and e.get("actor") in enemy_ids \
                and e.get("target") in pc_ids:
            dmg_to_pcs[e["actor"]] += float(e.get("amount", 0))

    print(f"=== enc-0 Low ({name}) — seed {seed} ===")
    print(f"outcome: {st.termination_reason}  rounds: {st.round}\n")
    print(f"{'monster':16} {'maxRdDmg':>8} {'~25%':>6} {'measured DPR':>12} "
          f"{'ratio':>6}")
    by_template = {}
    for m in mons:
        if m.id not in by_template:
            by_template[m.id] = _max_round_damage(m.template)
    for m in mons:
        mx = by_template[m.id]
        exp = 0.25 * mx
        ar = max(1, len(active_rounds.get(m.id, {1})))
        measured = dmg_to_pcs.get(m.id, 0.0) / ar
        ratio = (measured / exp) if exp else 0.0
        print(f"{m.id:16} {mx:>8} {exp:>6.1f} {measured:>12.1f} {ratio:>5.2f}x")

    # --- Accounting check: replay damage/heal/temp-HP per PC ---
    print("\n=== HP accounting (reconstructed vs actual final) ===")
    recon = dict(pc_start)
    temp = defaultdict(int)
    cur = None
    for e in st.event_log:
        ev = e.get("event")
        if ev == "turn_start":
            cur = e.get("actor")
        elif ev == "temp_hp_granted" and e.get("target") in pc_ids:
            temp[e["target"]] = e.get("amount", temp[e["target"]])
        elif ev == "damage_dealt" and e.get("target") in pc_ids:
            amt = float(e.get("amount", 0))
            t = e["target"]
            absorbed = min(temp[t], amt)
            temp[t] -= absorbed
            recon[t] = max(0, recon[t] - (amt - absorbed))
        elif ev == "healed" and e.get("target") in pc_ids:
            recon[e["target"]] = e.get("hp_current", recon[e["target"]])
    ok = True
    for p in party:
        actual = max(0, p.hp_current)
        rc = recon[p.id]
        flag = "" if abs(rc - actual) <= 1 else "  <-- MISMATCH"
        if flag:
            ok = False
        print(f"  {p.id:18} reconstructed={rc:>4}  actual={actual:>4}{flag}")
    print("\nAccounting:", "OK — HP reduction matches damage dealt" if ok
          else "MISMATCH — damage/HP do not reconcile")


if __name__ == "__main__":
    main()
