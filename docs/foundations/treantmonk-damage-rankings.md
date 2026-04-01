# Treantmonk 2024 Damage Rankings — Definitive Summary

**Source:** "Definitive Class Damage Ranks: D&D 2024" (Video 19 of 23)  
**Treantmonk's Temple:** https://youtube.com/playlist?list=PLfdtR0ufZC9eElP2Dv68kRj0yJIP1QtbU  
**Status:** ✅ Complete — extracted from transcript  
**Last updated:** 2026-03-30  
**Used by:** `engine/math/pc_dpr.py`, `docs/foundations/pc-dpr-baselines.md`

---

## Purpose

This document encodes Treantmonk's weighted overall damage scores for every
build he analyzed across the 2024 series. These scores are the primary reference
for the simulator's class/subclass power ranking system.

These are NOT per-level DPR values — they are weighted aggregate scores across
all 20 levels, with middle levels weighted more heavily than tier 1 and tier 4.
Per-level DPR curves live in `pc-dpr-baselines.md`.

---

## Scoring Methodology

- Scores represent weighted average single-target DPR across levels 1–20
- Middle levels (roughly tiers 2–3, levels 5–15) weighted more heavily
- Lower bound: ~140 (worst build analyzed)
- Upper bound: ~329 (best build analyzed)
- Scores are comparable across builds but NOT directly translatable to per-round
  DPR without the weighting formula (defined in tier breakdown videos 20–23)

### Tier Thresholds

| Tier | Score Range | Description |
|---|---|---|
| **D** | < 175 | Below acceptable damage |
| **C** | 175–225 | Acceptable / okay damage |
| **B** | 226–275 | Good damage |
| **A** | > 275 | Top tier damage |

### Classes Omitted

Treantmonk explicitly did not analyze Wizard or Cleric, noting:
- Neither would have been at the top of the list
- Spellcasting damage is well-represented by Bard, Druid, Warlock, Sorcerer
- Both can be inferred from existing spellcaster data

**Engine policy:** Wizard and Cleric use Sorcerer Base Blast as their closest
proxy for single-target DPR until dedicated data is available.

---

## Complete Build Rankings (Bottom to Top)

### D Tier (Score < 175)

| Rank | Build | Type | Score | Notes |
|---|---|---|---|---|
| 1 (lowest) | Bard Base Spells | Base | 140 | Lowest of all builds. Bards not built for single-target damage |
| 2 | Warlock Base True Strike Shillelagh | Base | 162 | Reddit novelty build — single attack with Cha modifier via Agonizing Blast |
| 3 | Druid Base Spells | Base | 163 | Spells alone insufficient for single-target damage |
| 4 | Warlock Base Eldritch Blast | Base | 166 | **Former 2014 baseline now in D tier** — EB Warlocks no longer competitive |
| 5 | Fighter Base Longsword | Base | 167 | Longsword is defensive weapon; base fighter without optimized build is weak |
| 6 | Ranger Base Hunter's Mark + Hail of Thorns Longbow | Base | 168 | Flatline at level 11; significantly behind TWF variant |

**Key insight:** The 2014 Warlock EB+Agonizing Blast baseline is now D tier.
This is why Treantmonk switched to a new 2024 baseline. Eldritch Blast Warlocks
"just aren't in the game anymore as far as single target damage."

---

### C Tier (Score 175–225)

| Rank | Build | Type | Score | Notes |
|---|---|---|---|---|
| 7 | College of Valor True Strike Greatsword | Optimized | 185 | Lowest optimized build. No weapon mastery hurts badly. Slow start |
| 7 | Ranger Base Hunter's Mark TWF | Base | 185 | Tied with College of Valor — shocking for an optimized vs base comparison |
| 9 | Battle Master Longsword | Optimized | 189 | Subclass improves longsword but still C tier |
| 10 | Ranger Base Summoner TWF | Base | 191 | Summon Fey improves on Hunter's Mark alone |
| 11 | Rogue Base Dagger Thrower | Base | 194 | From methodology video — two daggers Nick mastery |
| 12 | Archfey Patron Eldritch Blast | Optimized | 203 | +37 over base EB build from subclass optimization |
| 12 | Beastmaster Longbow | Optimized | 203 | Tied — better than base longbow Ranger but still limited at high levels |
| 14 | Celestial Patron True Strike Shillelagh | Optimized | 213 | 4-way tie |
| 14 | Paladin Base Greatsword | Base | 213 | 4-way tie |
| 14 | Rogue Base Light Crossbow True Strike | Base | 213 | 4-way tie |
| 14 | Warlock Base Blade Pact Greatsword | Base | 213 | 4-way tie |
| 18 | Sorcerer Base Blast Spells | Base | 214 | Big Bad's Hand + Scorching Ray; highest pure-spell base build |
| 19 | Fey Wanderer Summoner TWF | Optimized | 218 | Best Ranger build — still only high C tier |
| 20 | Monk Base | Base | 219 | Quarterstaff L1–4, unarmed L5–20. Strong showing for base build |
| 21 | Zealot Barbarian Longsword | Optimized | 224 | Excellent at lower tiers, falls off at higher levels |

