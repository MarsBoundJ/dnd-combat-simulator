"""WS-F3 — local SQLite run archive (reproducible, queryable cohorts).

Library-only persistence built on the **stdlib** ``sqlite3`` (Pyodide-
compatible — no native deps, works against ``:memory:`` and on-disk files).
Each finished run is stored so that:

* runs are reproducible — the full manifest (WS-F2) and F1 metrics are kept
  verbatim as JSON;
* cohorts are queryable — ``manifest_id`` (the manifest's canonical hash) is
  the cohort key, and the common summary fields (outcome, closeness, seed,
  engine SHA, content hash) are denormalized into indexed columns so the
  analysis surface (WS-F4) doesn't parse JSON to filter;
* storage is tiered per ``docs/stages-1-3-plan.md`` §3.6 — **aggregates
  (manifest + metrics) are always stored; the full event stream only when
  explicitly opted in** via ``record_run(..., events=...)``.

The module imports only ``engine.manifest.manifest_id`` (read-only) to derive
the cohort key; it never mutates manifest/metrics — both serialize as-is.

Public API
----------
    open_archive(path) -> sqlite3.Connection
    record_run(conn, manifest, metrics, *, events=None) -> int   # returns run id
    fetch_run(conn, run_id) -> dict | None
    fetch_runs_by_manifest(conn, manifest_id) -> list[dict]
    cohort_summary(conn, manifest_id) -> dict
    schema_version(conn) -> int
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Any

from engine.manifest import manifest_id as _manifest_id

__all__ = [
    "SCHEMA_VERSION", "ArchiveError",
    "open_archive", "record_run", "fetch_run", "fetch_runs_by_manifest",
    "cohort_summary", "schema_version",
]

# Bump when the archive table shape changes; add a migration in _MIGRATIONS.
SCHEMA_VERSION = 1


class ArchiveError(RuntimeError):
    """Raised on archive open/migration problems (e.g. a DB newer than code)."""


# ---------------------------------------------------------------------------
# Canonical JSON (stable, lossless-enough for a text store)
# ---------------------------------------------------------------------------

def _dumps(obj: Any) -> str:
    """Deterministic JSON. ``default=str`` catches the rare non-JSON scalar
    (a stray tuple/set) so persistence never raises. NOTE: JSON coerces
    non-string dict keys to strings (e.g. metrics' integer spell-slot levels)
    — read-back returns the JSON projection of the input, which is the
    archive's contract."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def _loads(text: str | None) -> Any:
    return json.loads(text) if text is not None else None


# ---------------------------------------------------------------------------
# Schema + migrations
# ---------------------------------------------------------------------------

def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE archive_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE runs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            manifest_id       TEXT    NOT NULL,   -- cohort key
            -- denormalized summary columns (indexed for common queries)
            outcome           TEXT,
            winning_side      TEXT,
            closeness         REAL,
            rounds            INTEGER,
            seed              INTEGER,
            engine_sha        TEXT,
            engine_dirty      INTEGER,            -- 0/1/NULL
            content_hash      TEXT,
            manifest_version  INTEGER,
            -- full payloads (aggregates always; events only when opted in)
            manifest_json     TEXT    NOT NULL,
            metrics_json      TEXT    NOT NULL,
            events_json       TEXT,               -- NULL unless events= supplied
            recorded_at       TEXT    NOT NULL
        );

        CREATE INDEX idx_runs_manifest_id  ON runs (manifest_id);
        CREATE INDEX idx_runs_outcome      ON runs (outcome);
        CREATE INDEX idx_runs_content_hash ON runs (content_hash);
        CREATE INDEX idx_runs_engine_sha   ON runs (engine_sha);
        CREATE INDEX idx_runs_seed         ON runs (seed);
        """
    )
    conn.execute(
        "INSERT INTO archive_meta (key, value) VALUES ('schema_version', '1')"
    )


# version -> migration that brings the DB *up to* that version.
_MIGRATIONS = {1: _migrate_to_v1}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _read_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "archive_meta"):
        return 0
    row = conn.execute(
        "SELECT value FROM archive_meta WHERE key='schema_version'"
    ).fetchone()
    return int(row[0]) if row else 0


def _migrate(conn: sqlite3.Connection) -> None:
    current = _read_version(conn)
    if current > SCHEMA_VERSION:
        raise ArchiveError(
            f"archive schema_version {current} is newer than this code "
            f"(supports {SCHEMA_VERSION}); upgrade the engine to read it."
        )
    for target in range(current + 1, SCHEMA_VERSION + 1):
        migrate = _MIGRATIONS.get(target)
        if migrate is None:
            raise ArchiveError(f"missing migration to schema_version {target}")
        migrate(conn)
        conn.execute(
            "UPDATE archive_meta SET value=? WHERE key='schema_version'",
            (str(target),),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_archive(path: str = ":memory:") -> sqlite3.Connection:
    """Open (creating + migrating as needed) a run archive at ``path``.

    ``path`` may be a filesystem path or ``":memory:"`` (default). Returns a
    ``sqlite3.Connection`` with ``row_factory = sqlite3.Row`` so reads behave
    like mappings. The schema is created at :data:`SCHEMA_VERSION` on first
    open and forward-migrated on subsequent opens; a DB written by newer code
    raises :class:`ArchiveError`.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    """The archive's current on-disk schema version."""
    return _read_version(conn)


