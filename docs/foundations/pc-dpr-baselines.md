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
| 5 | BARBARIAN Damage 2024 | Barbarian | ✅ Complete |
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

### Barbarian — Base Greatsword (2024)

**Source:** Video 5 — "BARBARIAN Damage 2024 Player's Handbook"  
**Build:** Greatsword (Graze mastery) "quality of life build — BA stays free", no subclass  
**Starting stats (confirmed):** STR 17, CON 16 (DEX/INT/WIS/CHA unspecified)  
**Background:** Farmer (STR +2, CON +1, Tough origin feat)  
**ASIs:** Great Weapon Master L4 (STR 18), STR+2 L8 (STR 20), Mage Slayer L12 (DEX+1),
Speedy L16 (DEX+1), Boon of Irresistible Offense L19 (STR 21)  
**No subclass**  
**Assumptions (confirmed from screenshots):** 4 combats/LR, 4 rounds/combat, 1 SR,
no outside advantage, Target AC 14 scaling +1 at L4/5/8/9/13/17,
Rage used on round 1 when available, Reckless Attack always used,
GWM bonus action on crits only, Brutal Strike math done at each level —
included in DPR only when it exceeds normal Reckless Attack damage  
**Average DPR across 20 levels: 33.4 (667.7/20 — confirmed on screen)**

**Key mechanics (Barbarian-specific):**
- **Reckless Attack (L2):** Always has advantage → 84% hit, 10% crit, Graze on 16% miss
- **Rage bonus:** +2 at L1, +3 at L9, +4 at L16
- **Brutal Strike (L9):** Forgo advantage on one attack for +1d10 damage
  (scales to 2d10 at L17, gains 2 effect options at L13/17).
  When Brutal Strike used: Reckless attack is normal (60% hit), BA attack drops to 14% (×0.75)
