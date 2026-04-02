# PC DPR Baselines — Treantmonk 2024 Methodology

**Source:** Treantmonk's Temple YouTube channel — 2024 Player's Handbook DPS Series (23 videos, fall 2024)  
**Playlist:** https://youtube.com/playlist?list=PLfdtR0ufZC9eElP2Dv68kRj0yJIP1QtbU  
**Status:** 🟡 Methodology complete — per-class data partially populated  
**Last updated:** 2026-03-30  
**Location in engine:** `engine/math/pc_dpr.py`

---

## Purpose

This document encodes Treantmonk's per-class single-target DPR methodology for
use as the `dpr_hit` input to the PC XP formula in `finished-book-summary.md`
Section IV. It replaces the Finished Book's class-averaged baseline
(`DPR_PC ≈ 7 + 2·LV`) with empirically derived per-class curves.

This is single-target, white-room DPR only. It does not model AoE, control
spells, or support actions. Those are handled by the eHP Action Framework
(`ehp-action-framework.md`).

---

## ⚠️ Critical Policy Note — Two Baselines

Treantmonk uses two different baseline comparisons across this series:

**2014 Baseline (reference only — used in methodology video)**
Warlock: Eldritch Blast + Agonizing Blast + Hex. Used in prior series and
shown in the methodology video for historical comparison.

**2024 Baseline (the operative baseline for all 2024 class comparisons)**
A Warlock or Fighter using a two-handed Greatsword — a martial weapon baseline
that reflects the power shift in 2024 rules.
Source: Video 23 — "The New Baseline, and T4 damage."
`[PENDING — populate when Video 23 transcript is processed]`

**Engine policy:** All class DPR curves in this document are benchmarked against
the 2024 baseline, not the 2014 Warlock baseline. The 2014 baseline is retained
as a reference column only.

---

## Methodology

### Core Assumptions

Extracted from: "How to Calculate Damage in D&D 2024" (methodology video)

**Target AC Scale (maintains ~60% base hit chance at all levels):**

| Level | Target AC | Base Hit % |
|---|---|---|
| 1 | 14 | 60% |
| 2 | 14 | 60% |
| 3 | 15 | 60% |
| 4 | 15 | 60% |
| 5 | 16 | 60% |
| 6 | 16 | 60% |
| 7 | 17 | 60% |
| 8 | 17 | 60% |
| 9 | 18 | 60% |
| 10 | 18 | 60% |
| 11 | 18 | 60% |
| 12 | 18 | 60% |
| 13 | 19 | 60% |
| 14 | 19 | 60% |
| 15 | 20 | 60% |
| 16 | 20 | 60% |
| 17 | 20 | 60% |
| 18 | 20 | 60% |
| 19 | 20 | 60% |
| 20 | 20 | 60% |

