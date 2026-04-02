# Treantmonk 2024 Damage Rankings — Complete Summary

**Source:** Treantmonk's Temple — 2024 PHB DPS Series (Videos 19–23 of 23)  
**Playlist:** https://youtube.com/playlist?list=PLfdtR0ufZC9eElP2Dv68kRj0yJIP1QtbU  
**Status:** ✅ Complete — all tier breakdowns extracted  
**Last updated:** 2026-03-30  
**Used by:** `engine/math/pc_dpr.py`, `docs/foundations/pc-dpr-baselines.md`

---

## Purpose

This document encodes Treantmonk's weighted overall damage scores and per-tier
breakdowns for every build analyzed across the 2024 series. These are the primary
reference for the simulator's class/subclass power ranking system.

**Career scores** are weighted aggregates across all 20 levels.
**Tier scores** are simple averages within each tier's level range.
**Per-level DPR curves** live in `pc-dpr-baselines.md`.

---

## The Scoring Formula (Fully Verified)

```python
def calc_career_score(t1_avg: float, t2_avg: float,
                      t3_avg: float, t4_avg: float) -> float:
    """
    Treantmonk's weighted career damage score.
    Weights: T1×1, T2×3, T3×2, T4×1
    Reflects that T2 and T3 see the most campaign play.
    """
    return (t1_avg * 1) + (t2_avg * 3) + (t3_avg * 2) + (t4_avg * 1)

# Verified against known endpoints:
# Berserker Greatsword: 15*1 + 43*3 + 57*2 + 71*1 = 15+129+114+71 = 329 ✅
# Bard Base Spells:      6*1 + 15*3 + 27*2 + 35*1 =  6+ 45+ 54+35 = 140 ✅
```

**Tier level ranges:**
- Tier 1: Levels 1–4 (simple average)
- Tier 2: Levels 5–10 (simple average)
- Tier 3: Levels 11–16 (simple average)
- Tier 4: Levels 17–20 (simple average)

---

## The 2024 Baseline — CRITICAL ENGINE REFERENCE

### Retired: 2014 Warlock Baseline
**Build:** Warlock EB + Agonizing Blast + Hex
**Status:** D tier at all four tiers of 2024 play. Retired.
**Reason:** "Eldritch Blast Warlocks just aren't in the game anymore as far
as single target damage."

### New: 2024 Warlock Blade Pact Greatsword Baseline
**Build:** Warlock Base Blade Pact Greatsword (no subclass)
**Rationale:** Only build achieving C tier in all four tiers — represents
"okay but not great" damage consistently across a full career.

```python
TREANTMONK_2024_BASELINE = {
    "build":        "Warlock Base Blade Pact Greatsword",
    "description":  "C tier at all four tiers. Minimum okay damage benchmark.",
    "tier_scores":  {1: 8, 2: 24, 3: 37, 4: 59},
    "career_score": 196,   # 8*1 + 24*3 + 37*2 + 59*1
    "per_level_dpr": {level: None for level in range(1, 21)},
}
```

**Engine policy:** Any PC build scoring below this baseline at a given tier
is considered below-average single-target DPS. Used as the floor for
"contributing damage" in encounter simulations.

---

## Tier Thresholds

| | T1 (L1–4) | T2 (L5–10) | T3 (L11–16) | T4 (L17–20) |
|---|---|---|---|---|
| **A** | 13–15 | 37–43 | ~50+ | 70+ |
| **B** | 10–12 | 29–36 | ~40–49 | 60–69 |
| **C** | 7–9 | 22–28 | ~35–49 | 50–59 |
| **D** | 4–6 | 15–21 | 26–34 | 35–49 |

*T3 thresholds inferred — not explicitly stated. Lowest: 26, Highest: 57.*

---

## Classes Not Analyzed

Treantmonk did not cover **Wizard** or **Cleric**:
- Neither would rank near the top for single-target DPR
- Spellcasting well-represented by Bard, Druid, Warlock, Sorcerer data

