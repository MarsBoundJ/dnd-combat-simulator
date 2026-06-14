"""Character creation & level-up validation (WS-A6).

The **one validator** a PCSpec runs through — the single source of truth the
builder UI and every importer call to answer three *separate* questions about
a build (the §3.1 status triad), each with the reasons it failed:

* **rules_valid**     — is this a legal 2024 character? (ability-score method,
  origin/background application, ability cap, subclass timing, HP mode,
  prepared-spell counts, multiclass prerequisites).
* **content_resolved** — does every referenced id map to a known entity in the
  content registry? (A ref to a not-yet-built ``eq_*`` / ``ft_*`` / ``bg_*``
  is ``content_resolved: false`` — it does **not** make the build illegal.)
* **engine_supported** — is every referenced mechanic actually modeled? A
  legal, resolvable build can still reference an unmodeled subclass/feat/spell;
  that surfaces here as ``engine_supported: false`` ("not yet supported") and
  **fails loud** rather than silently degrading (plan §3.4).

This module is a **pure function over (pc_spec, registry)** — it imports no
engine-core build code, mutates nothing, and is deterministic. Wiring it into
the build flow (``pc_schema``) is a later integration step; here we only
``validate_creation(pc_spec, registry) -> ValidationResult``.

Multiclassing rules are **delegated** to ``engine.core.multiclass`` (the
authoritative WS-B1/B2 module) — we call its ``normalize_classes`` /
``check_prerequisites`` / ``total_level`` rather than duplicating the SRD facts.

SRD provenance (docs/srd/srd-coverage-audit.md §6A, docs/srd/SRD_CC_v5.2.1.pdf):
  * Ability-score methods — Point Buy (27-point; the Ability Score Point Costs
    table), Standard Array (15,14,13,12,10,8), and manual entry.
  * Origin — a background grants +2/+1 (or +1/+1/+1) to its three listed
    abilities plus an Origin feat; ability cap at creation is 20 (post-origin).
  * HP per level — fixed (average) or rolled; L1 = max die + CON mod.
  * Subclass — chosen at class level 3 (uniform across the 2024 classes).

Engine-support convention (forward-compatible): content marks itself unmodeled
with ``engine_supported: false`` or ``not_modeled: true``. Absent a marker an
entity is assumed modeled — the only sound default for a pure validator that
can't introspect the engine. Content authors set the marker when a mechanic
isn't wired (per the NEEDS_ENGINE_WORK convention) so this validator can fail
loud.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from engine.core import multiclass

__all__ = [
    "validate_creation", "ValidationResult", "Check",
    "POINT_BUY_COSTS", "POINT_BUY_BUDGET", "STANDARD_ARRAY",
    "ABILITY_CAP_AT_CREATION", "SUBCLASS_LEVEL", "HP_MODES",
]


# ── SRD constants ───────────────────────────────────────────────────────────

# Ability Score Point Costs table (SRD 5.2.1 / 2024 PHB; identical across
# editions). 27-point budget; base scores 8–15 only.
POINT_BUY_COSTS: dict[int, int] = {8: 0, 9: 1, 10: 2, 11: 3,
                                   12: 4, 13: 5, 14: 7, 15: 9}
POINT_BUY_BUDGET = 27
POINT_BUY_MIN, POINT_BUY_MAX = 8, 15

STANDARD_ARRAY: tuple[int, ...] = (15, 14, 13, 12, 10, 8)

ABILITY_CAP_AT_CREATION = 20
SUBCLASS_LEVEL = 3                      # 2024: every class picks a subclass at L3
HP_MODES = frozenset({"fixed", "average", "rolled"})  # 'fixed'=='average'

_ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
_ABILITY_ALIASES = {
    "str": "str", "strength": "str",
    "dex": "dex", "dexterity": "dex",
    "con": "con", "constitution": "con",
    "int": "int", "intelligence": "int",
    "wis": "wis", "wisdom": "wis",
    "cha": "cha", "charisma": "cha",
}

# Entity `source`/dict markers that say "this mechanic is not wired yet".
_UNSUPPORTED_MARKERS = ("engine_supported", "not_modeled")


# ── Result types (the §3.1 status triad) ────────────────────────────────────

@dataclass(frozen=True)
class Check:
    """One leg of the triad: did it pass, and if not, why."""
    ok: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    """The three independent verdicts on a build, each carrying its reasons.

    A build can satisfy one and fail another (§3.1): e.g. a legal build that
    references an unmodeled subclass is ``rules_valid=True``,
    ``content_resolved=True``, ``engine_supported=False``.
    """
    rules_valid: Check
    content_resolved: Check
    engine_supported: Check

    @property
    def status(self) -> dict[str, bool]:
        """The §3.1 status-triad booleans."""
        return {
            "rules_valid": self.rules_valid.ok,
            "content_resolved": self.content_resolved.ok,
            "engine_supported": self.engine_supported.ok,
        }

    @property
    def ok(self) -> bool:
        """True only when all three legs pass."""
        return (self.rules_valid.ok and self.content_resolved.ok
                and self.engine_supported.ok)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "rules_valid": {"ok": self.rules_valid.ok,
                            "reasons": list(self.rules_valid.reasons)},
            "content_resolved": {"ok": self.content_resolved.ok,
                                 "reasons": list(self.content_resolved.reasons)},
            "engine_supported": {"ok": self.engine_supported.ok,
                                 "reasons": list(self.engine_supported.reasons)},
        }


# ── Registry access (read-only; accepts ContentRegistry or a mapping) ────────

def _lookup(registry: Any, etype: str, eid: Any) -> dict | None:
    if registry is None or eid is None:
        return None
    if hasattr(registry, "all") and hasattr(registry, "count"):
        try:
            return registry.get(etype, eid)        # ContentRegistry.get(type, id)
        except KeyError:
            return None
    if isinstance(registry, Mapping):
        bucket = registry.get(etype) or {}
        return bucket.get(eid)
    return None


def _is_unsupported(entity: Any) -> bool:
    if not isinstance(entity, Mapping):
        return False
    if entity.get("engine_supported") is False:
        return True
    if entity.get("not_modeled") is True:
        return True
    return False


def _resolve(registry, etype, eid, label, content, engine):
    """Resolve one ref: record a content failure if missing, an engine
    failure if present-but-unmodeled. Returns the entity (or None).

    With no registry, resolution is skipped entirely (those legs pass
    vacuously) — a rules-only validation."""
    if eid is None or registry is None:
        return None
    entity = _lookup(registry, etype, eid)
    if entity is None:
        content.append(f"{label} '{eid}' not found in content registry ({etype})")
        return None
    if _is_unsupported(entity):
        engine.append(f"{label} '{eid}' is not yet modeled by the engine")
    return entity


# ── Ability-score helpers ────────────────────────────────────────────────────

def _normalize_abilities(raw: Any, rules: list[str], where: str) -> dict[str, int]:
    """Coerce {label: score} | {label: {score: n}} into {short: int}, flagging
    unknown ability labels."""
    out: dict[str, int] = {}
    if not isinstance(raw, Mapping):
        return out
    for k, v in raw.items():
        key = _ABILITY_ALIASES.get(str(k).lower())
        if key is None:
            rules.append(f"{where}: unknown ability '{k}'")
            continue
        score = v.get("score") if isinstance(v, Mapping) else v
        try:
            out[key] = int(score)
        except (TypeError, ValueError):
            rules.append(f"{where}: ability '{k}' has a non-numeric score {score!r}")
    return out


def _validate_point_buy(base: dict[str, int], rules: list[str]) -> None:
    missing = [ab for ab in _ABILITIES if ab not in base]
    if missing:
        rules.append(f"point_buy: missing abilities {missing}")
    total = 0
    for ab in _ABILITIES:
        if ab not in base:
            continue
        s = base[ab]
        if s < POINT_BUY_MIN or s > POINT_BUY_MAX:
            rules.append(
                f"point_buy: {ab}={s} outside the buyable range "
                f"{POINT_BUY_MIN}-{POINT_BUY_MAX}")
            continue
        total += POINT_BUY_COSTS[s]
    if total > POINT_BUY_BUDGET:
        rules.append(
            f"point_buy: spends {total} points, but the budget is {POINT_BUY_BUDGET}")


def _validate_standard_array(base: dict[str, int], rules: list[str]) -> None:
    if any(ab not in base for ab in _ABILITIES):
        rules.append("standard_array: all six abilities must be assigned")
        return
    got = sorted((base[ab] for ab in _ABILITIES), reverse=True)
    if got != sorted(STANDARD_ARRAY, reverse=True):
        rules.append(
            f"standard_array: {got} is not the standard array "
            f"{list(STANDARD_ARRAY)}")


def _parse_origin_bonuses(pc_spec: dict, rules: list[str]) -> dict[str, int]:
    raw = pc_spec.get("origin_ability_bonuses")
    if raw is None:
        raw = pc_spec.get("ability_bonuses")
    if raw is None:
        return {}
    bonuses = _normalize_abilities(raw, rules, "origin_ability_bonuses")
    if not bonuses:
        return {}
    values = sorted(bonuses.values(), reverse=True)
    # RAW 2024: +2/+1 to two abilities, OR +1/+1/+1 to three.
    is_2_1 = (len(values) == 2 and values == [2, 1])
    is_1_1_1 = (len(values) == 3 and values == [1, 1, 1])
    if not (is_2_1 or is_1_1_1):
        rules.append(
            "origin: background increase must be +2/+1 to two abilities or "
            f"+1 to three abilities, got {bonuses}")
    return bonuses


# ── Per-area rule checks ─────────────────────────────────────────────────────

def _class_level_row(class_entity: Mapping, level: int) -> dict | None:
    for row in class_entity.get("level_table") or []:
        if isinstance(row, Mapping) and row.get("level") == level:
            return row
    return None


def _check_prepared_counts(classes, class_entities, pc_spec, rules) -> None:
    """Per-class prepared/cantrip counts must not exceed the class's allowance
    at its level (2024: prepared counts are per class, by level). Under-fill is
    allowed (a partial loadout); over-fill is illegal."""
    spells = pc_spec.get("spells") or {}
    prepared = spells.get("prepared") or []
    cantrips = spells.get("cantrips") or pc_spec.get("cantrips") or []

    single = classes[0]["class"] if len(classes) == 1 else None
    prepared_by_class: dict[str, int] = {}
    for entry in prepared:
        sc = entry.get("source_class") if isinstance(entry, Mapping) else None
        sc = sc or single
        if sc is not None:
            prepared_by_class[sc] = prepared_by_class.get(sc, 0) + 1

    cantrips_by_class: dict[str, int] = {}
    for entry in cantrips:
        sc = entry.get("source_class") if isinstance(entry, Mapping) else None
        sc = sc or single
        if sc is not None:
            cantrips_by_class[sc] = cantrips_by_class.get(sc, 0) + 1

    for ce in classes:
        cid, level = ce["class"], ce["level"]
        entity = class_entities.get(cid)
        if entity is None:
            continue                                # unresolved → content lane
        row = _class_level_row(entity, level)
        sc_block = (row or {}).get("spellcasting") or {}
        allowed_prep = sc_block.get("prepared_spells")
        have_prep = prepared_by_class.get(cid, 0)
        if allowed_prep is None and have_prep:
            rules.append(
                f"{cid}: declares {have_prep} prepared spell(s) but is not a "
                f"preparing caster at level {level}")
        elif isinstance(allowed_prep, int) and have_prep > allowed_prep:
            rules.append(
                f"{cid}: {have_prep} prepared spells exceeds the {allowed_prep} "
                f"allowed at level {level}")
        allowed_cantrips = sc_block.get("cantrips_known")
        have_cantrips = cantrips_by_class.get(cid, 0)
        if isinstance(allowed_cantrips, int) and have_cantrips > allowed_cantrips:
            rules.append(
                f"{cid}: {have_cantrips} cantrips exceeds the {allowed_cantrips} "
                f"known at level {level}")


def _check_feats(pc_spec, registry, total, final_scores, content, engine, rules) -> None:
    feats = pc_spec.get("feats") or []
    for fid in feats:
        feat = _resolve(registry, "feat", fid, "feat", content, engine)
        if feat is None:
            continue
        category = feat.get("category")
        if category == "epic_boon" and total < 19:
            rules.append(f"feat '{fid}': epic boons require level 19+ (have {total})")
        prereq = feat.get("prerequisites") or {}
        min_level = prereq.get("min_level")
        if isinstance(min_level, int) and total < min_level:
            rules.append(
                f"feat '{fid}': requires level {min_level} (have {total})")
        ability_reqs = prereq.get("ability_scores") or []
        if ability_reqs:
            all_required = bool(prereq.get("ability_scores_all_required"))
            checks = []
            for req in ability_reqs:
                ab = _ABILITY_ALIASES.get(str(req.get("ability", "")).lower())
                need = req.get("min")
                checks.append(ab is not None and isinstance(need, int)
                              and final_scores.get(ab, 0) >= need)
            satisfied = all(checks) if all_required else any(checks)
            if checks and not satisfied:
                rules.append(
                    f"feat '{fid}': ability-score prerequisite not met")


def _check_equipment(pc_spec, registry, content, engine) -> None:
    """Resolve equipment / magic-item refs. Missing eq_*/mi_* ids are a
    content gap (not a rules failure) — they're authored in later cycles."""
    equip = pc_spec.get("equipment") or {}
    armor = equip.get("armor")
    if isinstance(armor, str):
        _resolve(registry, "equipment", armor, "armor", content, engine)
    for w in equip.get("weapons") or []:
        wid = w.get("item") if isinstance(w, Mapping) else w
        _resolve(registry, "equipment", wid, "weapon", content, engine)
    off = equip.get("off_hand_weapon")
    if isinstance(off, str):
        _resolve(registry, "equipment", off, "off-hand weapon", content, engine)
    for mid in pc_spec.get("magic_items") or []:
        _resolve(registry, "magic_item", mid, "magic item", content, engine)


