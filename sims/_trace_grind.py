"""Trace-first diagnosis of the 45-round Moderate-fight grind (backlog #70).

Runs the calibrated day's first Moderate encounter — 3 Fire Giants — against
the L13 party AT FULL RESOURCES (isolated, so we measure per-fight decision
efficiency, not cross-fight depletion). Reconstructs each turn's action from
the event log and reports:

  - per-round, per-PC: what each PC did (attacked whom for how much, or
    dodged / dashed / disengaged / fled / moved-only / idle),
  - enemy HP trajectory (are the giants actually taking damage each round?),
  - aggregate PC action-kind histogram + damage-to-enemies per round.

If a 3-giant Moderate fight runs ~45 rounds, either the party deals almost
no damage per round (not attacking / whiffing / kiting) or something heals
the giants (they don't regenerate) — the histogram + DPR curve says which.

Usage: python sims/_trace_grind.py [seed]   (default 42)
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import engine.primitives as primitives_module
from engine.cli import _build_actor
from engine.core.runner import EncounterRunner
from engine.core.state import Encounter
from engine.loader import load_content
from sims.run_first_sim import _party_specs

REPO = Path(__file__).resolve().parent.parent

_PARTY_SPREAD = {"Fighter_Champion": [10, 0], "Cleric": [9, -8],
                 "Wizard_Evoker": [11, 5], "Bard_Lore": [9, 8]}
_GIANTS = [("m_fire_giant", 3)]
_MON_OFFSETS = [(0, 0), (0, 5), (0, -5)]

# Per-turn action events we care about (besides damage_dealt).
_WASTE_EVENTS = {
    "dodge_fallback": "DODGE", "dash_taken": "DASH",
    "disengage_taken": "DISENGAGE", "fled": "FLED",
    "retreat_triggered": "RETREAT", "hide_attempted": "HIDE",
    "steady_aim_taken": "STEADY_AIM", "search_attempted": "SEARCH",
}


def _build(registry):
    specs = _party_specs()
    for s in specs:
        s["position"] = _PARTY_SPREAD.get(s["instance_id"], s["position"])
    party = [_build_actor(s, registry) for s in specs]
    giants, i = [], 0
    for mid, count in _GIANTS:
        for n in range(count):
            giants.append(_build_actor(
                {"instance_id": f"{mid}_{n}", "side": "enemy",
                 "position": list(_MON_OFFSETS[i % len(_MON_OFFSETS)]),
                 "template_ref": {"entity_type": "monster", "id": mid}},
                registry))
            i += 1
    return party, giants


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    registry = load_content(REPO / "schema" / "content", validate=True,
                            schema_root=REPO / "schema" / "definitions")
    party, giants = _build(registry)
    pc_ids = {p.id for p in party}
    enemy_ids = {g.id for g in giants}
    enc = Encounter(id="grind", actors=party + giants)
    runner = EncounterRunner.new(enc, seed=seed, content_registry=registry)
    primitives_module.set_rng(runner.rng)
    state = runner.run(seed=seed)

    log = state.event_log

    # --- Segment the log into turns (turn_start .. next turn_start). --------
    turns = []   # list of (round, actor_id, [events])
    cur = None
    for e in log:
        if e.get("event") == "turn_start":
            if cur:
                turns.append(cur)
            cur = (e.get("round"), e.get("actor"), [])
        elif cur:
            cur[2].append(e)
    if cur:
        turns.append(cur)

    # --- Aggregates --------------------------------------------------------
    pc_action_kinds = Counter()
    dmg_to_enemies_by_round = defaultdict(float)
    pc_turns_no_damage = 0
    pc_turns_total = 0

    def _summarize_turn(events):
        """Return (label, dmg_to_enemy) for a PC turn. Classification order:
        ATTACK (dealt enemy damage) > CONTROL (forced_save/condition, no dmg) >
        CAST (slot spent / concentration, no dmg/control = buff/heal) > waste
        (dodge/dash/flee/...) > MOVE_ONLY > IDLE (no logged action at all)."""
        dmg = 0.0
        targets = []
        evs = [ev.get("event") for ev in events]
        for ev in events:
            if ev.get("event") == "damage_dealt" and ev.get("target") in enemy_ids:
                dmg += float(ev.get("amount", 0))
                targets.append((ev.get("target"), ev.get("amount"),
                                ev.get("target_hp_remaining")))
        if dmg > 0:
            tdesc = ", ".join(f"{t.split('_')[-1]}:-{a}->{hp}"
                              for t, a, hp in targets)
            return f"ATTACK {dmg:.0f} ({tdesc})", dmg
        spell = next((ev.get("action") for ev in events
                      if ev.get("event") == "aoe_origin_placed"), None) \
            or next((ev.get("action") for ev in events
                     if ev.get("event") == "spell_slot_consumed"), None)
        if "condition_applied" in evs or "forced_save" in evs:
            return f"CONTROL ({spell or '?'})", 0.0
        if "spell_slot_consumed" in evs or "concentration_started" in evs:
            return f"CAST ({spell or 'buff/heal'})", 0.0
        if "healed" in evs or "lay_on_hands" in evs:
            return "HEAL", 0.0
        waste = [lbl for ev in events
                 if (lbl := _WASTE_EVENTS.get(ev.get("event")))]
        if waste:
            return "+".join(waste), 0.0
        moved = "moved" in evs
        return ("MOVE_ONLY" if moved else "IDLE(hold)"), 0.0

    print(f"=== GRIND TRACE — 3 Fire Giants vs L13 party (seed {seed}) ===")
    print(f"outcome: {state.termination_reason}  rounds: {state.round}\n")

    last_round = None
    for rnd, actor_id, events in turns:
        if actor_id not in pc_ids:
            # still tally enemy damage to PCs? we focus on PC efficiency; skip
            continue
        pc_turns_total += 1
        label, dmg = _summarize_turn(events)
        kind = label.split()[0]
        pc_action_kinds[kind] += 1
        dmg_to_enemies_by_round[rnd] += dmg
        if dmg == 0:
            pc_turns_no_damage += 1
        if rnd != last_round:
            print(f"-- round {rnd} --")
            last_round = rnd
        print(f"  {actor_id:18} {label}")

    print("\n=== AGGREGATES ===")
    print(f"PC turns: {pc_turns_total}  | dealt-no-damage: {pc_turns_no_damage}"
          f" ({100*pc_turns_no_damage/max(1,pc_turns_total):.0f}%)")
    print(f"PC action-kind histogram: {dict(pc_action_kinds)}")
    print("\nEnemy HP trajectory (per round, dmg dealt TO giants):")
    for rnd in sorted(dmg_to_enemies_by_round):
        print(f"  round {rnd:>2}: {dmg_to_enemies_by_round[rnd]:>6.0f}")
    final = [(g.id, max(0, g.hp_current), g.hp_max) for g in giants]
    print("\nFinal giant HP:")
    for gid, hp, hpmax in final:
        print(f"  {gid:16} {hp}/{hpmax}")


if __name__ == "__main__":
    main()
