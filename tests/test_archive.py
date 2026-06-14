"""WS-F3 — engine.archive SQLite run archive.

Covers schema init/migration + version carry, record→read-back round-trip
(manifest + metrics), the §3.6 storage tiers (aggregates always / events
opt-in), cohort grouping by manifest_id (two runs share one) + cohort_summary,
indexed summary-column queries, distinct manifests forming distinct cohorts,
on-disk persistence across reopen, and the newer-DB guard. Uses :memory: dbs
except where on-disk persistence is the point.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from engine.archive import (
    SCHEMA_VERSION, ArchiveError,
    open_archive, record_run, fetch_run, fetch_runs_by_manifest,
    cohort_summary, schema_version,
)
from engine.manifest import build_manifest, manifest_id
from engine.metrics import compute_metrics


# ── fixtures ─────────────────────────────────────────────────────────────────

def _roster():
    return {"pc": {"side": "pc", "hp_max": 40, "name": "Hero"},
            "foe": {"side": "enemy", "hp_max": 30, "name": "Foe"}}


def _victory_events():
    return [
        {"event": "turn_start", "actor": "pc", "round": 1},
        {"event": "attack_roll", "actor": "pc", "target": "foe", "d20": 19, "result": "hit"},
        {"event": "damage_dealt", "actor": "pc", "target": "foe",
         "amount": 99, "type": "slashing", "target_hp_remaining": 0},
        {"event": "spell_slot_consumed", "actor": "pc", "slot_level": 2, "remaining": 1},
        {"event": "creature_dropped", "creature": "foe"},
    ]


def _tpk_events():
    return [
        {"event": "turn_start", "actor": "foe", "round": 1},
        {"event": "damage_dealt", "actor": "foe", "target": "pc",
         "amount": 99, "type": "slashing", "target_hp_remaining": 0},
        {"event": "creature_dropped", "creature": "pc"},
    ]


def _manifest(seed=7, **kw):
    return build_manifest(seed=seed, engine_sha="deadbeef", **kw)


def _metrics(events):
    return compute_metrics(events, roster=_roster())


# ── schema / migration ───────────────────────────────────────────────────────

class SchemaTest(unittest.TestCase):

    def test_open_creates_schema_at_current_version(self):
        conn = open_archive(":memory:")
        self.assertEqual(schema_version(conn), SCHEMA_VERSION)
        # runs + meta tables exist
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("runs", names)
        self.assertIn("archive_meta", names)

    def test_summary_columns_and_indexes_exist(self):
        conn = open_archive(":memory:")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
        for c in ("manifest_id", "outcome", "winning_side", "closeness",
                  "rounds", "seed", "engine_sha", "engine_dirty",
                  "content_hash", "manifest_version", "manifest_json",
                  "metrics_json", "events_json", "recorded_at"):
            self.assertIn(c, cols)
        idx = {r[1] for r in conn.execute("PRAGMA index_list(runs)").fetchall()}
        self.assertIn("idx_runs_manifest_id", idx)

    def test_reopen_is_idempotent_and_preserves_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "a.db")
            conn = open_archive(path)
            rid = record_run(conn, _manifest(), _metrics(_victory_events()))
            conn.close()
            # reopen: migration is a no-op, prior row still readable
            conn2 = open_archive(path)
            self.assertEqual(schema_version(conn2), SCHEMA_VERSION)
            self.assertIsNotNone(fetch_run(conn2, rid))

    def test_newer_db_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "future.db")
            conn = open_archive(path)
            conn.execute("UPDATE archive_meta SET value='999' "
                         "WHERE key='schema_version'")
            conn.commit()
            conn.close()
            with self.assertRaises(ArchiveError):
                open_archive(path)


# ── record / read-back round-trip ────────────────────────────────────────────

class RoundTripTest(unittest.TestCase):

    def setUp(self):
        self.conn = open_archive(":memory:")
        self.man = _manifest()
        self.met = _metrics(_victory_events())

    def test_record_returns_row_id_and_reads_back(self):
        rid = record_run(self.conn, self.man, self.met)
        run = fetch_run(self.conn, rid)
        self.assertIsNotNone(run)
        self.assertEqual(run["id"], rid)
        self.assertEqual(run["manifest_id"], manifest_id(self.man))

    def test_manifest_and_metrics_round_trip_as_json_projection(self):
        rid = record_run(self.conn, self.man, self.met, events=_victory_events())
        run = fetch_run(self.conn, rid)
        # The store keeps the JSON projection of the inputs (JSON coerces
        # int dict keys to strings — the documented archive contract).
        self.assertEqual(run["manifest"],
                         json.loads(json.dumps(self.man, sort_keys=True, default=str)))
        self.assertEqual(run["metrics"],
                         json.loads(json.dumps(self.met, sort_keys=True, default=str)))
        self.assertEqual(run["events"], _victory_events())

    def test_summary_columns_match_inputs(self):
        rid = record_run(self.conn, self.man, self.met)
        run = fetch_run(self.conn, rid)
        self.assertEqual(run["outcome"], "victory")
        self.assertEqual(run["winning_side"], "pc")
        self.assertEqual(run["closeness"], 1.0)
        self.assertEqual(run["seed"], 7)
        self.assertEqual(run["engine_sha"], "deadbeef")
        self.assertEqual(run["manifest_version"], self.man["manifest_version"])
        self.assertEqual(run["rounds"], self.met["rounds"])

    def test_content_hash_column_populated_when_manifest_has_content(self):
        content = {"spell": {"sp_x": {"id": "sp_x", "name": "X"}}}
        man = build_manifest(seed=1, engine_sha="z", content_registry=content)
        rid = record_run(self.conn, man, _metrics(_victory_events()))
        run = fetch_run(self.conn, rid)
        self.assertIsNotNone(run["content_hash"])
        self.assertTrue(run["content_hash"].startswith("sha256:"))
        self.assertEqual(run["content_hash"], man["content"]["hash"])

    def test_fetch_missing_run_returns_none(self):
        self.assertIsNone(fetch_run(self.conn, 999))


# ── storage tiers (§3.6): aggregates always, events opt-in ───────────────────

class StorageTierTest(unittest.TestCase):

    def setUp(self):
        self.conn = open_archive(":memory:")

    def test_aggregates_always_events_omitted_by_default(self):
        rid = record_run(self.conn, _manifest(), _metrics(_victory_events()))
        run = fetch_run(self.conn, rid)
        self.assertFalse(run["has_events"])
        self.assertIsNone(run["events"])
        # aggregates are present regardless
        self.assertIsNotNone(run["manifest"])
        self.assertIsNotNone(run["metrics"])

    def test_events_stored_only_when_opted_in(self):
        ev = _victory_events()
        rid = record_run(self.conn, _manifest(), _metrics(ev), events=ev)
        run = fetch_run(self.conn, rid)
        self.assertTrue(run["has_events"])
        self.assertEqual(run["events"], ev)

    def test_events_json_null_in_column_when_omitted(self):
        record_run(self.conn, _manifest(), _metrics(_victory_events()))
        row = self.conn.execute("SELECT events_json FROM runs").fetchone()
        self.assertIsNone(row["events_json"])


# ── cohorts (manifest_id grouping) ───────────────────────────────────────────

class CohortTest(unittest.TestCase):

    def setUp(self):
        self.conn = open_archive(":memory:")

    def test_two_runs_same_manifest_group_as_cohort(self):
        man = _manifest()
        ev = _victory_events()
        record_run(self.conn, man, _metrics(ev))
        record_run(self.conn, man, _metrics(ev), events=ev)
        cohort = fetch_runs_by_manifest(self.conn, manifest_id(man))
        self.assertEqual(len(cohort), 2)
        self.assertTrue(all(r["manifest_id"] == manifest_id(man) for r in cohort))
        # ordered oldest-first
        self.assertEqual([r["id"] for r in cohort],
                         sorted(r["id"] for r in cohort))

    def test_distinct_manifests_are_distinct_cohorts(self):
        m1, m2 = _manifest(seed=1), _manifest(seed=2)
        self.assertNotEqual(manifest_id(m1), manifest_id(m2))
        record_run(self.conn, m1, _metrics(_victory_events()))
        record_run(self.conn, m2, _metrics(_tpk_events()))
        self.assertEqual(len(fetch_runs_by_manifest(self.conn, manifest_id(m1))), 1)
        self.assertEqual(len(fetch_runs_by_manifest(self.conn, manifest_id(m2))), 1)

    def test_cohort_summary_aggregates_off_indexed_columns(self):
        man = _manifest()
        # mixed outcomes within one cohort (same manifest, different runs)
        record_run(self.conn, man, _metrics(_victory_events()))
        record_run(self.conn, man, _metrics(_victory_events()))
        record_run(self.conn, man, _metrics(_tpk_events()))
        summ = cohort_summary(self.conn, manifest_id(man))
        self.assertEqual(summ["runs"], 3)
        self.assertEqual(summ["outcomes"], {"victory": 2, "tpk": 1})
        self.assertIsNotNone(summ["mean_closeness"])

    def test_indexed_columns_are_queryable_without_json(self):
        man = _manifest()
        record_run(self.conn, man, _metrics(_victory_events()))
        record_run(self.conn, man, _metrics(_tpk_events()))
        n_victory = self.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE outcome='victory'").fetchone()[0]
        self.assertEqual(n_victory, 1)
        n_sha = self.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE engine_sha='deadbeef'").fetchone()[0]
        self.assertEqual(n_sha, 2)


# ── Pyodide-compat sanity: pure stdlib sqlite3, :memory: works ───────────────

class MemoryDbTest(unittest.TestCase):

    def test_default_is_in_memory(self):
        conn = open_archive()  # default ":memory:"
        self.assertIsInstance(conn, sqlite3.Connection)
        rid = record_run(conn, _manifest(), _metrics(_victory_events()))
        self.assertEqual(fetch_run(conn, rid)["outcome"], "victory")


if __name__ == "__main__":
    unittest.main()
