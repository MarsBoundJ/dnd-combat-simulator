# Stages 1–3 — Parallel Execution & Conflict-Avoidance Guide

**Companion to** `docs/stages-1-3-plan.md` (v2). **Builds on**
`docs/PARALLEL_BUILD_GUIDE.md` (the proven SRD-content lane rules — still in
force for spell/monster fan-out).

**Purpose:** run 2–3 concurrent Opus/Sonnet browser instances on the Stages 1–3
plan **without PR conflicts**. Each instance = one branch = one PR. The goal is
that any set of PRs we run in the same cycle touch **disjoint files**, so they
merge in any order with zero conflicts.

---

## 0. The one rule that prevents 90% of conflicts

> **At most ONE instance per cycle may edit a "hot core" file. Every other
> concurrent instance works in *new files only* (new content YAML, new Python
> modules, new per-feature test files).** New files never conflict; distinct
> existing files (separate monster/feat/test files) effectively never conflict.

Wave 1 has a huge reservoir of conflict-free new-file work (every schema, every
content YAML, every new engine module, every test). The only true serialization
point is the handful of hot mutable files below.

Two facts (verified in-repo) make this work:
- **Content is auto-discovered** — `engine/loader.py` globs each entity dir for
  `*.yaml`. Adding content files needs **no registry/index edit**. Fan-out is
  conflict-free as long as each instance owns a distinct entity type.
- **`SESSIONS.md` is a shared append-log** every change conventionally edits.
  That is the #1 hidden conflict magnet → **parallel instances must NOT touch
  it** (see §3).

---

## 1. File-territory map (who may edit what)

| Territory | Files | Rule |
|---|---|---|
| **HOT CORE — build/derivation** | `engine/pc_schema.py`, `engine/loader.py`, `engine/core/rest.py`, `engine/primitives.py` | **≤1 instance at a time** (the multiclass / creation lane). |
| **HOT CORE — scoring/pipeline** | `engine/ai/**` (esp. `ehp_scoring.py`), `engine/core/pipeline.py`, `engine/core/runner.py` | **≤1 instance at a time** (the decision-layer lane). |
| **HOT CORE — class wiring** | `schema/content/classes/c_*.yaml`, `schema/content/subclasses/sc_*.yaml` | Integration lane only, **at merge** (per PARALLEL_BUILD_GUIDE). |
| **SHARED INDEXES / LOGS** | `docs/SESSIONS.md`, `docs/spell-master-list.csv`, `docs/srd/*priority*.csv`, `docs/srd/NEEDS_ENGINE_WORK.md`, `engine/cli.py`, `engine/__init__.py` | Single owner per cycle, or integration lane at merge. **Never** two instances. |
| **NEW SCHEMAS** | `schema/*.schema.json` (background/feat/equipment/magic_item) | New files → free. One instance owns the batch. |
| **NEW CONTENT (per type)** | `schema/content/{equipment,races,feats,backgrounds,magic_items}/*.yaml` | New files → free. **One entity type per instance.** |
| **NEW ENGINE MODULES** | `engine/creation.py`, `engine/manifest.py`, `engine/archive.py`, `engine/resolution.py`, `engine/narrative.py`, etc. | New files → free. One module per instance. **Expose library functions only; defer CLI/`__init__` wiring to integration.** |
| **NEW TESTS** | `tests/test_<feature>.py` | New file per feature → free. Never edit a test you didn't create. |
| **NEW DOCS** | audit outputs, fixtures | New files → free. |

The two HOT-CORE engine territories (build vs scoring) touch **different files**,
so a multiclass lane (`pc_schema.py` + new slot module) and a decision-layer lane
(`ehp_scoring.py` + `pipeline.py`) *can* run concurrently — but that is the
riskiest pairing. Hard split if you do: **`pipeline.py` belongs to the scoring
lane; the build lane never edits it.** If a cycle feels risky, run only one core
lane + new-file lanes.

---

## 2. Conflict-avoidance rules (put these in every prompt)

1. **Stay in your territory.** Your prompt names the files you own. Touch nothing
   else. If you think you need a hot-core edit you weren't assigned, **stop and
   flag it** (NEEDS_ENGINE_WORK or back to the coordinator) — do not edit it.
2. **New files over edits.** Prefer adding a file to editing a shared one. Use the
   data-driven hooks (`pc_builder` etc.) so content needs no `pc_schema` edit.
3. **One entity type per content instance.** If you're building feats, you build
   *only* `feats/ft_*.yaml`; another instance owns `equipment/`. Distinct dirs.
4. **No CLI / `__init__` / SESSIONS / CSV edits in a parallel task.** New modules
   expose functions; the integration lane wires CLI flags, exports, the
   master-list CSV, and the SESSIONS entry **at merge**. Put your session summary
   in your **PR description** instead (an accepted record per `engine-
   capabilities.md`).