**Engine proxy:** Sorcerer Base Blast as closest proxy for Wizard/Cleric DPR.

---

## ⚠️ Balance Outlier: Conjure Minor Elementals

Excluded from all calculations. Upcasted with multiple attacks (e.g. College
of Valor at T3) produces ~80 DPR — "way above everything else."

**Engine policy:** Flag as outlier requiring DM override toggle.
See `docs/domain/conditions-and-edge-cases.md`.

---

## Career Scores — All 39 Builds

### D Tier (Score < 175)

| Score | Build | Type |
|---|---|---|
| 140 | Bard Base Spells | Base |
| 162 | Warlock Base True Strike Shillelagh | Base |
| 163 | Druid Base Spells | Base |
| 166 | Warlock Base Eldritch Blast | Base |
| 167 | Fighter Base Longsword | Base |
| 168 | Ranger Base HM + Hail of Thorns Longbow | Base |

### C Tier (Score 175–225)

| Score | Build | Type | Notes |
|---|---|---|---|
| 185 | College of Valor True Strike Greatsword | Optimized | Lowest optimized |
| 185 | Ranger Base Hunter's Mark TWF | Base | Tied with optimized Bard |
| 189 | Battle Master Longsword | Optimized | |
| 191 | Ranger Base Summoner TWF | Base | |
| 194 | Rogue Base Dagger Thrower | Base | |
| 203 | Archfey Patron Eldritch Blast | Optimized | |
| 203 | Beastmaster Longbow | Optimized | Tied |
| 213 | Celestial Patron True Strike Shillelagh | Optimized | 4-way tie |
| 213 | Paladin Base Greatsword | Base | 4-way tie |
| 213 | Rogue Base Light Crossbow True Strike | Base | 4-way tie |
| 213 | **Warlock Base Blade Pact Greatsword** | Base | **2024 Baseline** |
| 214 | Sorcerer Base Blast Spells | Base | Highest pure-spell base |
| 218 | Fey Wanderer Summoner TWF | Optimized | Best Ranger build |
| 219 | Monk Base | Base | Strong no-subclass showing |
| 224 | Zealot Barbarian Longsword | Optimized | Strong T1–T2, falls T3–T4 |

### B Tier (Score 226–275)

| Score | Build | Type | Notes |
|---|---|---|---|
| 232 | Draconic Sorcerer Blast | Optimized | Highest pure-spell career |
| 232 | Oath of Vengeance Paladin Longsword | Optimized | Tied |
| 235 | Barbarian Base Greatsword | Base | 2nd highest base build |
| 235 | Circle of Moon Druid | Optimized | Tied. Exceptional at T4 |
| 238 | Fighter Base Greatsword | Base | Highest base build overall |
| 245 | Assassin Heavy Crossbow | Optimized | Highest ranged career |
| 250 | Fiend Patron Greatsword (Cha) | Optimized | |
| 251 | Eldritch Knight True Strike Shillelagh | Optimized | Slow burn |
| 256 | Berserker Barbarian Longsword | Optimized | |
| 260 | Eldritch Knight Greatsword | Optimized | |
| 264 | Fiend Patron Greatsword (Str) | Optimized | |
| 274 | Champion Shillelagh | Optimized | Tied for top of B |
| 274 | Samurai Greatsword | Optimized | Tied for top of B |

### A Tier (Score > 275)

| Score | Build | Type | Notes |
|---|---|---|---|
| 293 | Zealot Barbarian Greatsword | Optimized | T2 dominant |
| 294 | Oath of Vengeance Paladin TWF (Dex) | Optimized | Highest TWF build |
| 298 | Warrior of Shadow Monk | Optimized | Darkness advantage |
| 305 | Oath of Vengeance Paladin Greatsword | Optimized | 2nd overall |
| 329 | Berserker Barbarian Greatsword | Optimized | **Highest of all 39** |

---