**Key insight:** College of Valor (optimized) scores the same as Ranger Base
Hunter's Mark TWF (no subclass). Weapon Mastery absence on Bards is "really
really felt."

---

### B Tier (Score 226–275)

| Rank | Build | Type | Score | Notes |
|---|---|---|---|---|
| 22 | Draconic Sorcerer Blast Build | Optimized | 232 | Highest damage achievable with full spellcasting. Innate Sorcery is key |
| 22 | Oath of Vengeance Paladin Longsword | Optimized | 232 | Tied — strong subclass overcomes longsword limitations |
| 24 | Barbarian Base Greatsword | Base | 235 | 2nd highest base build. Strong in tier 2 |
| 24 | Circle of Moon Druid Conjure Animals | Optimized | 235 | Tied — wild shape + conjure animals. Especially strong in tier 4 |
| 26 | Fighter Base Greatsword | Base | 238 | Highest base build overall. Tier 3 scaling (L11, L17, L20) pulls it ahead |
| 27 | Assassin Heavy Crossbow | Optimized | 245 | Highest ranged damage of all builds. Fighter dip for heavy crossbow proficiency |
| 28 | Fiend Patron Greatsword Blade Pact (Cha) | Optimized | 250 | Charisma focus — slightly lower than Str but better for spell DCs |
| 29 | Eldritch Knight True Strike Shillelagh | Optimized | 251 | Slow burn — poor at low levels, strong at high levels |
| 30 | Berserker Barbarian Longsword | Optimized | 256 | Strong at early levels — Reckless Attack + Sap mastery combo |
| 31 | Eldritch Knight Greatsword | Optimized | 260 | Better than Shillelagh variant for overall 20-level career |
| 32 | Fiend Patron Greatsword Blade Pact (Str) | Optimized | 264 | Strength focus — ~5% higher damage than Cha version |
| 33 | Champion Shillelagh | Optimized | 274 | Mathematically complex. Topple + Shillelagh + Champion crit range |
| 33 | Samurai Greatsword | Optimized | 274 | Tied — top of B tier. Better subclass-agnostic fighter build |

---

### A Tier (Score > 275)

| Rank | Build | Type | Score | Notes |
|---|---|---|---|---|
| 35 | Zealot Barbarian Greatsword | Optimized | 293 | Dominant in tier 2. Falls off at higher levels but early lead is significant |
| 36 | Oath of Vengeance Paladin TWF (Dex) | Optimized | 294 | Scimitar + shortsword, Dual Wielder, Divine Favor round 1. Highest TWF build |
| 37 | Warrior of Shadow Monk | Optimized | 298 | Quarterstaff L1–4, unarmed L5–20. Darkness for advantage. **3rd highest overall** |
| 38 | Oath of Vengeance Paladin Greatsword | Optimized | 305 | Half spell slots on smites. **2nd highest overall** |
| 39 (highest) | Berserker Barbarian Greatsword | Optimized | 329 | **Highest damage of all 39 builds**. Dominant at every tier, especially tier 2 |

---

## Class Rankings Summary

### Base Builds Only (No Subclass) — Best per Class

| Rank | Class | Best Base Build | Score | Tier |
|---|---|---|---|---|
| 1 | Fighter | Greatsword | 238 | B |
| 2 | Barbarian | Greatsword | 235 | B |
| 3 | Monk | Unarmed/Quarterstaff | 219 | C |
| 4 | Sorcerer | Blast Spells | 214 | C |
| 5 | Paladin | Greatsword | 213 | C |
| 5 | Rogue | Light Crossbow True Strike | 213 | C |
| 5 | Warlock | Blade Pact Greatsword | 213 | C |
| 8 | Ranger | Summoner TWF | 191 | C |
| 9 | Druid | Base Spells | 163 | D |
| 10 | Bard | Base Spells | 140 | D |