5. **Branch per task**, descriptive name (§4). Push; **do not merge to main.**
6. **Suite green before push** — `python -m pytest -q`, zero regressions. Your new
   tests live in their own files.

---

## 3. Why SESSIONS.md is special

The convention (`schema-design.md`) is "every change adds a SESSIONS.md entry."
Under parallelism that guarantees a conflict on every cycle. **Override for
parallel work:** instances do **not** edit `SESSIONS.md`. The integration lane
(or coordinator) writes the batch's SESSIONS entries once, after merge, from the
PR descriptions. Same for the `Status:` date headers on shared docs.

---

## 4. Branch & effort conventions

- **Branch:** `claude/s1-<ws><n>-<slug>` (e.g. `claude/s1-b-multiclass-slots`,
  `claude/s1-f0-narrative-log`, `claude/s1-a-feats-batch1`). One task, one branch.
- **Effort header — first line of every prompt:**
  - `**Effort: Max**` — hot-core engine work, scoring (`ehp_scoring.py`), schema
    *design*, the primitive/module fork, multiclass slot/provenance,
    candidate-generation. Anything where a wrong-but-plausible choice silently
    corrupts results.
  - `**Effort: High**` — new-file fan-out against an established pattern (content
    YAML, per-feature tests), new infra modules that follow a clear spec
    (narrative renderer, manifest, archive writer), audits, docs.

| Task | Territory | Effort |
|---|---|---|
| A0 SRD audit | new doc | High |
| A1 schemas + loader dirs | new `.json` + `loader.py` | Max |
| A2/A3/A5/A8(data)/A9 content | new content YAML (one type each) | High |
| A6 creation rules | new `engine/creation.py` | Max |
| A7 spell selection | `pc_schema.py` + `pipeline.py` | Max |
| A8 item primitives + matrix | scoring/primitives + new modules | Max |
| B1–B7 multiclass | `pc_schema.py` + new slot/rest modules | Max |
| C1–C5 decision layer | `ehp_scoring.py` + `pipeline.py` | Max |
| F0 narrative renderer | new `engine/narrative.py` | High |
| F2 manifest | new `engine/manifest.py` | High |
| F3 archive writer | new `engine/archive.py` | High |
| I1 resolution core | new `engine/resolution.py` | Max |
| I2/I4 demand queue / cohort tags | new modules | High |
| D7 spawn presets | new presets + setup | Max (positioning) |

---

## 5. The cycle model

Work proceeds in **cycles**. Each cycle = a batch of 2–3 tasks **certified
disjoint** by §1. The coordinator emits the prompts for a cycle; you run them;
the integration lane merges them sequentially (suite green each), wires the
shared files, and writes the SESSIONS entries. Then the next cycle is emitted —
adapting to what actually landed, rather than committing to a speculative
schedule.

### Recommended Cycle 1 (3 instances, zero overlap) — the gate + safe infra
A0 gates content fan-out; F0/F2 depend on nothing and touch only new modules.

| Inst | Task | Owns | Effort |
|---|---|---|---|
| 1 | **A0** SRD coverage audit | new `docs/srd/srd-coverage-audit.md` | High |
| 2 | **F0** narrative event-log renderer | new `engine/narrative.py` + test (no CLI) | High |
| 3 | **F2** run manifest | new `engine/manifest.py` + test (no CLI) | High |

### Recommended Cycle 2 (after Cycle 1 merges) — schemas + core start
A1 edits `loader.py` (register new entity dirs) + new `.json`; B edits
`pc_schema.py`. **A1 must keep its builder-dispatch additions in `loader.py` or a
new module — never `pc_schema.py`** — so A1 and B stay disjoint.

| Inst | Task | Owns | Effort |
|---|---|---|---|
| 1 | **A1** new schemas + loader dirs | `schema/*.schema.json`, `engine/loader.py` | Max |
| 2 | **B1+B2** multiclass rules + `classes:` list | `engine/pc_schema.py` | Max |
| 3 | **I1** resolution core | new `engine/resolution.py` | Max |

From Cycle 3 on, content fan-out (A2/A3/A4/A5/A8) opens up (schemas exist,
auto-discovery means no shared edits) and runs 2–3 wide freely; the single core
lane continues B → then A7 → then C, never two-in-one-core-file at once.

---

## 6. Integration-lane checklist (at merge)

1. Merge parallel PRs sequentially; `pytest -q` green after each.
2. Wire the shared files the parallel tasks deferred: `engine/cli.py` flags,
   `engine/__init__.py` exports, class/subclass YAML wiring,
   `docs/spell-master-list.csv` status.
3. Write the batch's `docs/SESSIONS.md` entries from the PR descriptions; bump
   `Status:` dates.
4. Drain `NEEDS_ENGINE_WORK.md` items into the next cycle's core-lane prompts.
