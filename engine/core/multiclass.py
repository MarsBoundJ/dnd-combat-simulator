"""Multiclassing rules — encoded as data + pure functions (WS-B1/B2).

This module is the **single authoritative source** for the SRD 5.2.1
multiclassing rules the rest of the engine consumes. It is deliberately
self-contained data (no registry dependency for the SRD facts) so the oracle
tests can pin its values against the printed book without any build wiring.

Provenance — everything here is transcribed DIRECTLY from
`docs/srd/SRD_CC_v5.2.1.pdf`:
  * Multiclassing rules text — pages 24-25.
  * Multiclass Spellcaster: Spell Slots per Spell Level table — page 26.
  * Per-class Primary Ability + Hit Point Die — each class's "Core <Class>
    Traits" block (pages 28-78).

Scope of THIS file (B1 + B2 support only):
  * B1 — the rules AS DATA + validation: the spellcaster table (exact),
    prerequisites, PB-by-total-level, HP-across-hit-dice, Extra-Attack
    non-stacking, one-AC-feature-at-a-time, and the combined-caster-level
    formula with its half-caster rounding. Locked by tests/test_multiclass_rules.py.
  * B2 support — `normalize_classes` (the ordered `classes:` spec) and the
    derivations build_pc_template needs (total level, PB, HP, prereq check).

NOT in scope here (later cycles, do not add): the spell-slot POOL ALLOCATION
onto a PC (B4 consumes `multiclass_spell_slots` — this file only provides it as
locked data), Pact-Magic interop (B5), the full oracle suite (B7).

────────────────────────────────────────────────────────────────────────────
THE HALF-CASTER ROUNDING — the §9 G#1 BLOCKER, resolved against the book
────────────────────────────────────────────────────────────────────────────
SRD 5.2.1 page 25, "Spellcasting → Spell Slots", verbatim:

    You determine your available spell slots by adding together the following:
      • All your levels in the Bard, Cleric, Druid, Sorcerer, and Wizard classes
      • Half your levels (round up) in the Paladin and Ranger classes

So the contribution is **round UP** for Paladin/Ranger — `ceil(level / 2)`.
This is the 2024 rule and it is the printed SRD text, NOT a prose summary.

Two independent locks against the book (see tests/test_multiclass_rules.py):
  1. The SRD's OWN worked example (page 25-26): "a level 4 Ranger / level 3
     Sorcerer … count as a level 5 character … four level 1 spell slots, three
     level 2 slots, and two level 3 slots" → combined level 5 → table row 5 =
     (4, 3, 2). `combined_caster_level` reproduces 5; `multiclass_spell_slots`
     reproduces (4,3,2).
  2. The discriminating case the plan named — **Paladin 1 / Sorcerer 1**:
       round-UP   → ceil(1/2)=1 + 1 = combined level 2 → 3 first-level slots
       round-down → floor(1/2)=0 + 1 = combined level 1 → 2 first-level slots
     We assert the round-UP result (combined level 2), pinning the direction.

Historical note (do NOT use): the 2014 PHB rounded these DOWN. The plan's §9
flagged that G#1's worked example was internally garbled; this module follows
the printed SRD 5.2.1 table+text, oracle-tested, and ignores any prose memory.
"""
from __future__ import annotations

import math
from typing import Iterable


