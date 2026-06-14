"""Run manifest — reproducibility by construction (WS-F2).

A **manifest** is the identity of a run's *inputs*: capture it and you can
reproduce the run, and two runs that share a manifest are the "same
thing" (the precondition the archive's cohort aggregation keys on — see
``docs/stages-1-3-plan.md`` §3.6). It records:

* **engine version** — the git SHA (+ a dirty flag, because uncommitted
  changes mean the SHA alone does not pin the code);
* **content-bundle hash** — a deterministic hash of the loaded content
  set, so a data change is detectable even at the same SHA;
* **rule bundle** — RAW / Common-Table / Strict (forward-compat: not yet
  implemented; ``None`` == today's engine-default behavior);
* **seed** and the **run parameters** (optimization dials, day pacing);
* a **full encounter-spec snapshot** — the declarative spec that produced
  the run (PCSpec ``pc:`` blocks, positions, environment), or, failing
  that, a structural snapshot derived from the built ``Encounter``.

This module is **library only** — no CLI / archive wiring (the
``--archive`` stamping is a later integration-lane step per
``docs/stages-1-3-execution.md`` §1) and it imports nothing from the
engine core: it reads plain data and does read-only attribute access on
an ``Encounter`` / ``ContentRegistry``. Deterministic by design — the
manifest carries **no wall-clock timestamp**, so identical inputs yield
an identical (and identically hashable) manifest.

Design choices worth knowing:

* **Why prefer ``encounter_spec`` over the ``Encounter`` object.** A PC's
  built template does *not* retain its original ``pc:`` spec (it is
  expanded into a stat block at build time), so the declarative spec is
  the only compact, faithful PCSpec record. When only an ``Encounter`` is
  available the snapshot embeds each actor's *full template* instead, so
  a built PC (whose template is not in the content registry) is still
  reproducible — bulkier, but lossless.
* **Forward-compat fields are present now, populated later.** RoomSpec
  (WS-D), the rule bundle (WS-I) and per-actor behavior profiles do not
  fully exist in Wave 1; their keys exist with ``None`` defaults and a
  comment so downstream code and the schema are stable from v1.

Public API:
    build_manifest(*, seed, content_registry=None, encounter_spec=None,
                   encounter=None, optimization_dials=None,
                   encounters_remaining_today=3, rule_bundle=None,
                   room_spec=None, behavior_profiles=None,
                   engine_sha=None, repo_root=None) -> dict
    content_hash(content) -> str            # "sha256:<hex>"
    manifest_id(manifest) -> str            # cohort key: hash of the manifest
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

__all__ = ["MANIFEST_VERSION", "build_manifest", "content_hash", "manifest_id"]

# Bump when the manifest *shape* changes in a way that breaks consumers.
MANIFEST_VERSION = 1


# ---------------------------------------------------------------------------
# Canonical serialization (the basis of every deterministic hash here)
# ---------------------------------------------------------------------------

def _canonical_bytes(obj: Any) -> bytes:
    """Deterministic JSON encoding: sorted keys, no incidental whitespace,
    ``default=str`` so the rare non-JSON scalar (e.g. a tuple position
    that slipped through) still encodes stably rather than raising."""
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Content-bundle hash
# ---------------------------------------------------------------------------

def _as_content_mapping(content: Any) -> Mapping[str, Mapping[str, dict]]:
    """Normalize a ``ContentRegistry`` (or a plain ``{type: {id: entity}}``
    mapping) into a uniform nested mapping for hashing.

    Uses the registry's public ``count()`` / ``all()`` surface so we don't
    reach into private state."""
    if hasattr(content, "count") and hasattr(content, "all"):
        return {etype: content.all(etype) for etype in content.count()}
    if isinstance(content, Mapping):
        return content
    raise TypeError(
        "content_hash expects a ContentRegistry or a {type: {id: entity}} "
        f"mapping, got {type(content).__name__!r}"
    )


def content_hash(content: Any) -> str:
    """Deterministic SHA-256 over the loaded content set.

    The hash is independent of load order and dict iteration order: entity
    types and ids are walked sorted, each entity canonically serialized.
    Adding, removing or editing any entity changes the hash; reloading the
    same content does not.
    """
    mapping = _as_content_mapping(content)
    h = hashlib.sha256()
    for etype in sorted(mapping):
        entities = mapping[etype]
        for eid in sorted(entities):
            h.update(etype.encode("utf-8"))
            h.update(b"\x00")
            h.update(str(eid).encode("utf-8"))
            h.update(b"\x00")
            h.update(_canonical_bytes(entities[eid]))
            h.update(b"\x00")
    return "sha256:" + h.hexdigest()


def _content_counts(content: Any) -> dict | None:
    if hasattr(content, "count"):
        try:
            return dict(content.count())
        except Exception:
            return None
    if isinstance(content, Mapping):
        return {etype: len(items) for etype, items in content.items()}
    return None


# ---------------------------------------------------------------------------
# Engine version (git)
# ---------------------------------------------------------------------------

def _repo_root_default() -> Path:
    # engine/manifest.py -> repo root is one level up from engine/.
    return Path(__file__).resolve().parent.parent


def _git(args: list[str], repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(repo_root),
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _detect_engine_version(repo_root: Path) -> dict:
    """Best-effort git identity. Outside a checkout (e.g. a Pyodide
    bundle) both fields are ``None`` — pass ``engine_sha`` explicitly
    there. ``git_dirty=True`` flags a working tree with uncommitted
    changes (the run is *not* reproducible from the SHA alone)."""
    sha = _git(["rev-parse", "HEAD"], repo_root)
    dirty: bool | None = None
    porcelain = _git(["status", "--porcelain"], repo_root)
    if porcelain is not None:
        dirty = bool(porcelain.strip())
    return {"git_sha": sha, "git_dirty": dirty}


# ---------------------------------------------------------------------------
# Encounter-spec snapshot
# ---------------------------------------------------------------------------

def _snapshot_initial_distances(distances: Any) -> list | None:
    """``Encounter.initial_distances`` is keyed by ``(id1, id2)`` tuples,
    which JSON can't represent — flatten to a sorted list of records."""
    if not distances:
        return None
    records = []
    for pair, ft in distances.items():
        if isinstance(pair, (tuple, list)) and len(pair) == 2:
            records.append({"pair": [str(pair[0]), str(pair[1])], "ft": ft})
        else:
            records.append({"pair": [str(pair)], "ft": ft})
    records.sort(key=lambda r: r["pair"])
    return records