## Per-Tier Build Tables

### Tier 1 — All Builds

| Build | T1 | Tier | Style |
|---|---|---|---|
| Druid Base Spells | 4 | D | Spell |
| Bard Base Spells | 6 | D | Spell |
| College of Valor Greatsword | 6 | D | 2H |
| Circle of Moon Druid | 7 | C | 2H |
| Eldritch Knight Shillelagh | 7 | C | 1H |
| Celestial Patron True Strike Shillelagh | 7 | C | 1H |
| Warlock Base True Strike Shillelagh | 7 | C | 1H |
| Fighter Base Longsword | 7 | C | 1H |
| Warlock Base Eldritch Blast | 7 | C | Spell |
| Warlock Base Blade Pact Greatsword | 8 | C | 2H |
| Ranger Base HM Longbow | 8 | C | Ranged |
| Archfey Patron Eldritch Blast | 8 | C | Spell |
| Champion Shillelagh | 8 | C | 1H |
| Battle Master Longsword | 8 | C | 1H |
| Fighter Base Greatsword | 9 | C | 2H |
| Sorcerer Base Blast Spells | 9 | C | Spell |
| Fiend Patron Greatsword (Cha) | 9 | C | 2H |
| Fiend Patron Greatsword (Str) | 9 | C | 2H |
| Samurai Greatsword | 9 | C | 2H |
| Eldritch Knight Greatsword | 9 | C | 2H |
| Draconic Sorcerer Blast | 9 | C | Spell |
| Oath of Vengeance Longsword | 9 | C | 1H |
| Beastmaster Longbow | 10 | B | Ranged |
| Assassin Heavy Crossbow | 10 | B | Ranged |
| Paladin Base Greatsword | 10 | B | 2H |
| Monk Base Quarterstaff (versatile) | 11 | B | 2H |
| Rogue Base Light Crossbow True Strike | 11 | B | Ranged |
| Zealot Barbarian Longsword | 11 | B | 1H |
| Barbarian Base Greatsword | 12 | B | 2H |
| Rogue Base Dagger Thrower | 12 | B | Ranged |
| Berserker Barbarian Longsword | 12 | B | 1H |
| Oath of Vengeance Greatsword | 12 | B | 2H |
| Warrior of Shadow Monk | 13 | A | 2H |
| Oath of Vengeance Paladin TWF (Dex) | 14 | A | 2H |
| Zealot Barbarian Greatsword | 14 | A | 2H |
| Ranger Base HM TWF | 14 | A | 2H |
| Berserker Barbarian Greatsword | 15 | A | 2H |
| Fey Wanderer Summoner TWF | 15 | A | 2H |

**T1 Class Rankings:** Ranger=Barbarian=15 → Monk 13 → Paladin 14 → Rogue 12 → Fighter 9 → Sorcerer 9 → Warlock 8 → Bard 6 → Druid 4

---

### Tier 2 — All Builds

