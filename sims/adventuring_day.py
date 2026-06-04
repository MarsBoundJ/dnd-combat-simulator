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
from engine.core.rest import apply_short_rest, apply_long_rest
from engine.core.runner import EncounterRunner
from engine.core.state import Encounter
from engine.loader import load_content
from sims.run_first_sim import _party_specs

REPO = Path(__file__).resolve().parent.parent

# A graduated day for a 4-person L13 party: warm-up -> mediums -> climax.
# (monster_id, count) per encounter. Tuned to be survivable-to-climax, not
# XP-precise — the harness reports burn-down; exact daily-budget tuning is a
# follow-up.
DAY = [
    ("Manticore flight",      [("m_manticore", 3)]),
    ("Ogre raiders",          [("m_ogre", 2), ("m_berserker", 2)]),
    # --- short rest ---
    ("Wyvern pair",           [("m_wyvern", 2)]),
    ("Vampire spawn ambush",  [("m_vampire_spawn", 3)]),
    # --- short rest ---
    ("Fire giant",            [("m_fire_giant", 1)]),
    ("CLIMAX: Adult Red Dragon", [("m_adult_red_dragon", 1)]),
]
SHORT_REST_AFTER = {1, 3}   # indices after which the party short-rests

# Monster placement: spread a few squares around the origin; the party
# starts in the run-3 spread formation (around x=8-11).
_MON_OFFSETS = [(0, 0), (0, 4), (0, -4), (2, 2), (2, -2), (-2, 0), (4, 0)]
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
        })
        if pcs_up == 0:
            party_alive = False
            break
        if i in SHORT_REST_AFTER:
            for p in party:
                if p.is_alive():
                    apply_short_rest(p, state)
                    # Hit-Dice approximation: a short rest recovers ~half the
                    # missing HP (real parties spend Hit Dice + a bit of
                    # healing). Without this the party can't recover between
                    # fights and the pacing signal is pure attrition noise.
                    p.hp_current = min(p.hp_max,
                                        p.hp_current + (p.hp_max - p.hp_current) // 2)
    # End-of-day long rest (for completeness / multi-day extension).
    if party_alive:
        for p in party:
            if p.is_alive():
                apply_long_rest(p, party and state)

    print(f"=== ADVENTURING DAY — seed {seed} "
          f"({'survived' if party_alive else 'WIPED'}) ===\n")
    print(f"{'#':>2} {'encounter':<26} {'rem':>3} {'rounds':>6} "
          f"{'PCs up':>6} {'slots spent':>11} {'left':>5} {'hi(>=4) left':>12}  outcome")
    for n, r in enumerate(rows):
        print(f"{n:>2} {r['enc']:<26} {r['remaining']:>3} {r['rounds']:>6} "
              f"{r['pcs_up']:>6} {r['slots_spent']:>11} {r['slots_left']:>5} "
              f"{r['hi_left']:>12}  {r['reason']}")
    print("\nNova-late check: slots_spent should rise as 'rem' falls "
          "(conserve early, dump late).")


if __name__ == "__main__":
    main()