**Reasoning (Treantmonk's explicit rationale):**
The DMG monster creation AC table is inaccurate — no CR30 creature has AC below
23, yet the table suggests 19. Real "big bad" monsters tend to have CR higher
than party level. 65% is overly generous; he would sooner use 55% than 65%.

**⚠️ Conflict with The Finished Book:** The Finished Book uses 65% as its
baseline hit probability. See `pillars-reconciliation.md` for resolution policy.
Short version: Finished Book's 65% governs encounter XP calculations; Treantmonk's
60% governs per-class DPR calibration. They serve different purposes.

**Encounter assumptions:**
- 4 combats per long rest
- Short rests: class-dependent (noted per class)
- No outside source of advantage or disadvantage unless specified
- No Elven Accuracy unless specified
- No magic items unless specifically noted
- Money-dependent damage sources (poison crafting, scrolls) excluded
- All values rounded to one decimal place

---

### The Damage Calculation Engine

#### Step 1 — Normal Attack Damage
```python
attack_damage = damage_mean * hit_probability
```

**Studied Attacks — Exact Formula (confirmed from screenshots):**

For attacks 2+ after a miss on the previous attack:
```
hit_prob  = (p_hit_adv × p_miss_prev) + (p_hit_normal × p_hit_prev)
crit_prob = (p_crit_normal × p_miss_prev) + (p_crit_adv × p_hit_prev)
```

At 60% base hit chance, the per-attack cascade is:
- Attack 1: 60% hit, 5% crit
- Attack 2: 70% hit, 7% crit
- Attack 3: 67% hit, 7% crit
- Attack 4: 68% hit, 7% crit

**Approximation (used in all builds):** All attacks after attack 1 use
68% hit / 7% crit once Studied Attacks is in play (L13+).

```python
STUDIED_ATTACKS_HIT_PROB = 0.68   # simplified approximation
STUDIED_ATTACKS_CRIT_PROB = 0.07  # simplified approximation
# Apply from level 13 onward to all attacks except the first
```
```python
crit_bonus = crit_dice_mean * 0.05
```
Kept separate because some builds (Epic Boon of Irresistible Offense, Brutal
Critical, etc.) modify crit damage independently from normal hit damage.

#### Step 3 — Second Attack Without Ability Modifier
When a second attack doesn't add the ability modifier (e.g. Nick weapon property,
off-hand without Fighting Style):
```python
# Shorthand valid for standard attacks with no special crit treatment
second_attack = damage_mean_no_mod * 0.65
# (equivalent to: damage_mean_no_mod * 0.60 + crit_dice_mean * 0.05)
```

#### Step 4 — Sneak Attack / Once-Per-Turn Bonus Damage
Treantmonk does NOT attach sneak attack to individual attacks. He calculates the
probability of landing it at least once across all eligible attacks:

```python
def p_sneak_attack(p_miss_attacks: list[float]) -> float:
    """
    Probability of triggering a once-per-turn bonus (sneak attack, etc.)
    across multiple attack attempts.
    p_miss_attacks: list of miss probabilities for each eligible attack
    """
    p_miss_all = 1.0
    for p_miss in p_miss_attacks:
        p_miss_all *= p_miss
    return 1.0 - p_miss_all
```

#### Step 5 — Sneak Attack Critical Probability
The crit chance on sneak attack is NOT simply 5%. It accounts for the second
chance to crit if the first attack missed:

```python
def p_sneak_crit(p_crit: float, p_miss_attack1: float) -> float:
    """
    Probability that sneak attack is delivered as a critical hit.
    Accounts for second attack opportunity if first attack missed.
    """
    return p_crit + (p_crit * p_miss_attack1)
```

**Example at level 1 (60% hit, 5% crit, no advantage):**
```
p_sneak_crit = 0.05 + (0.05 × 0.40) = 0.05 + 0.02 = 0.07 (7%)
```

#### Step 6 — Advantage Calculations

```python
def p_hit_with_advantage(p_hit_normal: float) -> float:
    p_miss = 1.0 - p_hit_normal
    return 1.0 - (p_miss * p_miss)

def p_crit_with_advantage(p_crit: float = 0.05) -> float:
    return 1.0 - (0.95 * 0.95)  # ≈ 0.0975, rounds to 10%

def p_hit_partial_advantage(p_hit_normal: float, advantage_fraction: float) -> float:
    """For builds with advantage only some of the time."""
    p_hit_adv = p_hit_with_advantage(p_hit_normal)
    return (p_hit_normal * (1 - advantage_fraction) +
            p_hit_adv * advantage_fraction)
```

#### Step 7 — Full DPR Assembly
```python
def calc_treantmonk_dpr(
    attacks: list[dict],          # [{damage_mean, crit_dice_mean, hit_prob}]
    bonus_damage: dict = None,    # {dice_mean, p_trigger, p_crit}
) -> float:
    """
    Assembles total DPR using Treantmonk's methodology.
    bonus_damage covers sneak attack, smite, hex, hunter's mark, etc.
    """
    total = 0.0

    for attack in attacks:
        normal = attack['damage_mean'] * attack['hit_prob']
        crit   = attack['crit_dice_mean'] * 0.05
        total += round(normal + crit, 1)

    if bonus_damage:
        bonus = bonus_damage['dice_mean'] * bonus_damage['p_trigger']
        crit_extra = bonus_damage['dice_mean'] * bonus_damage['p_crit']
        total += round(bonus + crit_extra, 1)

    return round(total, 1)
```