# ───────────────────────────────────────────────────────────────────────────
# SRD 5.2.1 page 26 — Multiclass Spellcaster: Spell Slots per Spell Level.
# Keyed by combined caster level (1-20) → 9-tuple of slot counts for spell
# levels 1..9 (a printed "—" is 0). Transcribed cell-for-cell from the PDF.
# ───────────────────────────────────────────────────────────────────────────
MULTICLASS_SPELL_SLOTS: dict[int, tuple[int, ...]] = {
    1:  (2, 0, 0, 0, 0, 0, 0, 0, 0),
    2:  (3, 0, 0, 0, 0, 0, 0, 0, 0),
    3:  (4, 2, 0, 0, 0, 0, 0, 0, 0),
    4:  (4, 3, 0, 0, 0, 0, 0, 0, 0),
    5:  (4, 3, 2, 0, 0, 0, 0, 0, 0),
    6:  (4, 3, 3, 0, 0, 0, 0, 0, 0),
    7:  (4, 3, 3, 1, 0, 0, 0, 0, 0),
    8:  (4, 3, 3, 2, 0, 0, 0, 0, 0),
    9:  (4, 3, 3, 3, 1, 0, 0, 0, 0),
    10: (4, 3, 3, 3, 2, 0, 0, 0, 0),
    11: (4, 3, 3, 3, 2, 1, 0, 0, 0),
    12: (4, 3, 3, 3, 2, 1, 0, 0, 0),
    13: (4, 3, 3, 3, 2, 1, 1, 0, 0),
    14: (4, 3, 3, 3, 2, 1, 1, 0, 0),
    15: (4, 3, 3, 3, 2, 1, 1, 1, 0),
    16: (4, 3, 3, 3, 2, 1, 1, 1, 0),
    17: (4, 3, 3, 3, 2, 1, 1, 1, 1),
    18: (4, 3, 3, 3, 3, 1, 1, 1, 1),
    19: (4, 3, 3, 3, 3, 2, 1, 1, 1),
    20: (4, 3, 3, 3, 3, 2, 2, 1, 1),
}


# ───────────────────────────────────────────────────────────────────────────
# Per-class SRD facts (class ids use the engine's `c_<name>` convention).
# Hit dice + caster type + primary-ability prerequisites, all read off each
# class's "Core <Class> Traits" block in the SRD (pages 28-78).
# ───────────────────────────────────────────────────────────────────────────

# Spellcasting contribution to the SHARED multiclass slot pool:
#   "full"  → counts its full level   (Bard, Cleric, Druid, Sorcerer, Wizard)
#   "half"  → counts ceil(level / 2)  (Paladin, Ranger)
#   "pact"  → 0 to the shared pool — Warlock Pact Magic is a SEPARATE pool
#             (B5); it does not feed the Multiclass Spellcaster table.
#   "none"  → 0                       (Barbarian, Fighter, Monk, Rogue)
# NOTE: the third-caster subclasses (Eldritch Knight, Arcane Trickster) make
# their base class contribute ceil(level/3); that is a SUBCLASS nuance handled
# in a later cycle — base Fighter/Rogue are "none" here.
CASTER_TYPE: dict[str, str] = {
    "c_bard": "full", "c_cleric": "full", "c_druid": "full",
    "c_sorcerer": "full", "c_wizard": "full",
    "c_paladin": "half", "c_ranger": "half",
    "c_warlock": "pact",
    "c_barbarian": "none", "c_fighter": "none", "c_monk": "none",
    "c_rogue": "none",
}

# Hit Point Die per class — SRD "Core <Class> Traits → Hit Point Die" (int).
HIT_DICE: dict[str, int] = {
    "c_barbarian": 12,
    "c_fighter": 10, "c_paladin": 10, "c_ranger": 10,
    "c_bard": 8, "c_cleric": 8, "c_druid": 8, "c_monk": 8,
    "c_rogue": 8, "c_warlock": 8,
    "c_sorcerer": 6, "c_wizard": 6,
}

# Multiclass prerequisite — SRD page 24: "a score of at least 13 in the primary
# ability of the new class and your current classes." Each class's requirement
# is a list of CLAUSES; every clause must be met, and a clause is met if ANY of
# its abilities is >= 13. Single-ability classes have one one-ability clause;
# "X or Y" classes (Fighter) have one two-ability clause (either satisfies);
# "X and Y" classes (Monk/Paladin/Ranger) have two one-ability clauses (both
# required). Transcribed from each class's printed "Primary Ability":
#   Barbarian Strength · Bard Charisma · Cleric Wisdom · Druid Wisdom ·
#   Fighter Strength OR Dexterity · Monk Dexterity AND Wisdom ·
#   Paladin Strength AND Charisma · Ranger Dexterity AND Wisdom ·
#   Rogue Dexterity · Sorcerer Charisma · Warlock Charisma · Wizard Intelligence
PREREQUISITES: dict[str, tuple[tuple[str, ...], ...]] = {
    "c_barbarian": (("str",),),
    "c_bard": (("cha",),),
    "c_cleric": (("wis",),),
    "c_druid": (("wis",),),
    "c_fighter": (("str", "dex"),),          # STR or DEX
    "c_monk": (("dex",), ("wis",)),          # DEX and WIS
    "c_paladin": (("str",), ("cha",)),       # STR and CHA
    "c_ranger": (("dex",), ("wis",)),        # DEX and WIS
    "c_rogue": (("dex",),),
    "c_sorcerer": (("cha",),),
    "c_warlock": (("cha",),),
    "c_wizard": (("int",),),
}