def _snapshot_actor_from_object(actor: Any) -> dict:
    """Structural, reproducible snapshot of a built ``Actor``.

    Embeds the full template: a built PC's template is not in the content
    registry and its source ``pc:`` spec is not retained, so the template
    is the only lossless record of that combatant."""
    template = getattr(actor, "template", None)
    template = template if isinstance(template, dict) else {}
    position = getattr(actor, "position", None)
    return {
        "instance_id": getattr(actor, "id", None),
        "name": getattr(actor, "name", None),
        "side": getattr(actor, "side", None),
        "source": template.get("source"),
        "template_id": template.get("id"),
        "position": list(position) if isinstance(position, (tuple, list)) else position,
        "elevation": getattr(actor, "elevation", None),
        "hp_max": getattr(actor, "hp_max", None),
        "ac": getattr(actor, "ac", None),
        "abilities": getattr(actor, "abilities", None),
        "spell_slots": dict(getattr(actor, "spell_slots", {}) or {}),
        "spell_slots_max": dict(getattr(actor, "spell_slots_max", {}) or {}),
        "resources": dict(getattr(actor, "resources", {}) or {}),
        # Full stat block — lossless reproduction, esp. for built PCs.
        "template": template,
    }


def _snapshot_encounter(encounter_spec: Any, encounter: Any) -> dict:
    """Prefer the declarative spec (the true PCSpec/RoomSpec source);
    fall back to deriving a snapshot from the built ``Encounter``."""
    if encounter_spec is not None:
        spec = copy.deepcopy(encounter_spec)
        return {
            "snapshot_source": "declarative_spec",
            "id": spec.get("id") if isinstance(spec, dict) else None,
            # The declarative spec carries actors (with `pc:` blocks /
            # template_refs), environment and any distance overrides as-is.
            "spec": spec,
        }
    if encounter is not None:
        actors = getattr(encounter, "actors", []) or []
        return {
            "snapshot_source": "encounter_object",
            "id": getattr(encounter, "id", None),
            "actors": [_snapshot_actor_from_object(a) for a in actors],
            "environment": copy.deepcopy(getattr(encounter, "environment", {}) or {}),
            "initial_distances": _snapshot_initial_distances(
                getattr(encounter, "initial_distances", None)),
        }
    return {"snapshot_source": None}


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------

