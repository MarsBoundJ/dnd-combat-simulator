"""First end-to-end sim, stored for posterity (June 2 2026).

A Tier-3 (level 13) party vs the Adult Red Dragon (CR 17). Reproducible
(fixed seed). Emits, into this directory:
  - report.md   : round-by-round narrative + per-combatant derived stats
  - events.json : the raw event_log + final state snapshot

This is both a keepsake and the project's FIRST "is a real fight
plausible?" reality check — every prior test is unit/mechanic-level.
"""
from __future__ import annotations

import json
from pathlib import Path

import engine.primitives as primitives_module
from engine.cli import _build_actor
from engine.core.runner import EncounterRunner
from engine.core.state import Encounter
from engine.loader import load_content

REPO = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
SEED = 42


def _weapon(wid, name, ability, dice, dtype, reach=5):
    return {"id": wid, "name": name, "attack_ability": ability,
            "damage_dice": dice, "damage_type": dtype, "reach_ft": reach}


def _party_specs():
    """A classic Tier-3 four-person party at level 13 (subclasses used
    where one is built; Cleric runs its core, subclass-less)."""
    return [
        {"instance_id": "Fighter_Champion", "side": "pc", "position": [3, 0],
         "pc": {"class": "c_fighter", "level": 13, "subclass": "sc_champion",
                "ability_scores": {"str": 20, "dex": 14, "con": 16,
                                     "int": 10, "wis": 12, "cha": 10},
                "armor": {"base_ac": 18},
                "weapons": [_weapon("a_greatsword", "Greatsword", "str",
                                     "2d6", "slashing")]}},
        {"instance_id": "Cleric", "side": "pc", "position": [4, 1],
         "pc": {"class": "c_cleric", "level": 13,
                "ability_scores": {"str": 12, "dex": 10, "con": 16,
                                     "int": 10, "wis": 20, "cha": 12},
                "armor": {"base_ac": 18},
                "weapons": [_weapon("a_mace", "Mace", "str",
                                     "1d6", "bludgeoning")]}},
        {"instance_id": "Wizard_Evoker", "side": "pc", "position": [5, -1],
         "pc": {"class": "c_wizard", "level": 13, "subclass": "sc_evoker",
                "ability_scores": {"str": 8, "dex": 14, "con": 14,
                                     "int": 20, "wis": 12, "cha": 10},
                "armor": {"base_ac": 12},
                "weapons": [_weapon("a_dagger", "Dagger", "dex",
                                     "1d4", "piercing")]}},
        {"instance_id": "Bard_Lore", "side": "pc", "position": [4, -2],
         "pc": {"class": "c_bard", "level": 13,
                "subclass": "sc_college_of_lore",
                "ability_scores": {"str": 10, "dex": 16, "con": 14,
                                     "int": 12, "wis": 10, "cha": 20},
                "armor": {"base_ac": 15},
                "weapons": [_weapon("a_rapier", "Rapier", "dex",
                                     "1d8", "piercing")]}},
    ]


def _dragon_spec():
    return {"instance_id": "Adult_Red_Dragon", "side": "enemy",
            "position": [0, 0],
            "template_ref": {"entity_type": "monster",
                              "id": "m_adult_red_dragon"}}


def build_and_run():
    registry = load_content(REPO / "schema" / "content", validate=True,
                              schema_root=REPO / "schema" / "definitions")
    specs = _party_specs() + [_dragon_spec()]
    actors = []
    for s in specs:
        try:
            actors.append(_build_actor(s, registry))
        except Exception as e:   # surface a build failure clearly
            raise SystemExit(f"FAILED building {s.get('instance_id')}: {e}")
    enc = Encounter(id="first_sim_red_dragon_tier3", actors=actors)
    import random
    primitives_module.set_rng(random.Random(SEED))
    runner = EncounterRunner.new(enc, seed=SEED, content_registry=registry)
    primitives_module.set_rng(runner.rng)
    state = runner.run(seed=SEED)
    return state, actors


def _derive_stats(events, actors):
    """Per-combatant 'data buckets' derived from the raw event log — a
    first taste of the metrics worth storing per sim (DPR proxy, to-hit %,
    healing, damage taken)."""
    ids = [a.id for a in actors]
    st = {i: {"dmg_dealt": 0, "attacks": 0, "hits": 0, "healing": 0,
              "dmg_taken": 0, "saves_forced": 0, "saves_forced_failed": 0}
          for i in ids}
    for e in events:
        et = e.get("event")
        if et == "attack_roll" and e.get("result") in ("hit", "miss", "crit"):
            a = e.get("actor")
            if a in st:
                st[a]["attacks"] += 1
                if e["result"] in ("hit", "crit"):
                    st[a]["hits"] += 1
        elif et == "damage_dealt":
            a, t, amt = e.get("actor"), e.get("target"), e.get("amount", 0)
            if a in st:
                st[a]["dmg_dealt"] += amt
            if t in st:
                st[t]["dmg_taken"] += amt
        elif et == "healed" and e.get("target") in st:
            st[e["target"]]["healing"] += e.get("amount", 0)
        elif et == "forced_save":
            # attacker context isn't on the save line; count globally below
            pass
    return st