PREREQUISITE_SCORE = 13


# ───────────────────────────────────────────────────────────────────────────
# Proficiency Bonus by TOTAL character level (SRD Character Advancement table).
# ───────────────────────────────────────────────────────────────────────────

def proficiency_bonus(total_level: int) -> int:
    """PB from TOTAL character level (SRD: PB is by total level, never per
    class). +2 (1-4), +3 (5-8), +4 (9-12), +5 (13-16), +6 (17-20)."""
    if total_level < 1:
        raise ValueError(f"total_level must be >= 1, got {total_level}")
    return 2 + (min(total_level, 20) - 1) // 4


# ───────────────────────────────────────────────────────────────────────────
# Spell-slot combined level + table lookup (DATA for B4; not allocated here).
# ───────────────────────────────────────────────────────────────────────────

def spell_slot_contribution(class_id: str, level: int) -> int:
    """This class/level's contribution to the SHARED multiclass caster level.

    full → level; half (Paladin/Ranger) → ceil(level/2) [SRD round-UP, see the
    module header]; pact (Warlock) and none → 0. Unknown class → 0."""
    caster = CASTER_TYPE.get(class_id, "none")
    if caster == "full":
        return int(level)
    if caster == "half":
        return math.ceil(int(level) / 2)     # SRD 5.2.1 p25: "round up"
    return 0                                   # pact / none


def combined_caster_level(classes: Iterable[tuple[str, int]]) -> int:
    """Sum each class's `spell_slot_contribution` → the level to look up in
    the Multiclass Spellcaster table. `classes` is an iterable of
    (class_id, class_level)."""
    return sum(spell_slot_contribution(cid, lvl) for cid, lvl in classes)


def multiclass_spell_slots(classes: Iterable[tuple[str, int]]) -> dict[int, int]:
    """The SHARED Spellcasting slot pool for a multiclass set, as
    {spell_level: count} for non-zero levels. LOCKED DATA for B4 to allocate
    onto a PC — this module does NOT stamp it onto any template (that is the
    B4 allocation step). Combined level 0 (no Spellcasting classes) → {}."""
    combined = combined_caster_level(classes)
    if combined < 1:
        return {}
    row = MULTICLASS_SPELL_SLOTS[min(combined, 20)]
    return {sl + 1: n for sl, n in enumerate(row) if n > 0}


# ───────────────────────────────────────────────────────────────────────────
# Prerequisites (SRD page 24).
# ───────────────────────────────────────────────────────────────────────────

def _score_of(ability_scores: dict, ability: str) -> int:
    """Read a raw ability score from either the compact {str: 15} shape or the
    resolved {str: {score: 15}} shape. Missing → 0."""
    v = ability_scores.get(ability)
    if isinstance(v, dict):
        return int(v.get("score", 0))
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def class_prerequisite_met(class_id: str, ability_scores: dict) -> bool:
    """True if `ability_scores` satisfies `class_id`'s multiclass prerequisite
    (>= 13 in the printed primary ability; ALL clauses, ANY ability per
    clause). Unknown class → True (no prereq data → don't block)."""
    clauses = PREREQUISITES.get(class_id)
    if not clauses:
        return True
    for clause in clauses:
        if not any(_score_of(ability_scores, ab) >= PREREQUISITE_SCORE
                   for ab in clause):
            return False
    return True