def _summary_columns(manifest: dict, metrics: dict, mid: str) -> dict:
    engine = manifest.get("engine") or {}
    content = manifest.get("content") or {}
    run_params = manifest.get("run_params") or {}
    outcome = metrics.get("outcome") or {}
    closeness = outcome.get("closeness") or {}
    dirty = engine.get("git_dirty")
    return {
        "manifest_id": mid,
        "outcome": outcome.get("result"),
        "winning_side": outcome.get("winning_side"),
        "closeness": closeness.get("hp_fraction"),
        "rounds": metrics.get("rounds"),
        "seed": run_params.get("seed"),
        "engine_sha": engine.get("git_sha"),
        "engine_dirty": (None if dirty is None else int(bool(dirty))),
        "content_hash": content.get("hash"),
        "manifest_version": manifest.get("manifest_version"),
    }


def record_run(conn: sqlite3.Connection, manifest: dict, metrics: dict,
               *, events: list | None = None) -> int:
    """Persist one finished run; return its archive row id.

    ``manifest`` and ``metrics`` are stored verbatim as JSON (aggregates are
    always kept). ``events`` (the raw ``state.event_log``) is stored **only
    when supplied** — the opt-in tier from §3.6; pass ``None`` (default) to
    keep just the aggregates. The run's cohort key is ``manifest_id(manifest)``;
    two runs built from the same manifest share it and group as a cohort.
    """
    mid = _manifest_id(manifest)
    cols = _summary_columns(manifest, metrics, mid)
    cols["manifest_json"] = _dumps(manifest)
    cols["metrics_json"] = _dumps(metrics)
    cols["events_json"] = _dumps(events) if events is not None else None
    cols["recorded_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()

    keys = list(cols)
    placeholders = ", ".join("?" for _ in keys)
    sql = (f"INSERT INTO runs ({', '.join(keys)}) VALUES ({placeholders})")
    cur = conn.execute(sql, [cols[k] for k in keys])
    conn.commit()
    return int(cur.lastrowid)


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Rehydrate a runs row: summary columns as-is + parsed JSON payloads."""
    if row is None:
        return None
    d = dict(row)
    d["manifest"] = _loads(d.pop("manifest_json"))
    d["metrics"] = _loads(d.pop("metrics_json"))
    d["events"] = _loads(d.pop("events_json"))
    d["has_events"] = d["events"] is not None
    return d


def fetch_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """Fetch a single run by its archive row id (None if absent)."""
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return _row_to_dict(row)


def fetch_runs_by_manifest(conn: sqlite3.Connection,
                           manifest_id: str) -> list[dict]:
    """All runs sharing ``manifest_id`` (the cohort), oldest-first by row id."""
    rows = conn.execute(
        "SELECT * FROM runs WHERE manifest_id=? ORDER BY id", (manifest_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def cohort_summary(conn: sqlite3.Connection, manifest_id: str) -> dict:
    """Aggregate a cohort (§3.6) without parsing JSON — straight off the
    indexed summary columns. Returns run count, outcome breakdown, and mean
    closeness over runs that recorded one."""
    n = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE manifest_id=?", (manifest_id,)
    ).fetchone()[0]
    outcomes = {
        r["outcome"]: r["c"]
        for r in conn.execute(
            "SELECT outcome, COUNT(*) AS c FROM runs WHERE manifest_id=? "
            "GROUP BY outcome", (manifest_id,)
        ).fetchall()
    }
    mean_close = conn.execute(
        "SELECT AVG(closeness) FROM runs "
        "WHERE manifest_id=? AND closeness IS NOT NULL", (manifest_id,)
    ).fetchone()[0]
    return {
        "manifest_id": manifest_id,
        "runs": int(n),
        "outcomes": outcomes,
        "mean_closeness": mean_close,
    }