def _write_report(state, actors, events, snapshot):
    lines = []
    lines.append("# First Sim — Tier-3 party vs Adult Red Dragon\n")
    lines.append(f"*Seed {SEED}; reproducible via `sims/run_first_sim.py`. "
                 f"June 2 2026 — the project's first end-to-end encounter.*\n")
    lines.append(f"**Outcome:** {state.termination_reason} in "
                 f"{state.round} rounds.\n")
    lines.append("## Final state")
    lines.append("| Combatant | Side | HP | Status |")
    lines.append("|---|---|---|---|")
    for s in snapshot:
        tag = "💀 dead" if s["is_dead"] else ("🏃 fled" if s["is_fled"] else "alive")
        lines.append(f"| {s['id']} | {s['side']} | {s['hp_current']}/{s['hp_max']} | {tag} |")
    lines.append("")
    lines.append("## Derived stats (a first taste of the per-sim buckets)")
    lines.append("| Combatant | Dmg dealt | Attacks | Hits | To-hit % | Healing | Dmg taken |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    stats = _derive_stats(events, actors)
    for a in actors:
        s = stats[a.id]
        pct = f"{100*s['hits']//s['attacks']}%" if s["attacks"] else "—"
        lines.append(f"| {a.id} | {s['dmg_dealt']} | {s['attacks']} | "
                     f"{s['hits']} | {pct} | {s['healing']} | {s['dmg_taken']} |")
    lines.append("")
    lines.append("## Round-by-round")
    cur_round = None
    for e in events:
        et = e.get("event")
        if et == "turn_start":
            r = e.get("round")
            if r != cur_round:
                cur_round = r
                lines.append(f"\n### Round {r}")
            lines.append(f"\n**{e.get('actor')}'s turn**")
        elif et == "forced_save":
            lines.append(f"- save: {e.get('target')} {e.get('ability')} "
                         f"DC {e.get('dc')} → {e.get('outcome')} "
                         f"(rolled {e.get('total')})")
        elif et == "damage_dealt":
            lines.append(f"- {e.get('actor')} → {e.get('target')}: "
                         f"{e.get('amount')} {e.get('type')} "
                         f"({e.get('target_hp_remaining')} HP left)")
        elif et == "attack_roll" and e.get("actor"):
            lines.append(f"- attack: {e.get('actor')} → {e.get('target')} "
                         f"{e.get('result')} ({e.get('reason') or e.get('total')})")
        elif et == "healed":
            lines.append(f"- heal: {e.get('target')} +{e.get('amount')} "
                         f"(→ {e.get('hp_current')})")
        elif et == "legendary_action_used":
            lines.append(f"- ⚔️ legendary action: {e.get('option')} "
                         f"({e.get('remaining')} left)")
        elif et == "recharge_roll":
            lines.append(f"- 🎲 recharge {e.get('action')}: rolled "
                         f"{e.get('roll')} → {'recharged' if e.get('recharged') else 'not yet'}")
        elif et == "fled":
            lines.append(f"- 🏃 {e.get('actor')} FLED ({e.get('triggers')})")
        elif et == "creature_dropped":
            lines.append(f"- 💀 {e.get('actor') or e.get('target')} dropped")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    state, actors = build_and_run()
    events = state.event_log

    # Save raw events + a final snapshot.
    snapshot = [{"id": a.id, "side": a.side, "hp_current": a.hp_current,
                  "hp_max": a.hp_max, "is_dead": a.is_dead,
                  "is_fled": getattr(a, "is_fled", False)} for a in actors]
    (OUT / "events.json").write_text(json.dumps(
        {"seed": SEED, "termination_reason": state.termination_reason,
         "rounds": state.round, "final": snapshot, "events": events},
        indent=2), encoding="utf-8")

    _write_report(state, actors, events, snapshot)

    # Print a compact tail so the runner sees the outcome.
    print("=== OUTCOME ===")
    print("rounds:", state.round, "| reason:", state.termination_reason)
    for s in snapshot:
        tag = "DEAD" if s["is_dead"] else ("FLED" if s["is_fled"] else "alive")
        print(f"  {s['id']:<20} {s['side']:<6} {s['hp_current']:>4}/{s['hp_max']:<4} {tag}")
    print("event count:", len(events))


if __name__ == "__main__":
    main()