### Optimized Builds Only (With Subclass) — Best per Class

| Rank | Class | Best Optimized Build | Score | Tier |
|---|---|---|---|---|
| 1 | Barbarian | Berserker Greatsword | 329 | A |
| 2 | Paladin | Oath of Vengeance Greatsword | 305 | A |
| 3 | Monk | Warrior of Shadow | 298 | A |
| 4 | Fighter | Samurai Greatsword | 274 | B |
| 5 | Warlock | Fiend Patron Blade Pact Str Greatsword | 264 | B |
| 6 | Rogue | Assassin Heavy Crossbow | 245 | B |
| 7 | Druid | Circle of Moon Conjure Animals | 235 | B |
| 8 | Sorcerer | Draconic Blast | 232 | B |
| 9 | Ranger | Fey Wanderer Summoner TWF | 218 | C |
| 10 | Bard | College of Valor True Strike Greatsword | 185 | C |

---

## Key Findings for Engine Design

### 1. Greatsword Dominance
The greatsword is the highest-damage weapon in 2024 for virtually every martial
class. The engine's default weapon assignment for martial builds should be
greatsword unless build specifically requires otherwise.

### 2. The Paladin Is Not Nerfed
Treantmonk explicitly addresses online claims that Paladins were "horribly nerfed"
in 2024. His data shows Oath of Vengeance Greatsword Paladin is the 2nd highest
damage build overall at 305. Key: spending half spell slots on smites via bonus
action, not attacking with bonus action.

### 3. Monk Is Legitimate Now
Warrior of Shadow Monk at 298 (3rd overall) is a significant finding. The
Darkness advantage assumption is noted — this won't apply to creatures with
Truesight or Blindsight. The engine must flag this condition dependency.

### 4. Eldritch Blast Is Dead for DPR
The 2014 baseline (EB + Agonizing Blast + Hex) scores 166 — D tier. The engine
must NOT use this as a PC DPR reference for 2024 rules.

### 5. Base vs Optimized Gap
The gap between best base build (Fighter Greatsword 238) and best optimized
build (Berserker 329) is ~38%. The gap between worst base (Bard 140) and best
optimized (Berserker 329) is 135%. This is the range the simulator's
class/subclass scoring system must span.

### 6. Ranged vs Melee
Best ranged build: Assassin Heavy Crossbow at 245 (B tier, rank 6 of 10
optimized). Ranged damage is viable but cannot match top melee builds. Engine
should model ranged builds as approximately 75% of top melee damage.

### 7. Pure Spellcaster Ceiling
The highest pure-spellcasting damage (Draconic Sorcerer 232) is the 8th best
optimized build and doesn't reach A tier. For single-target DPR, the engine
should treat pure-spellcaster DPR as categorically lower than martial DPR,
compensated by AoE and control value in the eHP Action Framework.

### 8. Conjure Woodland Beings Note
Not scored in this video — a separate analysis video exists (Video 13). The
spell was flagged as "a PROBLEM" suggesting it may significantly inflate Druid
damage in certain configurations. Flag for separate treatment.

---

## Score-to-DPR Conversion Note

These weighted scores are NOT directly comparable to per-round DPR values.
The conversion methodology is defined across videos 20–23 (tier breakdowns).

**Approximate relationship:**
- Score ÷ 20 levels ≈ rough average DPR per level (unweighted)
- Berserker 329 ÷ 20 ≈ 16.5 average DPR (but middle levels do significantly more)
- Actual mid-tier DPR for top builds likely in the 25–50 range

Precise per-level curves come from individual class videos in `pc-dpr-baselines.md`.

---

## Video Processing Status Update

| Video | Status |
|---|---|
| Video 1 — Methodology | ✅ Complete |
| Video 19 — Definitive Rankings | ✅ Complete (this document) |
| Videos 20–23 — Tier Breakdowns | 🔴 Pending — will provide per-tier DPR context |
| Individual class videos (2–18) | 🔴 Pending — will provide per-level DPR curves |