---

## Target AC Reference Function

```python
def treantmonk_target_ac(level: int) -> int:
    """Returns Treantmonk's target AC for a given level (60% base hit chance)."""
    ac_table = {
        range(1, 3):  14,
        range(3, 5):  15,
        range(5, 9):  16,  # Note: he uses 16 at 5-6, 17 at 7-8
        range(7, 9):  17,
        range(9, 13): 18,
        range(13, 15): 19,
        range(15, 21): 20,
    }
    # Corrected table based on methodology video
    scale = [14,14,15,15,16,16,17,17,18,18,18,18,19,19,20,20,20,20,20,20]
    return scale[level - 1]
```

---

## Per-Class DPR Data

### Video Processing Status

| # | Video | Class/Topic | Status |
|---|---|---|---|
| 1 | How to Calculate Damage in D&D 2024 | Methodology + Rogue demo | ✅ Processed |
| 2 | MONK Damage 2024 | Monk | 🔴 Pending |
| 3 | ROGUE Damage 2024 | Rogue (True Strike build) | 🔴 Pending |
| 4 | FIGHTER Damage 2024 | Fighter | ✅ Complete |
| 5 | BARBARIAN Damage 2024 | Barbarian | 🔴 Pending |
| 6 | SWORD AND SHIELD | Fighter variant | ✅ Complete (in Video 4) |
| 7 | PALADIN Damage 2024 | Paladin | 🔴 Pending |
| 8 | Paladin TWO WEAPON FIGHTING | Paladin variant | 🔴 Pending |
| 9 | RANGER TWO WEAPON FIGHTING | Ranger | 🔴 Pending |
| 10 | LONGBOW RANGER | Ranger variant | 🔴 Pending |
| 11 | WARLOCK DAMAGE: EB and True Strike | Warlock | 🔴 Pending |
| 12 | Pact of the Blade | Warlock variant | 🔴 Pending |
| 13 | Conjure Woodland Beings | Druid spell analysis | 🔴 Pending |
| 14 | DRUID Damage 2024 | Druid | 🔴 Pending |
| 15 | SPELL DAMAGE: Base Bard | Bard | 🔴 Pending |
| 16 | Valor Bard Damage | Bard variant | 🔴 Pending |
| 17 | Eldritch Knight Damage | Fighter subclass | 🔴 Pending |
| 18 | Sorcerer Blaster Damage | Sorcerer | 🔴 Pending |
| 19 | Definitive Class Damage Ranks | Summary | 🔴 Pending — HIGH PRIORITY |
| 20 | Class Damage Ranks in T1 | Tier 1 summary | 🔴 Pending |
| 21 | Tier 2 Class Damage Results | Tier 2 summary | 🔴 Pending |
| 22 | Tier 3 Damage Results | Tier 3 summary | 🔴 Pending |
| 23 | The New Baseline, and T4 damage | Baseline + Tier 4 | 🔴 Pending — CRITICAL |

**Known gaps:** No dedicated Wizard video or Cleric video in the playlist.
Coverage of those classes may appear in summary videos or be absent from the
dataset entirely. Flag when summary videos are processed.

---

### 2024 Baseline

`[PENDING — Video 23]`

