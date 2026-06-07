"""End-to-end demonstration of the dial-5 evoker's signature play (#1 + #2):

  Two Fighters are surrounded by a pack of Ghouls. A perfect-knowledge (dial 5)
  Evocation Wizard reads the situation and drops ONE Fireball on the whole
  cluster — Sculpt Spells exempts the Fighters (zero friendly fire), and the
  kill-value model picks the slot level that reliably clears the Ghouls.

This sim narrates the moment from the event log: the spell, its slot level, the
allies it sculpted out, and the enemies it dropped — the full
sculpt + kill-value arc in actual play.

Usage:
    python -m sims.sculpt_fireball_demo [seed]
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

from engine.loader import load_content
from engine.core.state import Encounter
from engine.core.runner import EncounterRunner
from engine.core.combat_metrics import build_contribution_ledger, classify_diff
import engine.primitives as pm
from engine.cli import _build_actor

REPO = Path(__file__).resolve().parent.parent

_INT = {"str": 8, "dex": 14, "con": 14, "int": 20, "wis": 12, "cha": 10}
_STR = {"str": 18, "dex": 12, "con": 16, "int": 8, "wis": 12, "cha": 10}


def _build(reg):
    specs = [
        # The Evoker — ranged, perfect play. 5th-level slots available at L13.
        {"instance_id": "Evoker", "side": "pc", "position": [12, 0],
         "pc": {"class": "c_wizard", "level": 13, "subclass": "sc_evoker",
                "ability_scores": _INT}},
        # Two Fighters, surrounded in melee.
        {"instance_id": "Fighter_A", "side": "pc", "position": [5, 0],
         "pc": {"class": "c_fighter", "level": 13, "subclass": "sc_champion",
                "ability_scores": _STR}},
        {"instance_id": "Fighter_B", "side": "pc", "position": [6, 0],
         "pc": {"class": "c_fighter", "level": 13, "subclass": "sc_champion",
                "ability_scores": _STR}},
    ]
    # Six Ghouls ringing the two Fighters (all within a 20-ft Fireball).
    ghoul_pos = [(5, 1), (6, 1), (5, -1), (6, -1), (4, 0), (7, 0)]
    for i, (x, y) in enumerate(ghoul_pos):
        specs.append({"instance_id": f"Ghoul_{i}", "side": "enemy",
                      "position": [x, y],
                      "template_ref": {"entity_type": "monster",
                                       "id": "m_ghoul"}})
    return [_build_actor(s, reg) for s in specs]


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    reg = load_content(REPO / "schema" / "content", validate=True,
                        schema_root=REPO / "schema" / "definitions")
    actors = _build(reg)
    pcs = [a for a in actors if a.side == "pc"]
    ghouls = [a for a in actors if a.side == "enemy"]

    print("=== SCULPT + KILL-VALUE DEMO — dial 5 Evoker vs a Ghoul swarm ===")
    print(f"Setup: 2 Fighters at (5,0)/(6,0) ringed by {len(ghouls)} Ghouls "
          f"(22 HP each); Evoker at (12,0).\n")

    enc = Encounter(id="demo", actors=actors)
    pm.set_rng(random.Random(seed))
    runner = EncounterRunner.new(enc, seed=seed, content_registry=reg)
    pm.set_rng(runner.rng)
    state = runner.run(seed=seed,
                       optimization_dials={"pc": 5, "enemy": 1})

    # --- Narrate the Evoker's first AoE from the event log ---
    log = state.event_log
    # Find the first spell-slot the Evoker consumed (its big play) + level.
    cast = next((e for e in log if e.get("event") == "spell_slot_consumed"
                 and e.get("actor") == "Evoker"), None)
    # forced_save events grouped: sculpted allies vs damaged enemies in R1.
    sculpted = [e["target"] for e in log
                if e.get("event") == "forced_save" and e.get("sculpt_spells")]
    fireball_dmg = [(e["target"], e["amount"]) for e in log
                    if e.get("event") == "damage_dealt"
                    and e.get("actor") == "Evoker"]

    spells = [e.get("action") or e.get("action_id") for e in log
              if e.get("event") == "spell_slot_consumed"
              and e.get("actor") == "Evoker"]
    print(f"Evoker spells cast: {spells or '(none)'}")
    print(f"  Sculpt Spells protected: {sorted(set(sculpted)) or '(none)'}")

    hit = {}
    for tid, amt in fireball_dmg:
        hit[tid] = hit.get(tid, 0) + amt
    ff = sum(amt for tid, amt in hit.items() if tid.startswith("Fighter"))
    print(f"  Evoker damage by target:")
    for tid, amt in sorted(hit.items()):
        print(f"    {tid:10} {amt:>4.0f}")
    print(f"  >> Evoker FRIENDLY-FIRE to allies: {ff:.0f}")

    print()
    ghouls_down = sum(1 for g in ghouls if not g.is_alive())
    print(f"Result: {ghouls_down}/{len(ghouls)} Ghouls down; "
          f"Evoker dealt {ff:.0f} damage to its own party "
          f"(sculpt makes this 0).")
    print(f"Outcome: {state.termination_reason} in {state.round} rounds\n")

    led = build_contribution_ledger(state)
    print(f"Evoker contribution: "
          f"{led['per_actor'].get('Evoker', {}).get('damage_dealt', 0):.0f} dmg")
    print(f"d_iff: {led['d_iff']:.2f} ({led['difficulty_band']})")


if __name__ == "__main__":
    main()