- **Graze scaling:** = STR modifier + Rage bonus (3→4→5→6→7)
- **GWM taken at L4** (earlier than Fighter's L6), applying immediately with Reckless advantage

```python
BARBARIAN_GREATSWORD_DPR = {
    1:  8.8,   # 2d6+3+2 (12,7): 12x0.60=7.2, 7x0.05=0.4, Graze 3x0.40=1.2
    2:  11.3,  # Reckless Attack: 12x0.84=10.1, 7x0.10=0.7, Graze 3x0.16=0.5
    3:  11.3,
    4:  14.8,  # STR+4, Graze 4, GWM+2: 2d6+4+2+2 (15,7), BA 10%x0.75=0.9
    5:  28.7,  # Extra Attack: 13.9x2=27.8+BA 0.9
    6:  31.1,  # GWM+3, BA 19%x0.75
    7:  31.1,
    8:  33.5,  # STR+5 (20), Graze 5: 2d6+5+2+3 (17,7), BA attack included
    9:  36.9,  # Rage+3, GWM+4, Brutal Strike 1d10 available (taken when higher)
    10: 36.9,
    11: 36.9,
    12: 36.9,
    13: 38.6,  # GWM+5, Brutal Strike gains Disadv/no-opp-attack or +5-to-hit options
    14: 38.6,
    15: 38.6,
    16: 40.3,  # Rage+4
    17: 44.3,  # GWM+6, Brutal Strike now 2d10 + 2 options on a hit
    18: 44.3,
    19: 47.7,  # Boon of Irresistible Offense (STR 21, crit +21); without Brutal Strike: 46.6
    20: 57.1,  # STR+7, Graze 7, base 70% hit/91% adv; without Brutal Strike: 54.3
}
# Career average: 667.7 / 20 = 33.4 (confirmed on screen)
```

**Engine notes:**
- Barbarian DPR is consistently higher than Fighter at T1–T2 due to permanent Reckless
  advantage from L2. No level spike comparable to Fighter's L11.
- Brutal Strike is an optional trade — engine should model both paths and take max,
  matching Treantmonk's methodology.
- At L20, Barbarian base (33.4 career) is below Fighter base (36.2 career) despite
  stronger T1–T2 performance. Fighter's L11 triple-attack spike is decisive.

---

### Barbarian — Zealot (Greatsword)

**Source:** Zealot subclass DPR analysis — `[TBD: separate Treantmonk video, not in the 23-video 2024 PHB DPS playlist]`
**Build:** Greatsword (Graze mastery) "quality of life build — BA stays free", Zealot subclass
**Starting stats (confirmed):** STR 17, CON 16 (DEX/INT/WIS/CHA unspecified)
**Background:** Farmer (STR +2, CON +1, Tough origin feat)
**ASIs:** Great Weapon Master L4 (STR 18), Strength +2 L8 (STR 20), Mage Slayer L12 (DEX +1), Speedy L16 (DEX +1), Boon of Irresistible Offense L19 (STR 21)
**Assumptions (confirmed from screenshots):** 4 combats/LR, 4 rounds/combat, 1 SR, no outside advantage, Target AC 14 scaling +1 at L4/5/8/9/13/17, Rage round 1, Reckless Attack always used, GWM bonus action attack on crits only, Brutal Strike math computed each level — included in DPR only when it exceeds normal Reckless DPR
**Average DPR across 20 levels: 41.5 (829.7/20)**

**Zealot-specific mechanic — Divine Fury (L3):**
- Once per turn, on the first creature hit, add `1d6 + ½ barbarian level` radiant/necrotic damage
- Activation = P(at least one hit on turn): `0.84` with single attack (L3–L4), `0.97` with Extra Attack (L5+) under Reckless
- Crit chance for DF damage = P(first-hitting attack is a crit) = `crit_1 + miss_1 × crit_2`
  - With 2 Reckless attacks: `0.10 + 0.16 × 0.10 = 11%`
  - With Brutal Strike (forgoes advantage on one attack): `~10%`
- **Never triggers on a Bonus Action attack** — by the time BA fires, the main attack already hit, so DF was already spent
- Crit-damage contribution from DF is `0.4` at every level — the `1d6` portion crits to `3.5` extra and multiplies the same way regardless of the underlying weapon path (Reckless vs Brutal Strike)

**Per-level math (verbatim from Treantmonk's tables — see screenshots in `treantmonk-dpr-baselines` branch):**

#### L1 — Str +3, Graze 3, Rage +2

```
Main: 2d6 + 3 + 2   (avg 12, crit extra 7)
  12 × 0.60 = 7.2    hit
   7 × 0.05 = 0.4    crit
   3 × 0.40 = 1.2    Graze (= STR mod + Rage)
  → 8.8

DPR: 8.8
```

#### L2 — Reckless Attack (advantage: hit 0.84, crit 0.10, miss 0.16)

```
Main: 2d6 + 3 + 2   (avg 12, crit extra 7)
  12 × 0.84 = 10.1
   7 × 0.10 = 0.7
   3 × 0.16 = 0.5
  → 11.3

DPR: 11.3
```

#### L3 — Divine Fury online

```
Main: (same as L2) → 11.3

Divine Fury: 1d6 + 1   (avg 4.5, crit extra 3.5)
  4.5 × 0.84 = 3.8    activation (single attack hit chance)
  3.5 × 0.10 = 0.4    crit (single attack)
  → 4.2

DPR: 15.5
```

#### L4 — Str +4 (18), Graze 4, GWM +2; BA attack 10% × 0.75 (can't use round 1)

```
Main: 2d6 + 4 + 2 + 2   (avg 15, crit extra 7)
  15 × 0.84 = 12.6
   7 × 0.10 = 0.7
   4 × 0.16 = 0.6
  → 13.9

Bonus Action attack (GWM, on crit only): 2d6 + 4 + 2   (avg 13, crit extra 7)
  13 × 0.84 = 10.9
   7 × 0.10 = 0.7
   4 × 0.16 = 0.6
  → 12.2 per use
  BA contribution = 12.2 × 0.75 × 0.10 = 0.9

Main + BA: 13.9 + 0.9 = 14.8

Divine Fury: 1d6 + 2   (avg 5.5, crit extra 3.5)
  5.5 × 0.84 = 4.6
  3.5 × 0.10 = 0.4
  → 5.0

DPR: 19.8
```

#### L5 — Extra Attack (DF activation jumps to 0.97 = 1 − 0.16²)

```
Main (×2 attacks): 2d6 + 4 + 2 + 2   (avg 15, crit extra 7)
  per attack: 12.6 + 0.7 + 0.6 = 13.9
  × 2 = 27.8

Bonus Action attack: 2d6 + 4 + 2   (avg 13, crit extra 7)
  → 12.2 per use
  BA contribution = 12.2 × 0.75 × 0.10 = 0.9

Main + BA: 27.8 + 0.9 = 28.7

Divine Fury: 1d6 + 2   (avg 5.5, crit extra 3.5)
  5.5 × 0.97 = 5.3    activation (≥1 hit out of 2 reckless attacks)
  3.5 × 0.11 = 0.4    crit (~11%)
  → 5.7

DPR: 34.4
```

#### L6 — GWM +3, BA chance up to 19% (×0.75 round-1 unavailable)

```
Main (×2 attacks): 2d6 + 4 + 2 + 3   (avg 16, crit extra 7)
  per attack: 13.4 + 0.7 + 0.6 = 14.7
  × 2 = 29.4

Bonus Action attack: 2d6 + 4 + 2   (avg 13, crit extra 7)
  → 12.2 per use
  BA contribution = 12.2 × 0.75 × 0.19 = 1.7

Main + BA: 29.4 + 1.7 = 31.1

Divine Fury: 1d6 + 3   (avg 6.5, crit extra 3.5)
  6.5 × 0.97 = 6.3
  crit = 0.4
  → 6.7

DPR: 37.8
```

#### L7 — no new DPR features

```
DPR: 37.8 (unchanged from L6)
```

#### L8 — Str +5 (20), Graze 5

```
Main (×2 attacks): 2d6 + 5 + 2 + 3   (avg 17, crit extra 7)
  per attack: 14.3 + 0.7 + 0.8 = 15.8
  × 2 = 31.6

Bonus Action attack: 2d6 + 5 + 2   (avg 14, crit extra 7)
  14 × 0.84 = 11.8
   7 × 0.10 = 0.7
   5 × 0.16 = 0.8
  → 13.3
  BA contribution = 13.3 × 0.75 × 0.19 = 1.9

Main + BA: 31.6 + 1.9 = 33.5

Divine Fury: 1d6 + 4   (avg 7.5, crit extra 3.5)
  7.5 × 0.97 = 7.3
  crit = 0.4
  → 7.7

DPR: 41.2
```

#### L9 — Rage +3, GWM +4, Brutal Strike available (1d10 + Forceful Blow: 15' push or 15' slow)

```
Reckless attack (×2): 2d6 + 5 + 3 + 4   (avg 19, crit extra 7)
  19 × 0.84 = 16.0
   7 × 0.10 = 0.7
   5 × 0.16 = 0.8
  → 17.5 per attack

Brutal Strike alternative (one attack, forgoes advantage):
  2d6 + 1d10 + 5 + 3 + 4   (avg 24.5, crit extra 12.5)
  24.5 × 0.60 = 14.7
  12.5 × 0.05 = 0.6
   5 × 0.40 = 2.0
  → 17.3

Bonus Action attack: 2d6 + 5 + 3   (avg 15, crit extra 7)
  → 14.1 per use
  No-BS BA contribution = 14.1 × 0.75 × 0.19 = 2.0
  With-BS BA contribution = 14.1 × 0.75 × 0.14 = 1.5

Main + BA (no BS):   17.5 × 2 + 2.0 = 36.9
Main + BA (with BS): 17.5 + 17.3 + 1.5 = 36.2

Divine Fury: 1d6 + 4   (avg 7.5)
  No BS: 7.5 × 0.97 = 7.3, crit 0.4 → 7.7
  BS:    7.5 × 0.94 + 0.4 = 7.5

DPR: 44.6 (Reckless path wins by 0.7)
```

#### L10 — DF scales

```
Main + BA: 36.9
Divine Fury: 1d6 + 5   (avg 8.5)
  8.5 × 0.97 = 8.2
  crit = 0.4
  → 8.6

DPR: 45.5
```

#### L11 — no change

```
DPR: 45.5
```

#### L12 — DF 1d6 + 6

```
Main + BA: 36.9
Divine Fury: 1d6 + 6   (avg 9.5)
  9.5 × 0.97 = 9.2
  crit = 0.4
  → 9.6

DPR: 46.5
```

#### L13 — GWM +5, Brutal Strike gains "Trip" (Disadv next save) or "+5 to be hit" rider options

```
Reckless attack (×2): 2d6 + 5 + 3 + 5   (avg 20, crit extra 7)
  20 × 0.84 = 16.8
   7 × 0.10 = 0.7
   5 × 0.16 = 0.8
  → 18.3 per attack

Brutal Strike alternative: 2d6 + 1d10 + 5 + 3 + 5   (avg 25.5, crit extra 12.5)
  25.5 × 0.60 = 15.3
  12.5 × 0.05 = 0.6
   5 × 0.40 = 2.0
  → 17.9

Bonus Action attack: 2d6 + 5 + 3   (avg 15, crit extra 7)
  → 14.1 per use
  No-BS BA contribution = 14.1 × 0.75 × 0.19 = 2.0
  With-BS BA contribution = 14.1 × 0.75 × 0.14 = 1.5

Main + BA (no BS):   18.3 × 2 + 2.0 = 38.6
Main + BA (with BS): 18.3 + 17.9 + 1.5 = 37.7

Divine Fury: 1d6 + 6   (avg 9.5)
  No BS: 9.5 × 0.97 + 0.4 = 9.6
  BS:    9.5 × 0.94 + 0.4 = 9.3

DPR: 48.2 (Reckless path wins)
```

#### L14 — DF 1d6 + 7

```
Main + BA: 38.6
Divine Fury: 1d6 + 7   (avg 10.5)
  10.5 × 0.97 = 10.2
  crit = 0.4
  → 10.6

DPR: 49.2
```

#### L15 — no change

```
DPR: 49.2
```

#### L16 — Rage +4

```
Reckless attack (×2): 2d6 + 5 + 4 + 5   (avg 21, crit extra 7)
  21 × 0.84 = 17.6
   7 × 0.10 = 0.7
   5 × 0.16 = 0.8
  → 19.1 per attack

Brutal Strike alternative: 2d6 + 1d10 + 5 + 4 + 5   (avg 26.5, crit extra 12.5)
  26.5 × 0.60 = 15.9
  12.5 × 0.05 = 0.6
   5 × 0.40 = 2.0
  → 18.5

Bonus Action attack: 2d6 + 5 + 4   (avg 16, crit extra 7)
  16 × 0.84 = 13.4
   7 × 0.10 = 0.7
   5 × 0.16 = 0.8
  → 14.9 per use
  No-BS BA contribution = 14.9 × 0.75 × 0.19 = 2.1
  With-BS BA contribution = 14.9 × 0.75 × 0.14 = 1.6

Main + BA (no BS):   19.1 × 2 + 2.1 = 40.3
Main + BA (with BS): 19.1 + 18.5 + 1.6 = 39.2

Divine Fury: 1d6 + 8   (avg 11.5)
  11.5 × 0.97 + 0.4 = 11.6

DPR: 51.9 (Reckless path)
```

#### L17 — GWM +6, Brutal Strike scales to 2d10 + can use **2** BS options on a hit  ← BS becomes optimal

```
Reckless attack (×2): 2d6 + 5 + 4 + 6   (avg 22, crit extra 7)
  22 × 0.84 = 18.5
   7 × 0.10 = 0.7
   5 × 0.16 = 0.8
  → 20.0 per attack

Brutal Strike alternative: 2d6 + 2d10 + 5 + 4 + 6   (avg 33, crit extra 18)
  33 × 0.60 = 19.8
  18 × 0.05 = 0.9
   5 × 0.40 = 2.0
  → 22.7

Bonus Action attack: 2d6 + 5 + 4   (avg 16, crit extra 7)
  → 14.9 per use
  No-BS BA contribution = 14.9 × 0.75 × 0.19 = 2.1
  With-BS BA contribution = 14.9 × 0.75 × 0.14 = 1.6

Main + BA (no BS):   20.0 × 2 + 2.1 = 42.1
Main + BA (with BS): 20.0 + 22.7 + 1.6 = 44.3  ← BS now wins by 2.2

Divine Fury: 1d6 + 8   (avg 11.5)  — using BS path
  11.5 × 0.94 = 10.8
  crit = 0.4
  → 11.2

DPR: 55.5 (Brutal Strike path)
```

#### L18 — DF 1d6 + 9

```
Main + BA (BS): 44.3
Divine Fury: 1d6 + 9   (avg 12.5)
  12.5 × 0.94 = 11.8
  crit = 0.4
  → 12.2

DPR: 56.5
```

#### L19 — Boon of Irresistible Offense (crit damage +21 → crit extras explode)

```
Reckless attack (×2): 2d6 + 5 + 4 + 6   (avg 22, crit extra 28)
  22 × 0.84 = 18.5
  28 × 0.10 = 2.8
   5 × 0.16 = 0.8
  → 22.1 per attack

Brutal Strike alternative: 2d6 + 2d10 + 5 + 4 + 6   (avg 33, crit extra 39)
  33 × 0.60 = 19.8
  39 × 0.05 = 2.0
   5 × 0.40 = 2.0
  → 23.8

Bonus Action attack: 2d6 + 5 + 4   (avg 16, crit extra 28)
  16 × 0.84 = 13.4
  28 × 0.10 = 2.8
   5 × 0.16 = 0.8
  → 17.0 per use
  No-BS BA contribution = 17.0 × 0.75 × 0.19 = 2.4
  With-BS BA contribution = 17.0 × 0.75 × 0.14 = 1.8

Main + BA (no BS):   22.1 × 2 + 2.4 = 46.6
Main + BA (with BS): 22.1 + 23.8 + 1.8 = 47.7  ← BS path

Divine Fury: 1d6 + 9   (avg 12.5)  — BS path
  12.5 × 0.94 = 11.8
  crit = 0.4
  → 12.2

DPR: 59.9 (BS path)
```

#### L20 — Str +7 (21), Graze 7; base hit 70% / 91% with advantage

```
Reckless attack (×2): 2d6 + 7 + 4 + 6   (avg 24, crit extra 28)
  24 × 0.91 = 21.8
  28 × 0.10 = 2.8
   7 × 0.16 = 1.1
  → 25.7 per attack

Brutal Strike alternative: 2d6 + 2d10 + 7 + 4 + 6   (avg 35, crit extra 39)
  35 × 0.70 = 24.5      (BS forgoes advantage: base 70% hit at this AC)
  39 × 0.05 = 2.0
   7 × 0.40 = 2.8
  → 29.3

Bonus Action attack: 2d6 + 7 + 4   (avg 18, crit extra 28)
  18 × 0.91 = 16.4
  28 × 0.10 = 2.8
   7 × 0.16 = 1.1
  → 20.3 per use
  No-BS BA contribution = 20.3 × 0.75 × 0.19 = 2.9
  With-BS BA contribution = 20.3 × 0.75 × 0.14 = 2.1

Main + BA (no BS):   25.7 × 2 + 2.9 = 54.3
Main + BA (with BS): 25.7 + 29.3 + 2.1 = 57.1  ← BS path

Divine Fury: 1d6 + 10   (avg 13.5)  — BS path, activation now 97%
  13.5 × 0.97 = 13.1
  crit = 0.4
  → 13.5

DPR: 70.6 (BS path)
```

**Engine integration:**

```python
BARBARIAN_ZEALOT_GREATSWORD_DPR = {
    1:  8.8,
    2:  11.3,
    3:  15.5,   # Divine Fury online
    4:  19.8,
    5:  34.4,   # Extra Attack
    6:  37.8,
    7:  37.8,
    8:  41.2,
    9:  44.6,   # Brutal Strike option (Reckless path still wins)
    10: 45.5,
    11: 45.5,
    12: 46.5,
    13: 48.2,
    14: 49.2,
    15: 49.2,
    16: 51.9,
    17: 55.5,   # Brutal Strike path now optimal (2d10 + 2 options)
    18: 56.5,
    19: 59.9,
    20: 70.6,
}
# Career average: 829.7 / 20 = 41.5

# Per-level "use Brutal Strike?" decision (False = Reckless wins)
BARBARIAN_ZEALOT_USE_BRUTAL_STRIKE = {
    level: level >= 17 for level in range(1, 21)
}
```

**Engine notes:**
- Zealot beats base Barbarian Greatsword (33.4 career) by +8.1 DPR through Divine Fury alone.
- DF activation chance is a function of attack count and per-attack hit probability — engine should compute `1 - P(miss)^n_attacks` at each level rather than hardcoding 0.84/0.97.
- DF crit chance is `P(first hitting attack is a crit)` = `crit_1 + miss_1 × crit_2` for two attacks. Worth a helper: `p_first_hit_is_crit(per_attack_hit, per_attack_crit, n_attacks)`.
- Brutal Strike crossover is at L17 (when it scales to 2d10 + 2 simultaneous options). Before that, Reckless advantage outweighs the +1d10.
- At L20, BS path uses base 70% hit on the BS attack while the regular Reckless attack still uses 91% — accurate modeling requires per-attack hit-chance tracking, not a single "build hit chance".
- The `0.4` crit-damage line in DF is invariant across Reckless/BS paths because the `1d6` DF bonus crits the same way regardless of underlying weapon path. Useful invariant for test fixtures.

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