```python
# Placeholder — to be populated from Video 23 transcript
TREANTMONK_2024_BASELINE_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Rogue — Dagger Thrower (No True Strike)

**Source:** Methodology video (demo build)  
**Build:** Two daggers (Nick mastery), Dex primary, Poisoner feat, Epic Boon of
Irresistible Offense at 19  
**Advantage source:** Cunning Action (Hide) ~50% at L2, Steady Aim 100% from L3  
**Short rests:** Irrelevant for Rogue  
**Notes:** Treantmonk noted this build beats baseline at all levels, but only
marginally. True Strike Rogue (light crossbow) outperforms at L5, L11, L17.

```python
ROGUE_DAGGER_THROWER_DPR = {
    1:  8.2,
    2:  9.2,
    3:  13.9,
    4:  14.8,
    5:  18.4,
    6:  18.4,
    7:  22.1,
    8:  22.9,
    9:  26.6,
    10: 26.6,
    11: 30.3,
    12: 30.3,
    13: 33.9,
    14: 33.9,
    15: 37.6,
    16: 37.6,
    17: 41.3,
    18: 41.3,
    19: 48.3,
    20: 48.3,
}
```

**Key observations:**
- Flat periods between sneak attack die increases (every odd level)
- Jump at L3 from Steady Aim (full-time advantage)
- Jump at L19 from Epic Boon of Irresistible Offense (+21 to crit damage)
- Characteristic Rogue pattern: strong at L3, L7, L11, L17 (sneak attack bumps)

---

### Rogue — True Strike Light Crossbow

`[PENDING — Video 3: "ROGUE: D&D 5.24 Damage is MENTAL"]`

```python
ROGUE_TRUE_STRIKE_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Fighter — Base Greatsword (2024)

**Source:** Video 4 — "FIGHTER Damage 2024 Player's Handbook"  
**Build:** Greatsword (Graze mastery) "quality of life build — BA stays free", Defense combat style  
**Starting stats (confirmed):** STR 17, CON 16 (DEX/INT/WIS/CHA unspecified)  
**Background:** Farmer (STR +2, CON +1, Tough origin feat)  
**ASIs:** Mage Slayer L4 (STR 18), Great Weapon Master L6 (STR 19), Charger L8 (STR 20),
Heavy Armor Master L12 (CON 17), Speedy L14 (CON 18), Alert L16,
Boon of Irresistible Offense L19 (STR 21)  
**No subclass**  
**Assumptions (confirmed from screenshots):** 4 combats/LR, 4 rounds/combat, 1 SR,
no outside advantage, Target AC 14 scaling +1 at L4/5/8/9/13/17,
GWM bonus action on crits only, Charger 50% of the time  
**Average DPR across 20 levels: 36.2 (723.9/20 — confirmed on screen)**

**Key mechanics:**
- Graze mastery adds ~15% DPR (guaranteed miss damage = ability modifier)
- Great Weapon Master 2024: adds proficiency bonus (+2→+6) to every attack action attack
- Studied Attacks (new 2024 feature): miss → next attack has advantage. Approximation:
  all attacks after first use 68% hit / 7% crit (vs baseline 60% / 5%)
- GWM bonus action attack on crits only (not on kill — same target assumed)

```python
FIGHTER_GREATSWORD_DPR = {
    1:  7.8,   # 2d6+3 (10.0,7.0): 10.0x0.60=6.0, 7.0x0.05=0.4, Graze 3x0.4=1.2
    2:  8.8,   # Action Surge 1 of 8 rounds: 7.8/8=1.0
    3:  8.8,
    4:  9.7,   # STR+4 (18): 2d6+4, attack 8.6+AS 8.6/8=1.1
    5:  19.4,  # Extra Attack: 8.6x2=17.2+AS 17.2/8=2.2
    6:  24.3,  # GWM+3: 2d6+7 (14.0,7.0), attack 20.8+BA 0.9+AS 20.8/8=2.6
    7:  24.3,
    8:  28.2,  # STR+5 (20), Charger: 2d6+8 (15.0,7.0), attack 22.8+BA 1.0+AS 2.9+Charger 1.5
    9:  29.4,  # GWM+4: 2d6+9 (16.0,7.0), attack 24.0+BA 1.0+AS 2.9+Charger 1.5
    10: 29.4,
    11: 43.3,  # Extra Attack x2: 3 attacks, 12x3=36.0+BA 1.3+AS 36.0/8=4.5+Charger 1.5
    12: 43.3,
    13: 48.4,  # GWM+5, Studied Attacks, BA 18%: attack 40.0+BA 1.9+AS 40.0/8=5.0+Charger 1.5
    14: 48.4,
    15: 48.4,
    16: 48.4,
    17: 55.7,  # AS x2 (1 of 4 rounds), GWM+6: 2d6+11 (18.0,7.0), attack 41.8+BA 1.9+AS 41.8/4=10.5+Charger 1.5
    18: 55.7,
    19: 60.9,  # Boon of Irresistible Offense (STR 21, crit damage +21)
    20: 81.3,  # Extra Attack x3 (4 attacks): attack 61.6+BA 2.8+AS 61.6/4=15.4+Charger 1.5
}
# Career average: 723.9 / 20 = 36.2 (confirmed on screen)
```

