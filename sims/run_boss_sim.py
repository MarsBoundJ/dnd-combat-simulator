"""Boss sim — run 3 (positioning stack live) — Tier-3 party vs Adult Red
Dragon. Same party/dragon as the first sim (stats imported from
run_first_sim for comparability), but with TWO changes:

  1. Spread STARTING POSITIONS (approach formation ~45-55 ft, fanned out)
     so the dragon's near-certain round-1 breath (it has Initiative +12,
     so it almost always acts first — RAW) can't catch the whole party in
     one cone. (positioning-model.md §5 starting geometry.)
  2. The full positioning stack is now live: max_aoe_coverage (the dragon
     orients its breath to the eHP-max placement) + PC de-cluster
     (best_position wired into _move_to_engage).

Initiative is rolled normally (PCs get their DEX bonus). Writes
report_run3_positioning.md + events_run3.json; also runs a few extra seeds
and appends an outcome-distribution table. Runs 1-2 artifacts are left
untouched.
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import engine.primitives as primitives_module
from engine.cli import _build_actor
from engine.core.runner import EncounterRunner
from engine.core.state import Encounter
from engine.loader import load_content
from sims.run_first_sim import _party_specs, _dragon_spec, _derive_stats

REPO = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
HEADLINE_SEED = 42
EXTRA_SEEDS = [1, 7, 13, 99]

# Spread approach formation (grid squares; dragon at (0,0)). Fanned across a
# wide arc ~45-55 ft out so a single 60-ft cone can't catch all four.
#
# NOTE (Monte Carlo finding, 2026-06-03): this layout (33% win over 60 seeds)
# BEATS a "widen the squishiest Wizard to a far flank" variant (13% win) —
# widening the Wizard eliminated its round-2 death but pushed the CLERIC into
# the cone, and losing the healer's sustain cost more wins than the Wizard's
# nova. Lesson: protect the highest-VALUE PC (the healer), not the
# lowest-HP one. See sims/FINDINGS.md.
_SPREAD = {
    "Fighter_Champion": [10, 0],
    "Cleric": [9, -8],
    "Wizard_Evoker": [11, 5],
    "Bard_Lore": [9, 8],
}


def _spread_specs():
    specs = copy.deepcopy(_party_specs())
    for s in specs:
        if s["instance_id"] in _SPREAD:
            s["position"] = _SPREAD[s["instance_id"]]
    return specs


def build_and_run(seed: int):
    registry = load_content(REPO / "schema" / "content", validate=True,
                             schema_root=REPO / "schema" / "definitions")
    specs = _spread_specs() + [_dragon_spec()]
    actors = [_build_actor(s, registry) for s in specs]
    enc = Encounter(id="boss_sim_run3", actors=actors)
    primitives_module.set_rng(random.Random(seed))
    runner = EncounterRunner.new(enc, seed=seed, content_registry=registry)
    primitives_module.set_rng(runner.rng)
    state = runner.run(seed=seed)
    return state, actors


def _first_actor_id(events):
    for e in events:
        if e.get("event") == "turn_start":
            return e.get("actor")
    return "?"


def _breath_hits_round1(events) -> int:
    """How many distinct PCs took fire damage before round 2 (the alpha
    breath, if the dragon went first)."""
    hit, round_no = set(), 1
    for e in events:
        if e.get("event") == "turn_start":
            round_no = e.get("round", round_no)
        if round_no > 1:
            break
        if e.get("event") == "damage_dealt" and e.get("type") == "fire":
            hit.add(e.get("target"))
    return len(hit)


def _summary(state, actors, events):
    stats = _derive_stats(events, actors)
    pcs = [a for a in actors if a.side == "pc"]
    party_dmg = sum(stats[a.id]["dmg_dealt"] for a in pcs)
    pcs_alive = sum(1 for a in pcs if a.is_alive() and not getattr(a, "is_fled", False))
    dragon = next(a for a in actors if a.side == "enemy")
    return {
        "rounds": state.round,
        "reason": state.termination_reason,
        "first": _first_actor_id(events),
        "breath1_hits": _breath_hits_round1(events),
        "party_dmg": party_dmg,
        "dragon_hp": f"{dragon.hp_current}/{dragon.hp_max}",
        "pcs_standing": pcs_alive,
    }


def _write_report(state, actors, events, snapshot, seed):
    s = _summary(state, actors, events)
    L = []
    L.append("# Boss Sim — Run 3 (positioning stack live) — Tier-3 vs Adult Red Dragon\n")
    L.append(f"*Seed {seed}; reproducible via `sims/run_boss_sim.py`. 2026-06-03. "
             f"Spread starting formation + full positioning stack "
             f"(max_aoe_coverage + PC de-cluster). Compare runs 1-2 "
             f"(`report.md`, `report_run2_post_casters.md`).*\n")
    L.append(f"**Outcome:** {s['reason']} in {s['rounds']} rounds. "
             f"First to act: **{s['first']}**. "
             f"PCs caught by the round-1 breath: **{s['breath1_hits']}** "
             f"(runs 1-2 caught all 4). Party damage dealt: **{s['party_dmg']}**.\n")
    L.append("## Final state")
    L.append("| Combatant | Side | HP | Status |")
    L.append("|---|---|---|---|")
    for sn in snapshot:
        tag = "dead" if sn["is_dead"] else ("fled" if sn["is_fled"] else "alive")
        L.append(f"| {sn['id']} | {sn['side']} | {sn['hp_current']}/{sn['hp_max']} | {tag} |")
    L.append("")
    L.append("## Derived stats")
    L.append("| Combatant | Dmg dealt | Attacks | Hits | Healing | Dmg taken |")
    L.append("|---|--:|--:|--:|--:|--:|")
    stats = _derive_stats(events, actors)
    for a in actors:
        st = stats[a.id]
        L.append(f"| {a.id} | {st['dmg_dealt']} | {st['attacks']} | {st['hits']} | "
                 f"{st['healing']} | {st['dmg_taken']} |")
    L.append("")
    L.append("## Round-by-round")
    cur = None
    for e in events:
        et = e.get("event")
        if et == "turn_start":
            if e.get("round") != cur:
                cur = e.get("round")
                L.append(f"\n### Round {cur}")
            L.append(f"\n**{e.get('actor')}'s turn**")
        elif et == "moved":
            extra = f" [{e.get('reason')}]" if e.get("reason") else ""
            L.append(f"- moved {e.get('actor')} {e.get('from')}->{e.get('to')}{extra}")
        elif et == "forced_save":
            L.append(f"- save: {e.get('target')} {e.get('ability')} DC {e.get('dc')} "
                     f"-> {e.get('outcome')} (rolled {e.get('total')})")
        elif et == "damage_dealt":
            L.append(f"- {e.get('actor')} -> {e.get('target')}: {e.get('amount')} "
                     f"{e.get('type')} ({e.get('target_hp_remaining')} HP left)")
        elif et == "attack_roll" and e.get("actor"):
            L.append(f"- attack: {e.get('actor')} -> {e.get('target')} "
                     f"{e.get('result')} ({e.get('reason') or e.get('total')})")
        elif et == "healed":
            L.append(f"- heal: {e.get('target')} +{e.get('amount')} (-> {e.get('hp_current')})")
        elif et == "fled":
            L.append(f"- {e.get('actor')} FLED ({e.get('triggers')})")
    (OUT / "report_run3_positioning.md").write_text("\n".join(L), encoding="utf-8")


def main():
    # Headline run (seed 42)
    state, actors = build_and_run(HEADLINE_SEED)
    events = state.event_log
    snapshot = [{"id": a.id, "side": a.side, "hp_current": a.hp_current,
                 "hp_max": a.hp_max, "is_dead": a.is_dead,
                 "is_fled": getattr(a, "is_fled", False)} for a in actors]
    (OUT / "events_run3.json").write_text(json.dumps(
        {"seed": HEADLINE_SEED, "summary": _summary(state, actors, events),
         "rounds": state.round, "final": snapshot, "events": events},
        indent=2), encoding="utf-8")
    _write_report(state, actors, events, snapshot, HEADLINE_SEED)

    # Addendum: extra seeds, outcome distribution
    rows = [("seed", "first", "rounds", "breath1_hits", "party_dmg",
             "dragon_hp", "pcs_standing")]
    for sd in [HEADLINE_SEED] + EXTRA_SEEDS:
        st2, ac2 = build_and_run(sd)
        s = _summary(st2, ac2, st2.event_log)
        rows.append((sd, s["first"], s["rounds"], s["breath1_hits"],
                     s["party_dmg"], s["dragon_hp"], s["pcs_standing"]))

    print("=== RUN 3 — outcome distribution (spread starts + positioning) ===")
    for r in rows:
        print("  " + " | ".join(f"{c}" for c in r))


if __name__ == "__main__":
    main()
