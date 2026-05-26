# Browser Deployment Option (Pyodide / WebAssembly)

**Status:** 🟡 Documented option — build deferred to Stage 2 timing
**Last updated:** 2026-05-25

This document captures Pyodide / PyScript as a viable **zero-cost
deployment target** for the simulator. The engine's existing architecture
already enables it; this doc records *why*, *where it fits*, *what we
preserve to keep the option open*, and *what we'd build when the time
comes*.

---

## The option

Pyodide compiles CPython to WebAssembly. A pure-Python engine compiled to
WASM runs **entirely in the user's browser**, with $0 hosting cost
(static HTML + JS + WASM bundle served from GitHub Pages, Firebase free
tier, or any CDN). The user's own laptop / phone CPU does the work.

For this project specifically:

- **Single encounter run**: ~50-85ms in Pyodide (CPython baseline ~17ms;
  Pyodide is ~3-5× slower). Instant UX for "click and watch."
- **Monte Carlo 1k runs**: ~1-2 minutes browser-side. Acceptable with a
  progress bar; offload to a Web Worker so the page stays responsive.
- **Monte Carlo 10k+ runs**: too slow for browser. Stays on Phil's
  laptop or a backend runner.

---

## Why this engine is unusually Pyodide-friendly

The architectural invariants we adopted for **Foundry** integration also
make Pyodide trivial. Path-independence paying off.

| Pyodide requires… | Status in this engine |
|---|---|
| Pure Python, no C extensions | ✅ PyYAML + jsonschema both ship in Pyodide; no native deps |
| No threading / multiprocessing / async | ✅ Engine is fully synchronous |
| Deterministic seeded RNG | ✅ `random.Random(seed)` — identical behavior under Pyodide |
| Plain-data state (JSON-serializable) | ✅ `engine/core/state.py` explicit design commitment — see file docstring |
| Library-first API (no `__main__` coupling) | ✅ `EncounterRunner`, `load_content` importable; CLI is one thin consumer |
| Filesystem-independence | 🟡 Loader reads from disk via `pathlib`. Small ergonomic add (string-content sibling) is the only gap. |

---

## Where this fits the 4-stage plan

| Stage | Existing plan | Pyodide's role |
|---|---|---|
| **1: Internal grading** | CLI on local machine | Unchanged |
| **2: Published reports** | PDFs / markdown writeups | **New option:** every report links to a "click to re-run this encounter in your browser" companion demo. URL params encode `fixture_id + seed` → reproducible by anyone, no install, no signup. |
| **3: Foundry community tool** | Foundry VTT module via native JS bridge | Unchanged. Foundry stays the answer for "use this during a real session" — Pyodide would add ~10MB to Foundry world load, less efficient than the JS bridge for in-VTT use. |
| **4: AI-DM** | Long-term | Unchanged |

**Pyodide is a third deployment target, not a replacement** for either
the CLI or the Foundry bridge. Specifically, it's the **Stage 2
report-companion layer** — the "try it yourself" CTA on a written piece.

---

## Invariants to preserve (already followed; don't regress)

These are existing design choices. Listing them explicitly so any future
PR that would break the option gets caught in review.

1. **No native C-extension dependencies.** Every new dependency check
   should include "does Pyodide ship it?" PyYAML ✓, jsonschema ✓.
   If we ever need numpy / scipy for stats analysis, Pyodide ships those
   too. Avoid `cython`, `numba`, pip packages with mandatory C builds.

2. **Loader supports string content (when we build it).** Right now
   `engine/loader.py:load_yaml_file` reads from disk. For Pyodide we want
   a `load_yaml_string` sibling that takes raw YAML text. Small
   ergonomic addition; not blocking until we actually need it.

3. **`engine/cli.py` stays a thin wrapper.** The library API is the
   surface; the CLI is one consumer, Foundry will be a second, and a
   Pyodide-driven JS frontend would be a third. Decision logic does not
   migrate into the CLI module.

4. **`engine/core/state.py` plain-data invariant stays sacred.** The
   existing file-docstring commitment ("every state object is plain
   Python data ... full JSON serialization") is precisely the
   Pyodide-enabler. No closures, no Python-object-specific state, no
   callbacks-as-state.

5. **Synchronous execution only.** No threading or asyncio in engine
   modules. (Foundry bridge may use `async/await` at the JS layer; the
   Python engine stays sync.)

---

## What we'd build when the time comes

Rough scope estimate, **~1-3 days of work** at Stage 2 timing:

1. **`engine/loader.py:load_yaml_string`** — sibling to `load_yaml_file`
   that takes raw text. Tiny.

2. **Static frontend** (`web/index.html` + `web/app.js` + Pyodide CDN
   include):
   - Fixture picker / paste-your-own YAML textarea
   - Seed input
   - "Run" button → calls Pyodide → gets back JSON event log
   - Combat log renderer (the existing event_log dicts are already
     UI-friendly: `event`, `actor`, `target`, `amount`, etc.)
   - Optional: encode `fixture_id + seed` in URL params for shareable
     reproducible links

3. **Web Worker for heavier MC** — keep the page responsive when running
   100+ encounters. Pyodide-in-worker is well-documented.

4. **Deploy to GitHub Pages or Firebase free tier** — static files, no
   server-side compute. Custom domain optional.

5. **A "Run in browser" link** added to each Stage 2 published report
   that points at the demo with the report's specific fixture pre-loaded.

**What stays out of scope for the Pyodide build:**
- Heavy Monte Carlo at scale (still backend)
- Validation-oracle / Trusight integration pipelines (still backend)
- Persistent storage (browser localStorage only if needed for "save your
  fixture")
- User accounts / collaboration features (Stage 3+ Foundry path handles
  this differently)

---

## Trigger conditions

The Pyodide build is a **Stage 2 task**. Reasonable triggers to start it:

- First Stage 2 published report is drafted and ready for distribution,
  and a "click to re-run" affordance would meaningfully strengthen it
- A community member asks "how can I try this without installing Python?"
- We want to share a specific encounter result via URL during outreach /
  pitch conversations

Until one of those fires, this stays a documented option, not a task.

---

## Related docs

- `docs/architecture/engine-design.md` — overall library-first architecture
- `docs/architecture/foundry-integration.md` — the Stage 3 deployment path
- `docs/architecture/schema-design.md` — schema as the lingua franca
  across deployment targets
- `engine/core/state.py` (module docstring) — the plain-data invariant
- `engine/core/runner.py` — sim-mode vs observation-mode design (same
  observation-mode pattern Foundry uses applies to any external driver,
  including a JS frontend)