def check_prerequisites(class_ids: Iterable[str],
                        ability_scores: dict) -> list[str]:
    """SRD: to qualify you need >= 13 in the primary ability of the new class
    AND your current classes — i.e. EVERY class in a multiclass build must have
    its prerequisite met. Returns a list of human-readable failures (empty =
    all met). The initial class of a SINGLE-class character has no ability-score
    prerequisite, so callers should only invoke this for multiclass builds."""
    failures: list[str] = []
    for cid in class_ids:
        if not class_prerequisite_met(cid, ability_scores):
            clauses = PREREQUISITES.get(cid, ())
            need = " and ".join(
                "/".join(a.upper() for a in clause) for clause in clauses)
            failures.append(
                f"{cid}: requires {PREREQUISITE_SCORE}+ in {need}")
    return failures


# ───────────────────────────────────────────────────────────────────────────
# Hit Points across hit dice (SRD page 25).
# ───────────────────────────────────────────────────────────────────────────

def _avg_per_level(die: int) -> int:
    """5e fixed average per level for a die of `die` sides: die//2 + 1
    (d12=7, d10=6, d8=5, d6=4) — matches engine.pc_schema._compute_hp."""
    return die // 2 + 1


def multiclass_hit_points(classes: list[tuple[str, int]], con_mod: int) -> int:
    """Total HP across all hit dice (SRD p25).

    RAW: "You gain the level 1 Hit Points for a class only when your total
    character level is 1." So EXACTLY ONE level in the whole character — the
    first class's first level — uses the max die; every other class-level
    (the first class's levels 2+, and all levels of later classes) uses the
    fixed average. CON modifier applies to every level.

    `classes` is the ORDERED list of (class_id, level); the first entry is the
    initial class. Single-class input reproduces pc_schema._compute_hp exactly.
    """
    total = 0
    first_level_taken = False
    for class_id, level in classes:
        die = HIT_DICE.get(class_id)
        if die is None:
            raise ValueError(f"unknown class for hit die: {class_id!r}")
        avg = _avg_per_level(die)
        for _ in range(int(level)):
            if not first_level_taken:
                total += die + con_mod          # the single character-L1 max
                first_level_taken = True
            else:
                total += avg + con_mod
    return max(1, total)


def hit_dice_pool(classes: list[tuple[str, int]]) -> dict[int, int]:
    """The Hit Dice pool by die size (SRD p25: same die types pool together,
    different types track separately). {die_sides: count}. e.g. Fighter5/
    Paladin5 → {10: 10}; Cleric5/Paladin5 → {8: 5, 10: 5}."""
    pool: dict[int, int] = {}
    for class_id, level in classes:
        die = HIT_DICE.get(class_id)
        if die is None:
            raise ValueError(f"unknown class for hit die: {class_id!r}")
        pool[die] = pool.get(die, 0) + int(level)
    return pool


def hit_dice_string(classes: list[tuple[str, int]]) -> str:
    """Cosmetic dice expression for the pooled Hit Dice, e.g. '2d10+3d6'
    (descending die size for stable ordering)."""
    pool = hit_dice_pool(classes)
    return "+".join(f"{pool[d]}d{d}" for d in sorted(pool, reverse=True))


# ───────────────────────────────────────────────────────────────────────────
# Extra Attack non-stacking (SRD page 25).
# ───────────────────────────────────────────────────────────────────────────

# Feature ids that grant the baseline Extra Attack (one extra = two attacks).
# These do NOT stack with each other across classes (SRD: "If you gain the
# Extra Attack feature from more than one class, the features don't stack…").
# The Warlock Thirsting Blade invocation is included per the SRD's explicit
# call-out that it likewise doesn't add attacks.
_BASELINE_EXTRA_ATTACK_FEATURES = frozenset({
    "f_extra_attack",            # Fighter/Paladin/Ranger/Barbarian/Monk shared id
    "f_monk_extra_attack",
    "f_thirsting_blade",         # Warlock invocation — explicitly non-stacking
})
# Features that RAISE the attack ceiling beyond two (only the Fighter's higher
# tiers do this). Mapped to the total attacks they grant.
_EXTRA_ATTACK_CEILING_FEATURES = {
    "f_extra_attack_two": 3,     # Fighter L11 "Two Extra Attacks"
    "f_extra_attack_three": 4,   # Fighter L20 "Three Extra Attacks"
}


