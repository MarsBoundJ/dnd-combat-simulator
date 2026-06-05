"""Adventuring-day harness — run a Tier-3 party through a graduated SEQUENCE
of encounters with persistent HP / spell slots / resources, two short rests,
and a closing climactic boss, so NOVA-LATE pacing (PR #180) is actually
EXERCISED: with `encounters_remaining` decreasing each fight, the casters'
slot opportunity-cost falls, so they should CONSERVE early and NOVA late.

Also the seed of the future "idealized adventuring day" build-rubric (Dunn's
daily-XP-budget framing): one party, one day, measured resource burn-down.

Reuses the engine wholesale: EncounterRunner per fight (PCs persist across
fights as the same Actor objects), apply_short_rest / apply_long_rest
between them. Reports a per-encounter table — outcome, party HP, and total
spell slots remaining — so the conserve-early / nova-late curve is visible.

Usage: python sims/adventuring_day.py [seed]   (default 42)
"""
from __future__ import annotations

import sys
from pathlib import Path

import engine.primitives as primitives_module
from engine.cli import _build_actor
from engine.core.encounter_budget import encounter_report
from engine.core.rest import apply_short_rest, apply_long_rest
from engine.core.runner import EncounterRunner
from engine.core.state import Encounter
from engine.loader import load_content
from sims.run_first_sim import _party_specs

REPO = Path(__file__).resolve().parent.parent

# The party this day is built for (drives the 2024 XP budget read-out).
PARTY_LEVEL = 13
PARTY_SIZE = 4

# A 2024-DMG-budget-CALIBRATED graduated day for a 4-person L13 party
# (low=10,400 / moderate=16,800 / high=21,600). Each encounter spends real
# budget — Low warm-up -> four Moderates (with two short rests) -> a High
# climax — so resources actually attrite before the boss. (The prior roster
# was five SUB-LOW skirmishes then a High dragon — no real attrition; it only
# looked depleting because the fights ground on for 20+ rounds.) All fights
# stay <= 2 monsters/character, so none trip the "Many Creatures" advisory.
# (monster_id, count) per encounter; difficulty in the trailing comment.
DAY = [
    ("Skirmish line",  [("m_wyvern", 3), ("m_manticore", 4)]),   # 9,700  low
    ("Giant raiders",  [("m_fire_giant", 3)]),                   # 15,000 mod
    # --- short rest ---
    ("Vampire ambush", [("m_vampire_spawn", 6), ("m_wyvern", 2)]),  # 15,400 mod
    ("Wyvern stoop",   [("m_wyvern", 5), ("m_fire_giant", 1)]),  # 16,500 mod
    # --- short rest ---
    ("Giant vanguard", [("m_fire_giant", 3)]),                   # 15,000 mod
    ("CLIMAX: Adult Red Dragon", [("m_adult_red_dragon", 1)]),   # 18,000 high
]
SHORT_REST_AFTER = {1, 3}   # indices after which the party short-rests

# Monster placement: spread a few squares around the origin; the party
# starts in the run-3 spread formation (around x=8-11). Enough distinct
# offsets for the largest roster (8 monsters in "Vampire ambush").
_MON_OFFSETS = [(0, 0), (0, 4), (0, -4), (2, 2), (2, -2),
                (-2, 0), (4, 0), (4, 4), (4, -4)]
_PARTY_SPREAD = {"Fighter_Champion": [10, 0], "Cleric": [9, -8],
                 "Wizard_Evoker": [11, 5], "Bard_Lore": [9, 8]}


def _build_party(registry):
    specs = _party_specs()
    for s in specs:
        s["position"] = _PARTY_SPREAD.get(s["instance_id"], s["position"])
    return [_build_actor(s, registry) for s in specs]


def _build_monsters(registry, monster_counts):
    actors, i = [], 0
    for mid, count in monster_counts:
        for n in range(count):
            spec = {"instance_id": f"{mid}_{n}", "side": "enemy",
                    "position": list(_MON_OFFSETS[i % len(_MON_OFFSETS)]),
                    "template_ref": {"entity_type": "monster", "id": mid}}
            actors.append(_build_actor(spec, registry))
            i += 1
    return actors