**Engine note — L11 spike:** Fighter DPR at L5 is 19.4. At L11 it is 43.3 — a 2.2×
multiplier from a single level. Do NOT use a smooth curve for Fighter DPR.
Model it as a step function with discrete jumps at L5, L11, L17, L20.

---

### Fighter — Sword and Board (2024)

**Source:** Video 4 — shown as cautionary example, not primary DPR reference  
**Build:** Longsword (Sap mastery), Shield, Dueling +2, no subclass  
**Starting stats (confirmed):** STR 17, DEX 14, CON 16, INT 8, WIS 10, CHA 8  
**Background:** Farmer (STR +2, CON +1, Tough origin feat)  
**ASIs:** Sentinel L4 (STR 18), Charger L6 (STR 19), Shield Master L8 (STR 20),
Heavy Armor Master L12 (CON 17), Speedy L14 (CON 18), Alert L16,
Boon of Combat Prowess L19 (STR 21)  
**Assumptions:** Prone with Shield 60% on hit, Sentinel reaction 25%, Charger 50%  
**Verdict:** Tracks the retired 2014 Warlock EB baseline. Not viable as a DPR build.  
**Average DPR across 20 levels: ~24 (est.)**

```python
FIGHTER_SWORD_BOARD_DPR = {
    1:  5.9,   # 1d8+3+2: 9.5×0.60=5.7 + 4.5×0.05=0.2
    2:  6.6,   # Action Surge 1 of 8 rounds: +5.9/8=0.7
    3:  6.6,
    4:  8.9,   # STR+4 (18), Sentinel reaction 25%: attack 6.5+AS 0.8+Sentinel 1.6
    5:  16.2,  # Extra Attack: attack 13+AS 1.6+Sentinel 1.6
    6:  17.7,  # Charger 1d8: 4.5x0.65x0.50=1.5
    7:  17.7,
    8:  18.9,  # STR+5 (20), Shield Master: prone on attack 2 = 0.60x0.60=36%
    9:  18.9,
    10: 18.9,
    11: 27.2,  # Extra Attack x2: 3 attacks+AS 22.2/8=2.8+Sentinel 1.6+Charger 1.5
    12: 27.2,
    13: 28.4,  # Studied Attacks: Adv A2=58%, A3=52%; AS 23.6/8=3.0
    14: 28.4,
    15: 28.4,
    16: 28.4,
    17: 31.4,  # Action Surge x2: AS=6.0
    18: 31.4,
    19: 40.4,  # Boon of Combat Prowess (STR 21): 0.69x10.5=7.2+Sentinel 2.6+Charger 2.3
    20: 49.3,  # Extra Attack x3: 4 attacks+AS 31.4/4=7.9+Sentinel 2.6+Charger 2.3+Prowess 8.2
}
```

---

### Fighter — Champion Shillelagh (Optimized — "The Nightmare Build")