def build_manifest(
    *,
    seed: int | None,
    content_registry: Any = None,
    encounter_spec: Mapping | None = None,
    encounter: Any = None,
    optimization_dials: Mapping | None = None,
    encounters_remaining_today: int = 3,
    rule_bundle: str | None = None,
    room_spec: Mapping | None = None,
    behavior_profiles: Mapping | None = None,
    engine_sha: str | None = None,
    repo_root: Path | str | None = None,
) -> dict:
    """Build a reproducibility manifest for one run.

    Parameters
    ----------
    seed:
        The RNG seed the run was (or will be) executed with.
    content_registry:
        The loaded ``ContentRegistry`` (or a ``{type: {id: entity}}``
        mapping). Used for the content hash + counts. ``None`` leaves the
        content section's ``hash`` as ``None``.
    encounter_spec:
        The *declarative* encounter spec dict (``{"actors": [...],
        "environment": {...}, ...}``) — the preferred snapshot source
        because it carries the original ``pc:`` PCSpec blocks.
    encounter:
        A built ``Encounter`` object; used to derive the snapshot only
        when ``encounter_spec`` is not given.
    optimization_dials, encounters_remaining_today:
        The run-parameter dials (``EncounterRunner.run`` arguments).
    rule_bundle, room_spec, behavior_profiles:
        Forward-compat inputs (see module docstring). Captured verbatim
        when supplied; ``None`` otherwise.
    engine_sha:
        Override the engine git SHA (pass this in environments without a
        git checkout, e.g. Pyodide). When ``None`` the SHA is detected
        from ``repo_root``.
    repo_root:
        Where to run git for SHA/dirty detection (defaults to the repo
        containing this file).

    Returns
    -------
    dict
        A JSON-serializable, deterministic manifest with
        ``manifest_version == MANIFEST_VERSION``.
    """
    root = Path(repo_root) if repo_root is not None else _repo_root_default()

    if engine_sha is not None:
        engine = {"git_sha": engine_sha, "git_dirty": None}
    else:
        engine = _detect_engine_version(root)

    content_section: dict = {"hash": None, "counts": None}
    if content_registry is not None:
        content_section["hash"] = content_hash(content_registry)
        content_section["counts"] = _content_counts(content_registry)

    dials = {str(k): v for k, v in (optimization_dials or {}).items()}

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "engine": engine,
        "content": content_section,
        "rules": {
            # Forward-compat (WS-I): one of "RAW" | "Common-Table" |
            # "Strict". None == today's engine-default (RAW) behavior;
            # the rule-bundle system is not implemented in Wave 1.
            "rule_bundle": rule_bundle,
        },
        "run_params": {
            "seed": seed,
            "optimization_dials": dials,
            "encounters_remaining_today": encounters_remaining_today,
            # Forward-compat: per-actor / per-side behavior knobs beyond
            # the optimization dial. No behavior-profile system in Wave 1.
            "behavior_profiles": (copy.deepcopy(behavior_profiles)
                                  if behavior_profiles is not None else None),
        },
        "encounter": _snapshot_encounter(encounter_spec, encounter),
        # Forward-compat (WS-D): the RoomGeometry/TacticalAnnotations
        # RoomSpec. Until WS-D lands, environment lives in the encounter
        # snapshot; this top-level key is reserved so the schema is stable.
        "room_spec": (copy.deepcopy(room_spec) if room_spec is not None else None),
    }
    return manifest


def manifest_id(manifest: Mapping) -> str:
    """Stable cohort key for a manifest: a SHA-256 over its canonical
    form. Two manifests with the same inputs share an id; any captured
    difference (SHA, content hash, seed, spec, dials) changes it."""
    return _sha256(_canonical_bytes(manifest))