| Build | T2 | Tier | Style |
|---|---|---|---|
| Bard Base Spells | 15 | D | Spell |
| Druid Base Spells | 15 | D | Spell |
| Warlock Base True Strike Shillelagh | 17 | D | 1H |
| Warlock Base Eldritch Blast | 17 | D | Spell |
| College of Valor Greatsword | 18 | D | 2H |
| Celestial Patron True Strike Shillelagh | 19 | D | 1H |
| Fighter Base Longsword | 19 | D | 1H |
| Archfey Patron Eldritch Blast | 20 | D | Spell |
| Sorcerer Base Blast Spells | 20 | D | Spell |
| Circle of Moon Druid | 21 | D | 2H |
| Battle Master Longsword | 21 | D | 1H |
| Ranger Base HM Longbow | 21 | D | Ranged |
| Draconic Sorcerer Blast | 23 | C | Spell |
| Beastmaster Longbow | 23 | C | Ranged |
| Rogue Base Dagger Thrower | 23 | C | Ranged |
| Fiend Patron Greatsword (Cha) | 24 | C | 2H |
| Eldritch Knight Shillelagh | 24 | C | 1H |
| Warlock Base Blade Pact Greatsword | 24 | C | 2H |
| Rogue Base Light Crossbow True Strike | 24 | C | Ranged |
| Ranger Base Summoner TWF | 25 | C | 2H |
| Eldritch Knight Greatsword | 26 | C | 2H |
| Fighter Base Greatsword | 26 | C | 2H |
| Ranger Base HM TWF | 26 | C | 2H |
| Oath of Vengeance Longsword | 26 | C | 1H |
| Assassin Heavy Crossbow | 27 | C | Ranged |
| Monk Base TWF (Nick daggers) | 27 | C | 2H |
| Paladin Base Greatsword | 27 | C | 2H |
| Fey Wanderer Summoner TWF | 27 | C | 2H |
| Fiend Patron Greatsword (Str) | 28 | C | 2H |
| Samurai Greatsword | 29 | B | 2H |
| Champion Shillelagh | 29 | B | 1H |
| Zealot Barbarian Longsword | 30 | B | 1H |
| Berserker Barbarian Longsword | 32 | B | 1H |
| Barbarian Base Greatsword | 33 | B | 2H |
| Oath of Vengeance Paladin TWF (Dex) | 34 | B | 2H |
| Oath of Vengeance Paladin Greatsword | 35 | B | 2H |
| Warrior of Shadow Monk | 38 | A | 2H |
| Zealot Barbarian Greatsword | 41 | A | 2H |
| Berserker Barbarian Greatsword | 43 | A | 2H |

**T2 Class Rankings:** Barbarian 43 → Monk/Paladin 35–38 → Fighter/Ranger tied → Rogue/Warlock tied → Sorcerer 20 → Bard/Druid 15

---

### Tier 3 — All Builds

| Build | T3 | Tier | Style |
|---|---|---|---|
| Warlock Base True Strike Shillelagh | 26 | D | 1H |
| Bard Base Spells | 27 | D | Spell |
| Warlock Base Eldritch Blast | 27 | D | Spell |
| Ranger Base HM Longbow | 28 | D | Ranged |
| Ranger Base HM TWF | 28 | D | 2H |
| Ranger Base Summoner TWF | 29 | D | 2H |
| Druid Base Spells | 30 | D | Spell |
| Fighter Base Longsword | 31 | D | 1H |
| Rogue Base Dagger Thrower | 34 | C | Ranged |
| College of Valor Greatsword | 35 | C | 2H |
| Fey Wanderer Summoner TWF | 35 | C | 2H |
| Battle Master Longsword | ~36 | C | 1H |
| Beastmaster Longbow | ~36 | C | Ranged |
| Zealot Barbarian Longsword | ~37 | C | 1H |
| Archfey Patron Eldritch Blast | ~37 | C | Spell |
| Warlock Base Blade Pact Greatsword | 37 | C | 2H |
| Rogue Base Light Crossbow True Strike | 38 | C | Ranged |
| Monk Base TWF (Nick daggers) | 38 | C | 2H |
| Paladin Base Greatsword | 38 | C | 2H |
| Barbarian Base Greatsword | 38 | C | 2H |
| Sorcerer Base Blast Spells | 40 | C | Spell |
| Celestial Patron True Strike Shillelagh | 42 | B | 1H |
| Draconic Sorcerer Blast | 43 | B | Spell |
| Assassin Heavy Crossbow | 43 | B | Ranged |
| Circle of Moon Druid | 44 | B | 2H |
| Berserker Barbarian Longsword | 45 | B | 1H |
| Eldritch Knight Shillelagh | 47 | B | 1H |
| Fighter Base Greatsword | 47 | B | 2H |
| Fiend Patron Greatsword (Cha) | 48 | B | 2H |
| Zealot Barbarian Greatsword | 48 | B | 2H |
| Fiend Patron Greatsword (Str) | 49 | B | 2H |
| Eldritch Knight Greatsword | 49 | B | 2H |
| Oath of Vengeance Longsword | ~43 | B | 1H |
| Samurai Greatsword | 53 | A | 2H |
| Champion Shillelagh | 54 | A | 1H |
| Warrior of Shadow Monk | 54 | A | 2H |
| Oath of Vengeance Paladin TWF (Dex) | 56 | A | 2H |
| Oath of Vengeance Paladin Greatsword | 56 | A | 2H |
| Berserker Barbarian Greatsword | 57 | A | 2H |