**Source:** Video 4 — optimized build. Treantmonk explicitly flags math confidence as lower
than usual due to extreme complexity. "Take with a huge grain of salt."  
**Build:** Human (Magic Initiate Druid: Shillelagh, Guidance, Jump), Champion subclass,
Quarterstaff + Shillelagh (Topple mastery), Background: Farmer (STR +2, CON +1, Tough origin feat),
Polar Master, Sentinel, Shield Master, Dueling +2, STR primary  
**Starting stats (confirmed from screenshot):** STR 17, DEX 14, CON 16, INT 8, WIS 10, CHA 8  
**Shillelagh scaling:** 1d8 (L1) → 1d10 (L5) → 1d12 (L11) → 2d6 (L17)  
**Champion features:** Crit 19-20 at L3, Defense style L7, Heroic Inspiration L10, Crit 18-20 at L15  
**Average DPR across 20 levels: 41.1**

**Assumption list (from screenshots):**
- Reaction attacks do not have advantage
- Target not already prone at start of turn
- First attack has no advantage
- All attacks on turn against same target
- 60% of targets fail Shield Master save (prone)
- 50% of targets fail Topple save (prone)
- Enemy not immune to prone
- Reaction attack: 25% with PAM, 50% with PAM + Sentinel
- Bonus action used on round 1 to cast Shillelagh
- 4-round combat, 8 rounds between short/long rests
- Action Surge used for attack action as often as possible
- Polar Master 1d4 BA does NOT benefit from Shillelagh damage scaling

**Advantage cascade (from screenshots, L13+):**
- Attack 1: 0%, Attack 2: 69%, Attack 3: 81%, Attack 4: 87%,
  Attack 5: 92%, Attack 6: 95%

**Heroic Inspiration availability (from screenshots):**
- Attack 1: 40%, Attack 2: 9%, Attack 3: 7%, Attack 4: 6%,
  Attack 5: 5%, Attack 6: 4%

```python
FIGHTER_CHAMPION_SHILLELAGH_DPR = {
    1:  5.9,   # STR+3, Shillelagh 1d8, Dueling +2, Topple
    2:  6.7,   # Action Surge (1 of 8 rounds), 30% prone on AS
    3:  7.1,   # Crit range 19-20
    4:  14.0,  # STR+4, PAM BA on rounds 2-4, Reaction 25%
    5:  25.1,  # Extra Attack, Shillelagh 1d10, Reaction 25%
    6:  27.0,  # Reaction 50% (PAM + Sentinel)
    7:  27.0,  # Champion: Additional fighting style (Defense)
    8:  30.6,  # STR+5, Shield Master (60% prone on hit)
    9:  30.6,  # Tactical Master: replace Topple with Sap/Slow/Push when prone
    10: 36.0,  # Heroic Inspiration at start of turn
    11: 53.2,  # Extra Attack x2, Shillelagh 1d12
    12: 53.2,
    13: 54.0,  # Studied Attacks
    14: 54.0,
    15: 56.2,  # Crit range 18-20
    16: 56.2,
    17: 63.5,  # Action Surge x2, Shillelagh 2d6
    18: 63.5,
    19: 74.4,  # Boon of Combat Prowess (STR 21, missed hit → hit)
    20: 83.3,  # Extra Attack x3 (8 potential attacks in one turn)
}
```

**Note:** The Champion Shillelagh build outperforms the Greatsword build from L11 onward
despite using only one hand. This validates the career score (274) ranking it as tied
for top of B tier. The math complexity is real — Treantmonk spent hours on this and
is not fully confident in the results.

---

### Barbarian

`[PENDING — Video 5: "BARBARIAN Damage 2024 Player's Handbook"]`

```python
BARBARIAN_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Monk

`[PENDING — Video 2: "MONK: D&D 5.24 Damage 2024 Player's Handbook"]`

```python
MONK_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Paladin

`[PENDING — Video 7: "PALADIN: D&D 5.24 Damage 2024 Player's Handbook"]`

```python
PALADIN_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Paladin — Two Weapon Fighting

`[PENDING — Video 8]`

```python
PALADIN_TWF_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Ranger — Two Weapon Fighting

`[PENDING — Video 9]`

```python
RANGER_TWF_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Ranger — Longbow

`[PENDING — Video 10]`

```python
RANGER_LONGBOW_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Warlock — Eldritch Blast + True Strike