def extra_attack_total(features: Iterable[str]) -> int:
    """Total attacks the Attack action grants given a feature set, applying the
    SRD non-stacking rule: any baseline Extra Attack → 2 (never more from
    stacking multiple classes); only the Fighter's "Two/Three Extra Attacks"
    raise the ceiling to 3/4. No Extra-Attack feature → 1."""
    feats = set(features)
    ceiling = max((n for f, n in _EXTRA_ATTACK_CEILING_FEATURES.items()
                   if f in feats), default=0)
    baseline = 2 if (feats & _BASELINE_EXTRA_ATTACK_FEATURES) else 1
    return max(baseline, ceiling)


# ───────────────────────────────────────────────────────────────────────────
# Alternative AC calculation — one at a time (SRD page 25).
# ───────────────────────────────────────────────────────────────────────────

def choose_ac_calculation(candidates: Iterable[int]) -> int:
    """SRD: "If you have multiple ways to calculate your Armor Class, you can
    benefit from only one at a time." Given the candidate AC values from each
    applicable feature/armor, return the single best (highest). Empty → 10
    (the unarmored 10 + DEX baseline is handled by the caller; this is a
    defensive floor)."""
    vals = list(candidates)
    return max(vals) if vals else 10


# ───────────────────────────────────────────────────────────────────────────
# The `classes:` spec (B2) — ordered list, with class/level sugar.
# ───────────────────────────────────────────────────────────────────────────

def normalize_classes(pc_spec: dict) -> list[dict]:
    """Normalize a PC spec's class declaration into an ORDERED list of
    `{"class": <id>, "level": <int>, "subclass": <id or None>}`.

    Accepts either:
      * the multiclass form `classes: [{class, level, subclass?}, ...]`
        (order = order the classes were taken; first entry is the initial
        class that drives saving throws / L1 hit die / armor training), OR
      * the single-class sugar `class: <id>` + `level: <int>` (+ optional
        `subclass:`), which normalizes to a one-entry list.

    Validation (SRD-faithful): exactly one form may be present; each level is
    an int >= 1; total level is in [1, 20]; no class appears twice.
    """
    has_classes = "classes" in pc_spec and pc_spec["classes"] is not None
    has_sugar = pc_spec.get("class") is not None

    if has_classes and has_sugar:
        raise ValueError(
            "pc spec declares both `classes:` and `class:` — use one. "
            "`class:`+`level:` is single-class sugar for a one-entry `classes:`.")

    if not has_classes:
        if not has_sugar:
            raise ValueError("pc spec missing required field: class (or classes)")
        entries = [{"class": pc_spec.get("class"),
                    "level": pc_spec.get("level", 1),
                    "subclass": pc_spec.get("subclass")}]
    else:
        raw = pc_spec["classes"]
        if not isinstance(raw, list) or not raw:
            raise ValueError("pc spec `classes:` must be a non-empty list")
        entries = []
        for i, e in enumerate(raw):
            if not isinstance(e, dict) or not e.get("class"):
                raise ValueError(
                    f"pc spec `classes`[{i}] must be a dict with a `class` field")
            entries.append({"class": e["class"],
                            "level": e.get("level", 1),
                            "subclass": e.get("subclass")})

    out: list[dict] = []
    seen: set[str] = set()
    total = 0
    for e in entries:
        cid = e["class"]
        try:
            lvl = int(e["level"])
        except (TypeError, ValueError):
            raise ValueError(f"class {cid!r} has a non-integer level: {e['level']!r}")
        if lvl < 1:
            raise ValueError(f"class {cid!r} level must be >= 1, got {lvl}")
        if cid in seen:
            raise ValueError(f"class {cid!r} appears more than once in `classes`")
        seen.add(cid)
        total += lvl
        out.append({"class": cid, "level": lvl, "subclass": e.get("subclass")})

    if total < 1 or total > 20:
        raise ValueError(f"total character level must be in [1, 20], got {total}")
    return out


def total_level(classes: list[dict]) -> int:
    """Sum of class levels = total character level."""
    return sum(int(e["level"]) for e in classes)


def is_multiclass(classes: list[dict]) -> bool:
    return len(classes) > 1