**T3 Class Rankings:** Fighter 47 → Sorcerer 40 → Barbarian/Monk/Paladin/Rogue ~38 (4-way tie) → Warlock 37 → Druid 30 → Ranger 29 → Bard 27

---

### Tier 4 — All Builds

| Build | T4 | Tier | Style |
|---|---|---|---|
| Bard Base Spells | 35 | D | Spell |
| Ranger Base HM TWF | 37 | D | 2H |
| Fighter Base Longsword | 41 | D | 1H |
| Ranger Base HM Longbow | 44 | D | Ranged |
| Ranger Base Summoner TWF | 44 | D | 2H |
| Rogue Base Dagger Thrower | 45 | D | Ranged |
| Paladin Base Greatsword | ~46 | D | 2H |
| Barbarian Base Greatsword | ~48 | D | 2H |
| Battle Master Longsword | 48 | D | 1H |
| Zealot Barbarian Longsword | 49 | D | 1H |
| Monk Base TWF (Nick daggers) | 51 | C | 2H |
| Beastmaster Longbow | 52 | C | Ranged |
| Warlock Base True Strike Shillelagh | 52 | C | 1H |
| Fey Wanderer Summoner TWF | ~52 | C | 2H |
| Druid Base Spells | 54 | C | Spell |
| Warlock Base Eldritch Blast | 54 | C | Spell |
| Rogue Base Light Crossbow True Strike | 54 | C | Ranged |
| College of Valor Greatsword | 55 | C | 2H |
| Oath of Vengeance Longsword | 57 | C | 1H |
| Berserker Barbarian Longsword | 58 | C | 1H |
| Warlock Base Blade Pact Greatsword | 59 | C | 2H |
| Zealot Barbarian Greatsword | 60 | B | 2H |
| Archfey Patron Eldritch Blast | 61 | B | Spell |
| Fighter Base Greatsword | 63 | B | 2H |
| Warrior of Shadow Monk | 63 | B | 2H |
| Sorcerer Base Blast Spells | 65 | B | Spell |
| Celestial Patron True Strike Shillelagh | 65 | B | 1H |
| Oath of Vengeance Paladin TWF (Dex) | 66 | B | 2H |
| Draconic Sorcerer Blast | 68 | B | Spell |
| Assassin Heavy Crossbow | 68 | B | Ranged |
| Berserker Barbarian Greatsword | 71 | A | 2H |
| Champion Shillelagh | 71 | A | 1H |
| Samurai Greatsword | 72 | A | 2H |
| Fiend Patron Greatsword (Cha) | 73 | A | 2H |
| Fiend Patron Greatsword (Str) | 73 | A | 2H |
| Eldritch Knight Greatsword | 75 | A | 2H |
| Oath of Vengeance Paladin Greatsword | 76 | A | 2H |
| Circle of Moon Druid | 77 | A | 2H |
| Eldritch Knight Shillelagh | 78 | A | 1H |

**T4 Class Rankings (base):** Sorcerer 65 → Fighter 63 → Warlock 59 → Rogue/Druid 54 → Monk 51 → Barbarian ~48 → Paladin ~46 → Ranger 44 → Bard 35

---

## Subclass Damage Contributions at T4

