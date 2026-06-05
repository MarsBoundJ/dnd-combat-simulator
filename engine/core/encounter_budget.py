"""2024 DMG combat-encounter XP budgeting.

The 2024 model ("Combat Encounter Difficulty", DMG 2024) — NOT the 2014 one:

  - Three difficulty tiers: **Low / Moderate / High**.
  - XP budget = (per-character value at the party's level, by tier)
    × number of characters.
  - Spend the budget by summing each monster's **raw** stat-block XP. There
    is **no encounter multiplier** — the 2014 ×1.5..×2.5 scaling for monster
    count is gone. A qualitative "Many Creatures" advisory applies instead at
    **more than two monsters per character**.
  - There is **no daily XP budget** in 2024 (the 6-8 encounter adventuring-day
    XP accounting was dropped). Attrition across encounters is still a real
    play dynamic, but the 2024 rules put no XP number on a "day" — so anything
    that needs an encounters-per-rest count must treat it as an explicit
    modeling assumption, not a RAW figure.

XP values are read from monster stat blocks (`template['cr']['xp']`), which
are 2024 SRD numbers — cross-checked against the DMG's own worked examples
(Adult Red Dragon = 18,000 XP; Fire Giant = 5,000 XP).
"""
from __future__ import annotations

from typing import Iterable

# The three 2024 difficulty tiers, low → high.
DIFFICULTIES: tuple[str, ...] = ("low", "moderate", "high")

# DMG 2024 "XP Budget per Character" — party level → (low, moderate, high)
# XP PER CHARACTER. Multiply by party size for the encounter budget.
XP_BUDGET_PER_CHARACTER: dict[int, tuple[int, int, int]] = {
    1:  (50,    75,    100),
    2:  (100,   150,   200),
    3:  (150,   225,   400),
    4:  (250,   375,   500),
    5:  (500,   750,   1100),
    6:  (600,   1000,  1400),
    7:  (750,   1300,  1700),
    8:  (1000,  1700,  2100),
    9:  (1300,  2000,  2600),
    10: (1600,  2300,  3100),
    11: (1900,  2900,  4100),
    12: (2200,  3700,  4700),
    13: (2600,  4200,  5400),
    14: (2900,  4900,  6200),
    15: (3300,  5400,  7800),
    16: (3800,  6100,  9800),
    17: (4500,  7200,  11700),
    18: (5000,  8700,  14200),
    19: (5500,  10700, 17200),
    20: (6400,  13200, 22000),
}


def xp_budget(party_level: int, party_size: int, difficulty: str) -> int:
    """XP budget for an encounter of `difficulty` for `party_size` characters
    of level `party_level`, per the DMG 2024 table.

    budget = per-character value × party size.
    """
    diff = difficulty.lower()
    if diff not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}, "
                         f"got {difficulty!r}")
    if party_level not in XP_BUDGET_PER_CHARACTER:
        raise ValueError(f"party_level must be 1..20, got {party_level}")
    if party_size <= 0:
        raise ValueError(f"party_size must be positive, got {party_size}")
    per_char = XP_BUDGET_PER_CHARACTER[party_level][DIFFICULTIES.index(diff)]
    return per_char * party_size


def budgets_for(party_level: int, party_size: int) -> dict[str, int]:
    """All three tier budgets for the party, as a {tier: xp} dict."""
    return {d: xp_budget(party_level, party_size, d) for d in DIFFICULTIES}


def monster_xp(monster) -> int:
    """Raw stat-block XP for a monster — accepts a loaded template dict OR an
    Actor (reads `.template`). 0 if absent (e.g. CR-0 / unscored)."""
    template = getattr(monster, "template", monster)
    cr = (template.get("cr") or {}) if isinstance(template, dict) else {}
    return int(cr.get("xp", 0) or 0)


def encounter_cost(monsters: Iterable) -> int:
    """Total spent XP for an encounter = SUM of each monster's raw stat-block
    XP. No 2014-style multiplier for monster count (2024 dropped it)."""
    return sum(monster_xp(m) for m in monsters)


def many_creatures(monster_count: int, party_size: int) -> bool:
    """DMG 2024 "Many Creatures" advisory: more than two monsters per
    character raises the lucky-streak risk (the soft replacement for the
    deleted encounter multiplier). True when count > 2 × party size."""
    return monster_count > 2 * party_size


def classify_difficulty(spent_xp: int, party_level: int,
                         party_size: int) -> str:
    """Classify an encounter's difficulty from its spent XP.

    The tier budget is the CEILING for that tier (DMG "spend as much as you
    can without going over"), so an encounter is classified at the LOWEST
    tier whose budget it fits within:

      spent == 0                    -> "none"
      spent <= low budget           -> "low"
      spent <= moderate budget      -> "moderate"
      spent <= high budget          -> "high"
      spent  > high budget          -> "above_high"   (harder than High)

    e.g. 18,000 XP (solo Adult Red Dragon) for 4×L13: low=10,400,
    moderate=16,800, high=21,600 → exceeds Moderate's ceiling, fits under
    High's → "high" (with headroom). So the climax is a textbook RAW High
    encounter, not over-budget.
    """
    if spent_xp <= 0:
        return "none"
    b = budgets_for(party_level, party_size)
    if spent_xp <= b["low"]:
        return "low"
    if spent_xp <= b["moderate"]:
        return "moderate"
    if spent_xp <= b["high"]:
        return "high"
    return "above_high"


def encounter_report(monsters: list, party_level: int,
                     party_size: int) -> dict:
    """A full budget read-out for an encounter — spent XP, the three tier
    budgets, the classified difficulty, headroom under the High ceiling, and
    the many-creatures advisory. Intended for harness labeling / sim output.
    """
    spent = encounter_cost(monsters)
    b = budgets_for(party_level, party_size)
    return {
        "spent_xp": spent,
        "budgets": b,
        "difficulty": classify_difficulty(spent, party_level, party_size),
        "high_headroom": b["high"] - spent,
        "monster_count": len(monsters),
        "many_creatures": many_creatures(len(monsters), party_size),
    }