`[PENDING — Video 11]`

```python
WARLOCK_EB_DPR = {
    level: None for level in range(1, 21)
}
```

**Note:** This is the 2024 Warlock EB build, NOT the 2014 EB+Hex baseline.
The 2024 version uses True Strike differently due to rule changes.

---

### Warlock — Pact of the Blade

`[PENDING — Video 12]`

```python
WARLOCK_PACT_BLADE_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Druid

`[PENDING — Video 14]`

```python
DRUID_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Bard — Spell Damage (Base)

`[PENDING — Video 15]`

```python
BARD_BASE_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Bard — Valor

`[PENDING — Video 16]`

```python
BARD_VALOR_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Fighter — Eldritch Knight

`[PENDING — Video 17]`

```python
FIGHTER_EK_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Sorcerer — Blaster

`[PENDING — Video 18]`

```python
SORCERER_BLASTER_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Fighter — Sword and Shield

`[PENDING — Video 6]`

```python
FIGHTER_SNS_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Wizard

**Status:** 🔴 No dedicated video in playlist  
May appear in summary videos. Flag when processed.

```python
WIZARD_DPR = {
    level: None for level in range(1, 21)
}
```

---

### Cleric

**Status:** 🔴 No dedicated video in playlist  
May appear in summary videos. Flag when processed.

```python
CLERIC_DPR = {
    level: None for level in range(1, 21)
}
```

---

## Engine Integration

Once all DPR tables are populated, this module feeds the `PCStatBlock.dpr_hit`
field in `engine/data/schemas.py`:

```python
from engine.math.pc_dpr import get_class_dpr

def build_pc_stat_block(character_class: str, level: int, ...) -> PCStatBlock:
    dpr_hit = get_class_dpr(character_class, level)
    # Falls back to Finished Book average if class not in Treantmonk dataset
    if dpr_hit is None:
        dpr_hit = calc_pc_baseline_dpr(level)  # 7 + 2*LV
    ...
```

```python
def get_class_dpr(character_class: str, level: int) -> float | None:
    """
    Returns Treantmonk's single-target DPR for a class at a given level.
    Returns None if class/level not in dataset (caller should use fallback).
    """
    registry = {
        "rogue_dagger":      ROGUE_DAGGER_THROWER_DPR,
        "rogue_true_strike": ROGUE_TRUE_STRIKE_DPR,
        "fighter":           FIGHTER_DPR,
        "barbarian":         BARBARIAN_DPR,
        "monk":              MONK_DPR,
        "paladin":           PALADIN_DPR,
        "ranger_twf":        RANGER_TWF_DPR,
        "ranger_longbow":    RANGER_LONGBOW_DPR,
        "warlock_eb":        WARLOCK_EB_DPR,
        "warlock_blade":     WARLOCK_PACT_BLADE_DPR,
        "druid":             DRUID_DPR,
        "bard":              BARD_BASE_DPR,
        "bard_valor":        BARD_VALOR_DPR,
        "fighter_ek":        FIGHTER_EK_DPR,
        "sorcerer":          SORCERER_BLASTER_DPR,
    }
    table = registry.get(character_class)
    if table is None:
        return None
    return table.get(level)
```

---

## Known Limitations

Per Treantmonk's own stated caveats and community critique:

| Limitation | Impact on Simulator |
|---|---|
| White room only — no environmental factors | Engine applies environment modifiers on top of these baselines |
| Single-target only — no AoE | AoE handled by eHP Action Framework separately |
| Does not optimize all builds equally | Some classes (Monk) may be undervalued; note in class entries |
| Subclass features may be excluded | Note per class which subclass features are/aren't included |
| 4 combats/long rest assumption | May overvalue resource-intensive builds vs. The Finished Book's model |
| No magic items | Engine applies magic item adjustments from `finished-book-summary.md` Section X |
| Spike damage (crits, smites) penalized by averaging | Engine handles variance separately in Sampled mode |