| Subclass | Class | Style | +DPR at T4 |
|---|---|---|---|
| Oath of Vengeance | Paladin | 2H | +30 |
| Berserker | Barbarian | 2H | +23 |
| Circle of Moon | Druid | 2H | +23 |
| College of Valor | Bard | 2H | +20 |
| Eldritch Knight | Fighter | 1H | +15 |
| Fiend Patron | Warlock | 2H | +14 |
| Assassin | Rogue | Ranged | +14 |
| Zealot | Barbarian | 2H | +12 |
| Warrior of Shadow | Monk | 2H | +12 |
| Draconic | Sorcerer | Ranged | +3 |

---

## Key Engine Design Findings

**1. Greatsword dominates 2024.** Default weapon for martial build simulations.

**2. New baseline confirmed.** Warlock Blade Pact Greatsword — C tier all four tiers.
Career score 196. Engine minimum "okay damage" floor.

**3. Tier matters more than career score.** Ranger #1 at T1, near-last at T3–T4.
Circle of Moon: D at T2, A at T4. Eldritch Knight Shillelagh: 7 DPR at T1, 78 at T4.
Never evaluate a build from career score alone.

**4. Barbarian owns T2, Fighter owns T3.** Berserker 43 DPR at T2 (highest ever).
Fighter nearly doubles from T2→T3 (26→47) from third attack at L11.

**5. Pure spellcasting ceiling.** Best spell career: Draconic Sorcerer 232 (B tier).
Sorcerer only leads at T4 (base builds). Spellcasting categorically below
martial at T1–T3.

**6. Subclass gap grows with level.** Oath of Vengeance adds +30 DPR at T4.
Barbarian and Paladin fall to D tier at T4 without damage subclass.
Subclass selection is mandatory for T4 encounter accuracy.

**7. Ranged ~15% below melee.** Best ranged T4: 68. Best melee T4: 78.
Viable but not equivalent.

**8. Nick property underrated.** Rogue Dagger Thrower beats most optimized
two-handed builds at T1 purely from second sneak attack opportunity.

**9. Fighter L11 spike.** 26 DPR at T2 → 47 at T3. Most dramatic single-level
shift in dataset. Do not use smooth DPR curve for Fighters.

**10. Conjure Minor Elementals outlier.** ~80 DPR upcasted. Engine flag required.

---

## Video Processing Status

| Video | Title | Status |
|---|---|---|
| 1 | Methodology (How to Calculate Damage) | ✅ Complete |
| 19 | Definitive Class Damage Ranks | ✅ Complete |
| 20 | Class Damage Ranks in T1 | ✅ Complete |
| 21 | Tier 2 Class Damage Results | ✅ Complete |
| 22 | Tier 3 Damage Results | ✅ Complete |
| 23 | The New Baseline, and T4 Damage | ✅ Complete |
| 4 | FIGHTER Damage 2024 | 🔴 Pending — next priority |
| 5 | BARBARIAN Damage 2024 | 🔴 Pending |
| 2 | MONK Damage 2024 | 🔴 Pending |
| 3 | ROGUE Damage 2024 | 🔴 Pending |
| 7 | PALADIN Damage 2024 | 🔴 Pending |
| 8 | PALADIN TWF | 🔴 Pending |
| 11 | WARLOCK EB + True Strike | 🔴 Pending |
| 12 | PACT OF THE BLADE | 🔴 Pending |
| 14 | DRUID Damage 2024 | 🔴 Pending |
| 15 | SPELL DAMAGE: Base Bard | 🔴 Pending |
| 16 | VALOR BARD Damage | 🔴 Pending |
| 17 | ELDRITCH KNIGHT Damage | 🔴 Pending |
| 18 | SORCERER BLASTER Damage | 🔴 Pending |
| 9 | RANGER TWF | 🔴 Pending |
| 10 | LONGBOW RANGER | 🔴 Pending |
| 6 | SWORD AND SHIELD | 🔴 Pending |
| 13 | CONJURE WOODLAND BEINGS | 🔴 Pending |
