"""Integrity checks for docs/spell-master-list.csv — the single spell
inventory (PHB 2024 ∪ SRD 5.2.1, plus already-built out-of-scope extras).

The contract these tests enforce:
  - the list itself is well-formed (unique names, valid enums);
  - every row marked built/stub points at content files that exist;
  - every content file that implements a listed spell is referenced by
    that spell's row — so a new spell YAML can't land without the master
    list being updated, and a master-list row can't claim a file that
    doesn't implement it.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MASTER = REPO_ROOT / "docs" / "spell-master-list.csv"
CONTENT_DIRS = [
    REPO_ROOT / "schema" / "content" / "features",
    REPO_ROOT / "schema" / "content" / "spells",
]

SCHOOLS = {
    "Abjuration", "Conjuration", "Divination", "Enchantment",
    "Evocation", "Illusion", "Necromancy", "Transmutation",
}
SOURCES = {"srd_5.2.1", "phb_2024", "xge"}
TIERS = {"S", "A", "B", "C", "D"}
STATUSES = {"todo", "stub", "built"}

_NAME_RE = re.compile(r"^name:\s*[\"']?(.+?)[\"']?\s*(#.*)?$")


def load_master():
    with open(MASTER, newline="") as f:
        return list(csv.DictReader(f))


def content_file_names():
    """Map content filename -> declared feature/spell name."""
    out = {}
    for d in CONTENT_DIRS:
        for p in sorted(d.glob("*.yaml")):
            for line in p.open():
                m = _NAME_RE.match(line)
                if m:
                    out[p.name] = m.group(1).strip()
                    break
    return out


def test_master_list_well_formed():
    rows = load_master()
    assert len(rows) >= 390, "master list lost rows"

    names = [r["name"] for r in rows]
    assert len(names) == len(set(names)), "duplicate spell names"

    for r in rows:
        n = r["name"]
        assert 0 <= int(r["level"]) <= 9, n
        assert r["school"] in SCHOOLS, (n, r["school"])
        assert r["source"] in SOURCES, (n, r["source"])
        assert r["tier"] in TIERS, (n, r["tier"])
        assert r["status"] in STATUSES, (n, r["status"])
        if r["srd_name"]:
            assert r["source"] == "srd_5.2.1", (
                f"{n}: srd_name set but source is {r['source']}")


def test_status_matches_files():
    for r in load_master():
        files = [f for f in r["files"].split(";") if f]
        if r["status"] in ("built", "stub"):
            assert files, f"{r['name']}: status {r['status']} but no files"
        else:
            assert not files, f"{r['name']}: status todo but files listed"
        for f in files:
            assert any((d / f).is_file() for d in CONTENT_DIRS), (
                f"{r['name']}: listed file {f} does not exist")


def test_no_unregistered_spell_files():
    """Every content file whose declared name matches a master-list spell
    (PHB or SRD name) must be referenced on that spell's row."""
    rows = load_master()
    by_name = {}
    for r in rows:
        by_name[r["name"]] = r
        if r["srd_name"]:
            by_name[r["srd_name"]] = r

    for fname, declared in content_file_names().items():
        row = by_name.get(declared)
        if row is None:
            continue  # class/subclass feature, invocation, variant, etc.
        listed = [f for f in row["files"].split(";") if f]
        assert fname in listed, (
            f"{fname} implements '{declared}' but is not listed on the "
            f"master-list row for '{row['name']}' — update "
            f"docs/spell-master-list.csv (files + status)")