def _slot_total(pc):
    return sum(int(v) for v in (pc.spell_slots or {}).values())


def _hi_slots(pc):
    """Count of high-level slots (>= 4th) — the 'big guns' nova-pacing is
    supposed to make the party CONSERVE for the climax."""
    return sum(int(v) for lvl, v in (pc.spell_slots or {}).items() if int(lvl) >= 4)


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    registry = load_content(REPO / "schema" / "content", validate=True,
                             schema_root=REPO / "schema" / "definitions")
    party = _build_party(registry)
    casters = [p for p in party if _slot_total(p) > 0 or p.spell_slots]
    primitives_module.set_rng(__import__("random").Random(seed))

    rows = []
    party_alive = True
    for i, (name, monster_counts) in enumerate(DAY):
        remaining = len(DAY) - i - 1   # fights still to come AFTER this one
        slots_before = {p.id: _slot_total(p) for p in party}
        monsters = _build_monsters(registry, monster_counts)
        budget = encounter_report(monsters, PARTY_LEVEL, PARTY_SIZE)
        enc = Encounter(id=f"day_enc_{i}", actors=party + monsters)
        runner = EncounterRunner.new(enc, seed=seed + i,
                                      content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=seed + i,
                            encounters_remaining_today=remaining)

        pcs_up = sum(1 for p in party
                     if p.is_alive() and not getattr(p, "is_fled", False))
        slots_after = {p.id: _slot_total(p) for p in party}
        spent = sum(slots_before[p.id] - slots_after[p.id] for p in casters)
        rows.append({
            "enc": name, "remaining": remaining,
            "reason": state.termination_reason, "rounds": state.round,
            "pcs_up": pcs_up,
            "party_hp": sum(max(0, p.hp_current) for p in party),
            "slots_left": sum(slots_after[p.id] for p in casters),
            "slots_spent": spent,
            "hi_left": sum(_hi_slots(p) for p in casters),
            "xp": budget["spent_xp"], "diff": budget["difficulty"],
        })
        if pcs_up == 0:
            party_alive = False
            break
        if i in SHORT_REST_AFTER:
            for p in party:
                if p.is_alive():
                    # apply_short_rest now spends Hit Dice to heal (real
                    # recovery; the prior half-HP stand-in is gone).
                    apply_short_rest(p, state)
    # End-of-day long rest (for completeness / multi-day extension).
    if party_alive:
        for p in party:
            if p.is_alive():
                apply_long_rest(p, party and state)

    from engine.core.encounter_budget import budgets_for
    b = budgets_for(PARTY_LEVEL, PARTY_SIZE)
    print(f"=== ADVENTURING DAY — seed {seed} "
          f"({'survived' if party_alive else 'WIPED'}) ===")
    print(f"2024 XP budget (party {PARTY_SIZE}×L{PARTY_LEVEL}): "
          f"low={b['low']:,} / moderate={b['moderate']:,} / "
          f"high={b['high']:,}\n")
    print(f"{'#':>2} {'encounter':<26} {'XP':>6} {'diff':>9} {'rem':>3} "
          f"{'rounds':>6} {'PCs up':>6} {'slots spent':>11} {'left':>5} "
          f"{'hi(>=4) left':>12}  outcome")
    for n, r in enumerate(rows):
        print(f"{n:>2} {r['enc']:<26} {r['xp']:>6} {r['diff']:>9} "
              f"{r['remaining']:>3} {r['rounds']:>6} {r['pcs_up']:>6} "
              f"{r['slots_spent']:>11} {r['slots_left']:>5} "
              f"{r['hi_left']:>12}  {r['reason']}")
    print("\nNova-late check: slots_spent should rise as 'rem' falls "
          "(conserve early, dump late).")
    print("Day is 2024-budget-calibrated: Low -> 4× Moderate -> High climax, "
          "so resources genuinely attrite before the boss.")


if __name__ == "__main__":
    main()
