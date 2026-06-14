"""Content resolution & provenance core (WS-I1).

The shared mechanism that turns a **raw reference** — a human string from
an importer (a sheet's "Fire Bolt", "Eye Tyrant", "  greatsword ") plus an
entity type — into a **canonical internal id**, or into a *structured
non-resolution* the fix-up flow / demand queue can route (see
``docs/stages-1-3-plan.md`` §3.3, §3.4). Four problems converge on this
one subsystem: import resolution, the public monster-rename map (I3), the
demand-driven currency backlog (I2), and homebrew cohort tagging — so the
result is deliberately explicit rather than a bare ``str | None``.

This module is **standalone and read-only**: it consumes the loaded
``ContentRegistry`` through its public ``count()`` / ``all()`` surface (or
a plain ``{type: {id: entity}}`` mapping) and never mutates it. It imports
nothing from the engine core.

Key concepts
------------
* **Ambiguity class** (``MatchClass``): every resolution is exactly one of
  ``exact`` / ``aliased`` / ``ambiguous`` / ``unmapped`` (§3.4).
* **Alias table**: curated ``canonical-id ↔ accepted-aliases`` mappings.
  Ships **empty** — the rename map (I3) and the demand queue (I2) populate
  it later. Aliases are authoritative curated decisions, so an alias hit
  beats a fuzzy name match.
* **Provenance**: a resolved id carries the entity's ``source`` enum
  (``srd_5.2.1`` / ``phb_2024`` / ``mm_2024`` / ``user_authored`` /
  ``homebrew``) so analytics never pool non-comparable cohorts (§3.4 #4).
* **Fail loud, never silently coerce** (§3.3): an unknown or ambiguous
  reference returns a ``Resolution`` carrying a machine-readable
  ``reason``; it is never guessed into a wrong id.

Public API
----------
    normalize_ref(s) -> str
    resolve(raw_ref, entity_type, registry, alias_table=None) -> Resolution
    class Resolution            # the structured result
    class MatchClass            # exact | aliased | ambiguous | unmapped
    class AliasTable            # curated alias store (starts empty)
    class ContentResolver       # reusable resolver bound to a registry
    REVIEW_REASONS              # the stable set of review-reason strings
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

__all__ = [
    "MatchClass", "Resolution", "AliasTable", "ContentResolver",
    "resolve", "normalize_ref", "REVIEW_REASONS", "SOURCE_ENUM",
]


# The entity `source` enum (mirrors the values stamped by the content
# pipeline — see docs/stages-1-3-plan.md §1). Kept here as a read-only
# reference; this module does not own or validate the enum.
SOURCE_ENUM = frozenset({
    "srd_5.2.1", "phb_2024", "mm_2024", "user_authored", "homebrew",
})

# Stable machine-readable review reasons (the structured non-resolution
# payload the fix-up flow / demand queue key on). Stable strings, not
# free text, so downstream code can branch on them.
REVIEW_REASONS = frozenset({
    "empty_reference",          # raw_ref was empty / whitespace only
    "unknown_entity_type",      # the registry has no such entity type
    "no_match",                 # nothing matched (-> demand queue)
    "ambiguous_name",           # >1 entity shares the normalized name
    "alias_target_not_loaded",  # alias resolved to an id absent from the registry
})


class MatchClass(str, Enum):
    """How a reference resolved (the ambiguity class, §3.4)."""
    EXACT = "exact"          # matched a canonical id, or a unique entity name
    ALIASED = "aliased"      # matched via the curated alias table
    AMBIGUOUS = "ambiguous"  # matched >1 candidate — needs disambiguation
    UNMAPPED = "unmapped"    # no match — routes to the demand queue


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_NON_WORD = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+", flags=re.UNICODE)


def normalize_ref(s: Any) -> str:
    """Canonical comparison form for a reference or name.

    Unicode-normalizes (NFKD), case-folds, treats ``_`` and ``-`` as
    spaces, drops punctuation (apostrophes, periods, plus, commas …) and
    collapses runs of whitespace. So ``"  Fire_Bolt "``, ``"fire bolt"``
    and ``"FIRE-BOLT"`` all normalize to ``"fire bolt"``; ``"Beholder's"``
    -> ``"beholders"``.
    """
    text = unicodedata.normalize("NFKD", str(s))
    text = text.casefold()
    text = text.replace("_", " ").replace("-", " ")
    text = _NON_WORD.sub("", text)
    text = _WS.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Resolution:
    """The structured outcome of one resolution attempt.

    A resolved result (``exact`` / ``aliased``) carries ``resolved_id``;
    consumers gate ``engine_supported`` on ``in_registry`` and pool
    analytics by ``source``. A non-resolution (``ambiguous`` / ``unmapped``)
    carries a ``reason`` and any ``candidates`` for the fix-up flow.
    """
    raw_ref: str
    entity_type: str
    match_class: MatchClass
    normalized: str
    resolved_id: str | None = None
    in_registry: bool = False        # is resolved_id an actually-loaded entity?
    source: str | None = None        # the resolved entity's `source` enum
    candidates: tuple[str, ...] = ()  # disambiguation choices (ambiguous)
    reason: str | None = None        # a REVIEW_REASONS value when attention is needed

    @property
    def resolved(self) -> bool:
        """True when a single canonical id was determined (exact/aliased).

        Note: an aliased id may still be ``in_registry == False`` (the
        mapping is known but the content isn't loaded) — that is a
        ``content_resolved`` success but an ``engine_supported`` gap, so
        callers that need a live entity must also check ``in_registry``.
        """
        return self.match_class in (MatchClass.EXACT, MatchClass.ALIASED) \
            and self.resolved_id is not None


# ---------------------------------------------------------------------------
# Alias table
# ---------------------------------------------------------------------------

class AliasTable:
    """Curated ``canonical-id ↔ aliases`` store, per entity type.

    Starts **empty**. The public rename map (I3, e.g. "Eye Tyrant" ->
    ``m_beholder``) and the demand queue (I2) add entries later. Aliases
    are stored in normalized form, so lookups are case/whitespace
    insensitive; an alias added twice for different ids raises (curated
    data must be unambiguous).
    """

    def __init__(self) -> None:
        # entity_type -> {normalized_alias: canonical_id}
        self._by_type: dict[str, dict[str, str]] = {}

    def add_alias(self, entity_type: str, alias: str, canonical_id: str) -> None:
        norm = normalize_ref(alias)
        if not norm:
            raise ValueError("alias normalizes to empty string")
        bucket = self._by_type.setdefault(entity_type, {})
        existing = bucket.get(norm)
        if existing is not None and existing != canonical_id:
            raise ValueError(
                f"alias {alias!r} ({entity_type}) already maps to "
                f"{existing!r}, cannot remap to {canonical_id!r}"
            )
        bucket[norm] = canonical_id

    def add(self, entity_type: str, canonical_id: str, aliases) -> None:
        """Register one canonical id with one or more aliases."""
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            self.add_alias(entity_type, alias, canonical_id)

    def get(self, entity_type: str, ref: str) -> str | None:
        """Canonical id for a (possibly un-normalized) reference, or None."""
        return self._by_type.get(entity_type, {}).get(normalize_ref(ref))

    def aliases_for(self, entity_type: str, canonical_id: str) -> list[str]:
        return sorted(a for a, cid in self._by_type.get(entity_type, {}).items()
                      if cid == canonical_id)

    def __len__(self) -> int:
        return sum(len(b) for b in self._by_type.values())

    @classmethod
    def from_id_aliases(cls, data: Mapping[str, Mapping[str, Any]]) -> "AliasTable":
        """Build from ``{entity_type: {canonical_id: [alias, ...]}}`` — the
        natural shape of an id-keyed rename map (I3)."""
        table = cls()
        for entity_type, id_map in data.items():
            for canonical_id, aliases in id_map.items():
                table.add(entity_type, canonical_id, aliases)
        return table


# ---------------------------------------------------------------------------
# Registry adapter (read-only)
# ---------------------------------------------------------------------------

def _entities_of_type(registry: Any, entity_type: str) -> dict | None:
    """Return ``{id: entity}`` for a type, or ``None`` if the registry has
    no such type. Accepts a ``ContentRegistry`` (public count()/all()) or a
    plain ``{type: {id: entity}}`` mapping. Read-only."""
    if hasattr(registry, "count") and hasattr(registry, "all"):
        if entity_type not in registry.count():
            return None
        return registry.all(entity_type)
    if isinstance(registry, Mapping):
        if entity_type not in registry:
            return None
        return dict(registry[entity_type])
    raise TypeError(
        "registry must be a ContentRegistry or a {type: {id: entity}} "
        f"mapping, got {type(registry).__name__!r}"
    )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class ContentResolver:
    """Resolve raw references against a registry + an optional alias table.

    Build one per (registry, alias_table) and call ``resolve`` repeatedly;
    per-type name indexes are built lazily and cached, so resolving many
    references over the same content is cheap.
    """

    def __init__(self, registry: Any, alias_table: AliasTable | None = None) -> None:
        self.registry = registry
        self.alias_table = alias_table or AliasTable()
        # entity_type -> {normalized_name: [id, ...]}
        self._name_index: dict[str, dict[str, list[str]]] = {}
        # entity_type -> {normalized_id: id} (for id-form references)
        self._id_index: dict[str, dict[str, str]] = {}

    # -- index building -----------------------------------------------------

    def _ensure_indexed(self, entity_type: str, entities: dict) -> None:
        if entity_type in self._name_index:
            return
        names: dict[str, list[str]] = {}
        ids: dict[str, str] = {}
        for eid, entity in entities.items():
            ids.setdefault(normalize_ref(eid), eid)
            name = entity.get("name") if isinstance(entity, Mapping) else None
            if name:
                names.setdefault(normalize_ref(name), []).append(eid)
        # Deterministic candidate order.
        for key in names:
            names[key].sort()
        self._name_index[entity_type] = names
        self._id_index[entity_type] = ids

    # -- helpers ------------------------------------------------------------

    def _source_of(self, entities: dict, entity_id: str) -> str | None:
        entity = entities.get(entity_id)
        if isinstance(entity, Mapping):
            return entity.get("source")
        return None

    def _result(self, raw_ref, entity_type, match_class, normalized, **kw):
        return Resolution(raw_ref=raw_ref, entity_type=entity_type,
                          match_class=match_class, normalized=normalized, **kw)

    # -- the entry point ----------------------------------------------------

    def resolve(self, raw_ref: str, entity_type: str) -> Resolution:
        normalized = normalize_ref(raw_ref)

        if not normalized:
            return self._result(raw_ref, entity_type, MatchClass.UNMAPPED, "",
                                reason="empty_reference")

        entities = _entities_of_type(self.registry, entity_type)
        if entities is None:
            return self._result(raw_ref, entity_type, MatchClass.UNMAPPED,
                                normalized, reason="unknown_entity_type")

        self._ensure_indexed(entity_type, entities)

        # 1. Exact canonical-id hit (raw string is literally an id).
        if raw_ref in entities:
            return self._result(
                raw_ref, entity_type, MatchClass.EXACT, normalized,
                resolved_id=raw_ref, in_registry=True,
                source=self._source_of(entities, raw_ref))

        # 2. Curated alias hit (authoritative — beats fuzzy name matching).
        alias_target = self.alias_table.get(entity_type, normalized)
        if alias_target is not None:
            in_reg = alias_target in entities
            return self._result(
                raw_ref, entity_type, MatchClass.ALIASED, normalized,
                resolved_id=alias_target, in_registry=in_reg,
                source=self._source_of(entities, alias_target) if in_reg else None,
                reason=None if in_reg else "alias_target_not_loaded")

        # 3. Normalized id hit (id passed in a different case / separators).
        id_hit = self._id_index[entity_type].get(normalized)
        if id_hit is not None:
            return self._result(
                raw_ref, entity_type, MatchClass.EXACT, normalized,
                resolved_id=id_hit, in_registry=True,
                source=self._source_of(entities, id_hit))

        # 4. Name match — unique => exact, several => ambiguous.
        name_hits = self._name_index[entity_type].get(normalized, [])
        if len(name_hits) == 1:
            hit = name_hits[0]
            return self._result(
                raw_ref, entity_type, MatchClass.EXACT, normalized,
                resolved_id=hit, in_registry=True,
                source=self._source_of(entities, hit))
        if len(name_hits) > 1:
            return self._result(
                raw_ref, entity_type, MatchClass.AMBIGUOUS, normalized,
                candidates=tuple(name_hits), reason="ambiguous_name")

        # 5. Nothing matched — structured non-resolution for the demand queue.
        return self._result(raw_ref, entity_type, MatchClass.UNMAPPED,
                            normalized, reason="no_match")


def resolve(raw_ref: str, entity_type: str, registry: Any,
            alias_table: AliasTable | None = None) -> Resolution:
    """One-shot convenience wrapper around :class:`ContentResolver`.

    For repeated resolution over the same content, build a
    ``ContentResolver`` once (it caches per-type indexes) instead of
    calling this per reference.
    """
    return ContentResolver(registry, alias_table).resolve(raw_ref, entity_type)
