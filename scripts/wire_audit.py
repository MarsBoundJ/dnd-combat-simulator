#!/usr/bin/env python3
"""Phase 3A helper: audit a class's built-spell wiring status.

For a given base class, lists every BUILT spell the class may take (per
the `classes` column in docs/spell-master-list.csv) that produces a
combat action, tagged with:
  - its slot-gated WIRE level (full vs half caster), and
  - whether it is already in the class's level_table (WIRED) or still
    missing (TODO).

This is the deterministic candidate computation behind 3A — run it,
then add every TODO feature id to the level_table row at its WIRE level
(spells alphabetical within a level). Re-run until no TODO remains, then
run the full suite.

    python scripts/wire_audit.py cleric
    python scripts/wire_audit.py paladin   # half-caster table

Mechanism tags:
  action_template / pc_builder  -> rides the auto-attach path
  legacy:<scope>                -> hardcoded builder keyed by feature id
  (no action)                   -> not actionable; never wire (skipped)
"""
import csv
import sys
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "spell-master-list.csv"
FEAT = ROOT / "schema" / "content" / "features"
CLS = ROOT / "schema" / "content" / "classes"

# Character level at which each spell tier (0–9) first becomes castable.
FULL_CASTER = {0:1, 1:1, 2:3, 3:5, 4:7, 5:9, 6:11, 7:13, 8:15, 9:17}
HALF_CASTER = {1:2, 2:5, 3:9, 4:13, 5:17}   # Paladin / Ranger
HALF = {"paladin", "ranger"}


def mechanism(files: str):
    for f in files.split(";"):
        if not f:
            continue
        p = FEAT / f
        if not p.exists():
            continue
        d = yaml.safe_load(p.read_text())
        if not isinstance(d, dict):
            continue
        if "action_template" in d:
            return "action_template"
        if "pc_builder" in d:
            return "pc_builder"
        scope = (d.get("contract") or {}).get("scope") or ""
        if "action" in scope:
            return f"legacy:{scope}"
        if d.get("type") == "active":
            return "active(check)"
    return None


def main(cls: str):
    table = HALF_CASTER if cls in HALF else FULL_CASTER
    cfile = CLS / f"c_{cls}.yaml"
    wired = set(re.findall(r"f_[a-z0-9_]+", cfile.read_text())) if cfile.exists() else set()

    rows = []
    for r in csv.DictReader(open(CSV)):
        if r["status"] != "built":
            continue
        if cls not in r["classes"].split(";"):
            continue
        tier = int(r["level"])
        if tier not in table:           # half-casters never get tier 0/6+
            continue
        fid = r["files"].split(";")[0].replace(".yaml", "")
        mech = mechanism(r["files"])
        if mech is None:
            continue                    # no action -> never wire
        rows.append((table[tier], tier, fid, r["name"], mech,
                     fid in wired))

    rows.sort(key=lambda x: (x[0], x[1], x[3]))
    todo = [r for r in rows if not r[5]]
    print(f"{cls}: {len(rows)} actionable built spells, "
          f"{len(todo)} TODO\n")
    cur = None
    for wire, tier, fid, name, mech, is_wired in rows:
        if wire != cur:
            print(f"  --- wire at L{wire} ---")
            cur = wire
        state = "WIRED" if is_wired else "TODO "
        print(f"   {state} t{tier} {fid:38} {mech}")
    if todo:
        print("\nTODO feature ids grouped by wire level:")
        bylvl = {}
        for wire, tier, fid, *_ in todo:
            bylvl.setdefault(wire, []).append(fid)
        for wire in sorted(bylvl):
            print(f"  L{wire}: {', '.join(sorted(bylvl[wire]))}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/wire_audit.py <class>")
    main(sys.argv[1].lower())