# ── The validator ────────────────────────────────────────────────────────────

def validate_creation(pc_spec: dict, registry: Any = None) -> ValidationResult:
    """Validate a PCSpec for legal creation, content resolution, and engine
    support. Pure function; never mutates ``pc_spec`` or ``registry``.

    ``registry`` may be a ``ContentRegistry`` (public ``get``/``all``/``count``)
    or a plain ``{type: {id: entity}}`` mapping. When ``None``, content and
    engine resolution are skipped (those legs pass vacuously) and only the rules
    are checked.
    """
    rules: list[str] = []
    content: list[str] = []
    engine: list[str] = []

    if not isinstance(pc_spec, Mapping):
        return ValidationResult(
            Check(False, ("pc_spec must be a mapping",)),
            Check(True), Check(True))

    # 1. Class structure (delegated normalization + total-level bounds).
    classes: list[dict] = []
    total = 0
    try:
        classes = multiclass.normalize_classes(dict(pc_spec))
        total = multiclass.total_level(classes)
    except ValueError as e:
        rules.append(str(e))

    # 2. Ability scores — generation method + cap.
    method = pc_spec.get("ability_method") or pc_spec.get("ability_score_method")
    base = _normalize_abilities(
        pc_spec.get("base_ability_scores") or pc_spec.get("ability_scores"),
        rules, "ability_scores")
    declared = _normalize_abilities(
        pc_spec.get("ability_scores"), rules, "ability_scores")
    origin_bonuses = _parse_origin_bonuses(pc_spec, rules)

    if method == "point_buy":
        _validate_point_buy(base, rules)
    elif method == "standard_array":
        _validate_standard_array(base, rules)
    elif method == "manual":
        pass                                        # trusted entry; cap still checked
    elif method is not None:
        rules.append(
            f"ability_method '{method}' is not one of point_buy / "
            f"standard_array / manual")

    # Final scores = base + origin increases (when both are known).
    final_scores = dict(declared or base)
    if origin_bonuses and (pc_spec.get("base_ability_scores") or not declared):
        final_scores = {ab: base.get(ab, 0) + origin_bonuses.get(ab, 0)
                        for ab in set(base) | set(origin_bonuses)}

    # 3. Ability cap at creation (post-origin): 20.
    for ab, score in final_scores.items():
        if score > ABILITY_CAP_AT_CREATION:
            rules.append(
                f"ability {ab}={score} exceeds the creation cap of "
                f"{ABILITY_CAP_AT_CREATION}")

    # 4. Origin / background.
    bg_id = pc_spec.get("background")
    bg = _resolve(registry, "background", bg_id, "background", content, engine)
    if bg is not None and origin_bonuses:
        choices = set()
        for label in ((bg.get("ability_scores") or {}).get("choices") or []):
            short = _ABILITY_ALIASES.get(str(label).lower())
            if short:
                choices.add(short)
        off = [ab for ab in origin_bonuses if ab not in choices]
        if choices and off:
            rules.append(
                f"origin: background '{bg_id}' increases {sorted(choices)} but "
                f"the spec raises {off}")

    # 5. HP mode.
    hp_mode = (pc_spec.get("level_up") or {}).get("hp_mode") or pc_spec.get("hp_mode")
    if hp_mode is not None and hp_mode not in HP_MODES:
        rules.append(
            f"hp_mode '{hp_mode}' is not one of {sorted(HP_MODES)}")

    # 6. Per-class checks (subclass timing) + content/engine resolution.
    class_entities: dict[str, dict] = {}
    for ce in classes:
        cid, level, subclass = ce["class"], ce["level"], ce.get("subclass")
        class_entities[cid] = _resolve(
            registry, "class", cid, "class", content, engine)
        if subclass is not None:
            _resolve(registry, "subclass", subclass, "subclass", content, engine)
            if level < SUBCLASS_LEVEL:
                rules.append(
                    f"{cid}: subclass '{subclass}' chosen at level {level}, but "
                    f"a subclass is chosen at level {SUBCLASS_LEVEL}")
        elif level >= SUBCLASS_LEVEL:
            rules.append(
                f"{cid}: level {level} requires a subclass (chosen at level "
                f"{SUBCLASS_LEVEL})")

    # 7. Multiclass prerequisites (delegated). Only a multiclass build's
    #    classes carry an ability-score prerequisite (SRD p24).
    if multiclass.is_multiclass(classes):
        failures = multiclass.check_prerequisites(
            [ce["class"] for ce in classes], final_scores)
        rules.extend(failures)

    # 8. Prepared-spell counts per class.
    if classes:
        _check_prepared_counts(classes, class_entities, pc_spec, rules)

    # 9. Feats (resolution, engine support, prerequisites).
    _check_feats(pc_spec, registry, total, final_scores, content, engine, rules)

    # 10. Species + spells + equipment resolution (content/engine only).
    _resolve(registry, "race", pc_spec.get("species") or pc_spec.get("race"),
             "species", content, engine)
    spells = pc_spec.get("spells") or {}
    for bucket in ("prepared", "known", "cantrips"):
        for entry in spells.get(bucket) or []:
            sid = entry.get("id") if isinstance(entry, Mapping) else entry
            _resolve(registry, "spell", sid, "spell", content, engine)
    _check_equipment(pc_spec, registry, content, engine)

    return ValidationResult(
        rules_valid=Check(not rules, tuple(rules)),
        content_resolved=Check(not content, tuple(content)),
        engine_supported=Check(not engine, tuple(engine)),
    )
