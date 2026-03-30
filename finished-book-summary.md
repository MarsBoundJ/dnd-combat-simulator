# The Finished Book: Mathematical & Statistical Foundations
**Source:** https://tomedunn.github.io/the-finished-book/  
**Author:** Tom Dunn (physicist)  
**Last Audited Against Live Site:** 2026-03-30  
**Coverage Status:** All articles enumerated and mapped below.

---

## Article Coverage Map

This document tracks every article on the site. Each section header links to its source.

### Theory
- [x] Effective HP and Damage
- [x] XP and Encounter Balancing
- [x] Calculating the Encounter Multiplier: part 1
- [x] Calculating the Encounter Multiplier: part 2 *(see Section V)*
- [x] Rounds of Combat Per Day
- [x] Valuing Conditions
- [x] Encounter Building in Pathfinder vs D&D *(comparative reference, not encoded)*
- [x] Encounter Building in Xanathar's Guide to Everything *(comparative reference, not encoded)*
- [x] Variability: Damage and Healing Rolls
- [x] Variability: Attacks
- [x] Variability: Saves
- [x] Variability: Combat
- [x] Variability: Encounter Difficulty
- [x] Initiative Probabilities
- [x] Random Encounter Tables *(not encoded — no simulator-relevant formulas)*
- [x] Calibrating Encounter Math *(methodology reference, findings folded into XP Approximations)*
- [x] XP Approximations

### Classes
- [x] Baseline Player Character Stats
- [x] Player Character XP
- [x] Daily XP and Encounter Difficulty
- [x] Balancing Short Adventuring Days
- [x] Magic Items and Encounter Balancing
- [x] Magic Items and Encounter Balancing: part 2
- [x] Stunning Strike *(specific ability analysis, findings folded into Conditions section)*

### Monsters
- [x] Monster Manual (2024)

---

## ⚠️ Engine Policy Notes (Read Before Using Formulas)

**XP Formula Selection:** The Finished Book derives three XP approximations of varying accuracy. This document encodes the **exponential form** (`1.077^(AC+AB-15)`) as the engine standard, which is the most accurate. The linear approximation and the official 5e published monster values are less accurate and are documented in Section VI for reference. See Section VI for the full accuracy analysis before deciding which formula to use in any given simulator subsystem.

**2014 vs 2024 Rules:** The majority of The Finished Book was written for 2014 rules. The 2024 Monster Manual article and XP Approximations article both have 2024-specific findings. Where rules differ, 2024-specific findings are flagged with `[2024]`.

**Baseline Assumptions:** Unless otherwise noted, all formulas assume:
- Baseline hit probability: ρ_h = 0.65
- Critical hit damage multiplier: d_crit = 1.5
- Standard four-PC party
- Non-legendary single monster unless specified

---

## I. Offensive Math (Hit, Damage, and DCs)

*Source: [Effective HP and Damage](https://tomedunn.github.io/the-finished-book/theory/effective-hp-and-damage/), [Baseline Player Character Stats](https://tomedunn.github.io/the-finished-book/classes/baseline-player-character-stats/)*

### 1. Attack Bonus and Save DC Scaling

Average Attack Bonus and Save DC scale linearly with player character level.

**Mathematical Formula:**
```latex
$$ AB \approx 4.6 + \frac{LV}{3} $$
$$ DC \approx 12.6 + \frac{LV}{3} $$
```

**Engine Representation (Python):**
```python
def calc_player_ab(level: int) -> float:
    return 4.6 + (level / 3.0)

def calc_player_dc(level: int) -> float:
    return 12.6 + (level / 3.0)
```

### 2. Exact Hit & Save Probability Formulas

The probability of a hit (ρ_h) or a failed save (ρ_f) are linear functions of the differential between offensive and defensive stats.

**Mathematical Formula:**
```latex
$$ \rho_h = 0.05(20 + AB - AC), \quad 0.05 \le \rho_h \le 0.95 $$
$$ \rho_f = 0.05(DC - SB - 1), \quad 0 \le \rho_f \le 1.0 $$
```

**Engine Representation (Python):**
```python
def calc_hit_probability(ab: float, ac: float) -> float:
    prob = 0.05 * (20.0 + ab - ac)
    return max(0.05, min(0.95, prob))

def calc_fail_probability(dc: float, sb: float) -> float:
    prob = 0.05 * (dc - sb - 1.0)
    return max(0.0, min(1.0, prob))
```

### 3. Single Target Damage Per Round (DPR) Scaling

**Mathematical Formula:**
```latex
$$ DPR_{PC} \approx 7 + 2 \cdot LV $$
$$ DPR_N \approx \begin{cases} 6 + 6 \cdot CR & CR < 20 \\ 132 + 12 (CR - 20) & CR \ge 20 \end{cases} $$
$$ DPR_L \approx \begin{cases} 7.5 + 7.5 \cdot CR & CR < 20 \\ 165 + 15 (CR - 20) & CR \ge 20 \end{cases} $$
```

**Engine Representation (Python):**
```python
def calc_pc_baseline_dpr(level: int) -> float:
    return 7.0 + (2.0 * level)

def calc_monster_dpr(cr: float, is_legendary: bool = False) -> float:
    if not is_legendary:
        return 6.0 + 6.0 * cr if cr < 20 else 132.0 + 12.0 * (cr - 20)
    else:
        return 7.5 + 7.5 * cr if cr < 20 else 165.0 + 15.0 * (cr - 20)
```

---

## II. Defensive Math (AC, Saves, and HP)

*Source: [Effective HP and Damage](https://tomedunn.github.io/the-finished-book/theory/effective-hp-and-damage/), [Baseline Player Character Stats](https://tomedunn.github.io/the-finished-book/classes/baseline-player-character-stats/)*

### 1. Armor Class and Hit Point Scaling

**Mathematical Formula:**
```latex
$$ AC_{PC} \approx 14.7 + \frac{LV}{6} $$
$$ HP_{PC} \approx 1 + 7 \cdot LV $$
```

**Engine Representation (Python):**
```python
def calc_player_ac(level: int) -> float:
    return 14.7 + (level / 6.0)

def calc_player_hp(level: int) -> float:
    return 1.0 + (7.0 * level)
```

### 2. Saving Throw Bonus Scaling and AC Relation

For player characters, SB scales with level. For monsters, SB is tied directly to AC.

**Mathematical Formula:**
```latex
$$ SB_{PC} \approx 1.5 + \frac{LV}{5} $$
$$ SB_{Monster} \approx AC - 14 $$
```

**Engine Representation (Python):**
```python
def calc_player_save_bonus(level: int) -> float:
    return 1.5 + (level / 5.0)

def calc_monster_sb_from_ac(ac: float) -> float:
    """Monster save bonus is derived from AC, not level."""
    return ac - 14.0
```

> **Engine Note:** The `SB ≈ AC - 14` relation is derived from regression across published monsters. It is used to argue the relative strength of save-targeting vs. AC-targeting attacks at a given CR. It is the correct formula for monster stat blocks; do not apply it to PCs.

---

## III. Multipliers & Effective Stats (The Core Engine)

*Source: [Effective HP and Damage](https://tomedunn.github.io/the-finished-book/theory/effective-hp-and-damage/)*

This is the translation layer from raw stats into the **Effective Hit Points (eHP)** and **Effective DPR (eDPR)** values that the rest of the engine runs on. All XP and encounter difficulty calculations flow from these.

### 1. Normalizing Offensive and Defensive Stats

Raw stats are normalized against baseline values to allow direct cross-entity comparison.

**Mathematical Formula:**
```latex
$$ A'_B = \begin{cases} AB - 4 & \text{(attacks)} \\ DC - 12 & \text{(saves)} \end{cases} $$
$$ A'_C = \begin{cases} AC - 12 & \text{(attacks)} \\ SB - (-2) & \text{(saves)} \end{cases} $$
```

**Engine Representation (Python):**
```python
def normalize_offense(val: float, is_save: bool = False) -> float:
    """Normalize AB or DC against baseline."""
    return val - 12.0 if is_save else val - 4.0

def normalize_defense(val: float, is_save: bool = False) -> float:
    """Normalize AC or SB against baseline."""
    return val - (-2.0) if is_save else val - 12.0
```

### 2. Effective Attack/Save Damage (Single Ability)

The expected damage of a single attack or save ability, adjusted for the difference between the attacker's normalized offensive stat and the target's normalized defensive stat.

**Mathematical Formula:**
```latex
$$ D_a = 0.65 \, D \left[ 1 + \frac{A'_B - A'_C}{13} \right] $$
```

**Engine Representation (Python):**
```python
def calc_effective_damage(raw_damage: float, a_prime_b: float, a_prime_c: float) -> float:
    return 0.65 * raw_damage * (1.0 + (a_prime_b - a_prime_c) / 13.0)
```

### 3. Multi-Ability Effective DPR (Weighted Aggregation)

When a creature has multiple attack or save abilities, each is weighted by its fraction of the total unmitigated DPR.

**Mathematical Formula:**
```latex
$$ DPR_a = 0.65 \, DPR_t \left[ 1 + \sum_i dpr_i \frac{A'_{B,i} - A'_{C,i}}{13} \right] $$
```
where `DPR_t = Σ DPR_i` (sum assuming all hit/fail) and `dpr_i = DPR_i / DPR_t`.

**Engine Representation (Python):**
```python
def calc_multi_ability_edpr(
    dpr_list: list[float],
    a_prime_b_list: list[float],
    a_prime_c_list: list[float]
) -> float:
    dpr_total = sum(dpr_list)
    if dpr_total == 0:
        return 0.0
    weighted_accuracy = sum(
        (dpr / dpr_total) * (ab - ac) / 13.0
        for dpr, ab, ac in zip(dpr_list, a_prime_b_list, a_prime_c_list)
    )
    return 0.65 * dpr_total * (1.0 + weighted_accuracy)
```

### 4. Effective AC and Effective AB (eAC / eAB)

Weighted effective totals combining multiple abilities into abstract eAC and eAB scalars.

**Mathematical Formula:**
```latex
$$ eAC = \sum_i (dpr_i \cdot A'_{C,i}) + 12 $$
$$ eAB = \sum_i (dpr_i \cdot A'_{B,i}) + 4 $$
```

**Engine Representation (Python):**
```python
def calc_effective_ac(damage_fractions: list[float], a_prime_c_list: list[float]) -> float:
    return sum(frac * ac for frac, ac in zip(damage_fractions, a_prime_c_list)) + 12.0

def calc_effective_ab(damage_fractions: list[float], a_prime_b_list: list[float]) -> float:
    return sum(frac * ab for frac, ab in zip(damage_fractions, a_prime_b_list)) + 4.0
```

### 5. Effective HP and Effective DPR (Terminal Translation)

The final effective values. Base constant `c ≈ 1.077` is derived from the 0.65 hit baseline.

**Mathematical Formula:**
```latex
$$ eHP = \frac{1}{\sqrt{0.65}} \, HP \cdot 1.077^{\,eAC - 12} $$
$$ eDPR = \sqrt{0.65} \, DPR_t \cdot 1.077^{\,eAB - 4} $$
```

**Engine Representation (Python):**
```python
import math

def calc_ehp(hp: float, eac: float) -> float:
    return (1.0 / math.sqrt(0.65)) * hp * math.pow(1.077, eac - 12.0)

def calc_edpr(dpr_total: float, eab: float) -> float:
    return math.sqrt(0.65) * dpr_total * math.pow(1.077, eab - 4.0)
```

---

## IV. XP, Encounter Difficulty, and Simulation Variables

*Source: [XP and Encounter Balancing](https://tomedunn.github.io/the-finished-book/theory/xp-and-encounter-balancing/), [XP Approximations](https://tomedunn.github.io/the-finished-book/theory/xp-approximations/)*

### 1. XP from Stat Blocks

XP is proportional to the product of eHP and eDPR. This is the engine's fundamental valuation unit for any creature.

**Mathematical Formula (Exponential — Engine Standard):**
```latex
$$ XP \propto HP \cdot DPR_t \cdot 1.077^{\,(eAB - 4) + (eAC - 12)} $$
$$ XP \propto eHP \cdot eDPR $$
```

**Engine Representation (Python):**
```python
def calculate_xp_from_stats(
    hp: float,
    dpr_total: float,
    eab: float,
    eac: float,
    xp_constant: float = 1.0
) -> float:
    return xp_constant * hp * dpr_total * math.pow(1.077, (eab - 4.0) + (eac - 12.0))
```

### 2. XP Formula Variants and Accuracy (Critical Policy Decision)

Three XP approximations exist with different accuracy profiles. **This is not a trivial distinction.** The engine must pick one and apply it consistently.

| Approximation | Formula for F | Best Accuracy Range | Notes |
|---|---|---|---|
| **Exponential (recommended)** | `1.077^(AC+AB-15)` | CR ±15 from party level, within ~10% | Engine standard |
| Linear | `(AC+AB-2)/13` | CR ±4 from party level | Undervalues high-CR/high-level differences |
| Official 5e published XP | (no explicit formula) | CR within [-2, 1] of party level | Flat AC/AB dependence for CR ≤ 20 |

> **[2024] Key Finding:** Published monsters CR 20 and below have essentially no dependence on AC + AB in their official XP values, while monsters above CR 20 follow the linear approximation. The 2024 encounter building rules work **without** an encounter multiplier because a multiplier effect was baked into the published XP values themselves. If your simulator uses the exponential XP formula (recommended), you **must** apply an explicit encounter multiplier. If it uses published 5e XP values, applying the DMG encounter multiplier table will double-count difficulty.

**Engine Representation (Python):**
```python
def xp_accuracy_factor_exponential(ac: float, ab: float) -> float:
    """Exponential form — most accurate across full CR range."""
    return math.pow(1.077, ac + ab - 15.0)

def xp_accuracy_factor_linear(ac: float, ab: float) -> float:
    """Linear approximation — less accurate at high CR."""
    return (ac + ab - 2.0) / 13.0
```

### 3. Encounter Difficulty (d) Definition

Encounter difficulty is measured as the fraction of total PC HP the monsters are expected to deal before being defeated.

**Mathematical Formula:**
```latex
$$ d \equiv \frac{D_{NPCs}^{total}}{HP_{PCs}^{total}} $$
$$ d_{XP} = \frac{XP_{NPCs}}{4 \cdot XP_{PCs}} $$
```

**Engine Representation (Python):**
```python
def calc_encounter_difficulty_xp(xp_npcs: float, xp_pcs_per_character: float, party_size: int = 4) -> float:
    return xp_npcs / (party_size * xp_pcs_per_character)
```

### 4. Rounds to Win & Encounter Duration

**Mathematical Formula:**
```latex
$$ Rounds_{Win} \approx 2.5 \ \text{rounds} $$
$$ Rounds_{TPK} \approx 7.0 \ \text{rounds} $$
$$ \text{Expected damage taken} \approx 35.7\% \ \text{of party HP} $$
```

**Engine Representation (Python):**
```python
ENCOUNTER_DURATION_ROUNDS = 2.5
TPK_ROUNDS = 7.0
EXPECTED_DAMAGE_TAKEN_PCT = 0.357
```

> **Engine Note:** These are expected values. See Section VII (Variability) for the distributions around them.

---

## V. Encounter Multiplier

*Source: [Encounter Multiplier: part 1](https://tomedunn.github.io/the-finished-book/theory/encounter-multiplier-p1/), [Encounter Multiplier: part 2](https://tomedunn.github.io/the-finished-book/theory/encounter-multiplier-p2/)*

The encounter multiplier accounts for the fact that monsters in groups live longer than they would individually, because the PCs cannot kill all monsters simultaneously. Its value depends not on monster count alone, but on **how the PCs choose to engage**.

> **[2024] Warning:** As noted in Section IV, the 2024 rules incorporate a de facto multiplier into published XP values. If using official 5e XP values for monsters, do not also apply the encounter multiplier or you will double-count difficulty.

### 1. General Encounter XP Formula

**Mathematical Formula:**
```latex
$$ EM = \left(\frac{XP^{wt}_{NPCs}}{XP^{tot}_{NPCs}}\right) \cdot \left(\frac{4 \cdot XP^{tot}_{PCs}}{XP^{wt}_{PCs}}\right) $$
```

For a standard four-PC party this simplifies to:
```latex
$$ EM = \frac{XP^{wt}_{NPCs}}{XP^{tot}_{NPCs}} $$
```

where `XP^{wt}_{NPCs} = Σ_{i,j} W_{ij} · XP_{ij}` and `XP_{ij} = (1/4) · eHP_i · eDPR_j`.

### 2. Single Target Strategy (Focus-Fire)

PCs defeat one monster at a time. For N identical NPCs, averaged across all kill orders:

**Mathematical Formula:**
```latex
$$ EM = \frac{(N + 1)}{2} $$
```

**Weights (ordered kill):**
```latex
$$ W_{ij} = \begin{cases} 1 & i \le j \\ 0 & i > j \end{cases} $$
```

**Engine Representation (Python):**
```python
def encounter_multiplier_single_target(n_identical_npcs: int) -> float:
    """Average EM assuming focus-fire on identical NPCs."""
    return (n_identical_npcs + 1) / 2.0
```

> **Engine Note:** This formula matches the 2014 DMG table exactly for N ≤ 3. For N > 3, this is *harder* than the DMG suggests because the DMG assumes some AoE capability. Groups without AoE can see difficulty underestimated by up to 50%.

### 3. Multi-Target (Full AoE) Strategy

PCs damage all monsters simultaneously. `eff_MT` is the ratio of per-target AoE damage to single-target damage.

**Mathematical Formula:**
```latex
$$ EM = \frac{1}{eff_{MT}} $$
```

For spells vs. non-resistant targets: `eff_MT ≈ 0.70`, so `EM ≈ 1.43`.
For spells vs. resistant targets: `eff_MT ≈ 0.35`, so `EM ≈ 2.86`.

**Engine Representation (Python):**
```python
def encounter_multiplier_aoe(eff_mt: float) -> float:
    """EM for pure AoE strategy. eff_mt = per-target AoE DPR / single-target DPR."""
    return 1.0 / eff_mt

EFF_MT_SPELLS_NORMAL = 0.70
EFF_MT_SPELLS_RESISTANT = 0.35
```

### 4. Mixed Strategy (AoE then Focus-Fire)

The most realistic scenario. PCs open with AoE, then transition to single-target. `d_MT_i = AoE damage dealt per target / eHP_i`.

**Mathematical Formula (N identical NPCs):**
```latex
$$ EM = \frac{(N + 1)(1 - d_{MT})}{2} + \frac{d_{MT}}{eff_{MT}} $$
```

**Engine Representation (Python):**
```python
def encounter_multiplier_mixed(
    n_identical_npcs: int,
    d_mt: float,           # fraction of each monster's eHP dealt by AoE
    eff_mt: float          # AoE per-target DPR efficiency vs single-target
) -> float:
    single_target_component = ((n_identical_npcs + 1) * (1.0 - d_mt)) / 2.0
    aoe_component = d_mt / eff_mt
    return single_target_component + aoe_component
```

### 5. PC-Side Encounter Multiplier

Part 2 of the Encounter Multiplier series covers how NPC strategy and party size affect the multiplier from the PC side. The general formula for the full two-sided EM is:

```latex
$$ EM_{full} = \left(\frac{XP^{wt}_{NPCs}}{XP^{tot}_{NPCs}}\right) \cdot \left(\frac{4 \cdot XP^{tot}_{PCs}}{XP^{wt}_{PCs}}\right) $$
```

The second term `(4 · XP^{tot}_{PCs}) / (XP^{wt}_{PCs})` adjusts for how NPC strategy distributes damage across the PC party. A party of 4 identical PCs where monsters split damage evenly sets this term to 1.0, which is the standard assumption. Monster focus-fire on a single PC increases this term, making the encounter harder.

---

## VI. PC-Side XP and Daily Resource Economy

*Source: [Player Character XP](https://tomedunn.github.io/the-finished-book/classes/xp-and-player-characters/), [Daily XP and Encounter Difficulty](https://tomedunn.github.io/the-finished-book/classes/daily-xp-and-encounter-difficulty/), [Balancing Short Adventuring Days](https://tomedunn.github.io/the-finished-book/classes/short-adventuring-days/)*

This section is essential if the simulator models anything beyond a single isolated encounter: long rest economy, attrition across multiple fights, or resource depletion.

### 1. Player Character XP Formula

```latex
$$ XP_{PC} = eHP \cdot eDPR $$
$$ XP_{PC} \approx HP \cdot DPR_{hit} \cdot \left(\frac{AC + AB - 2}{13}\right) $$
```

**Engine Representation (Python):**
```python
def calc_pc_xp(hp: float, dpr_hit: float, ac: float, ab: float) -> float:
    """
    Linear approximation for PC XP.
    DPR_hit should reflect single-target damage only (AoE is handled by EM).
    """
    return hp * dpr_hit * ((ac + ab - 2.0) / 13.0)
```

### 2. Encounter XP Thresholds (as % of PC Encounter Budget)

The DMG difficulty thresholds correspond to stable percentages of a PC's per-encounter XP budget (half their daily budget):

| Difficulty | % of Encounter XP Budget |
|---|---|
| Easy | ~15% |
| Medium | ~30% |
| Hard | ~45% |
| Deadly | ~70% |

### 3. Daily HP Budget (Adventuring Day Economy)

Across a full adventuring day, a PC's effective HP includes hit dice recovery from short rests:

**Mathematical Formula:**
```latex
$$ HP_{daily} = HP_{max} + LV \cdot (HD + CON) + \sum_{rounds} \Delta HP_i $$
```

**Engine Representation (Python):**
```python
def calc_pc_daily_hp(
    hp_max: float,
    level: int,
    hit_die_avg: float,   # e.g. 4.5 for d8
    con_modifier: float,
    in_combat_healing: float = 0.0
) -> float:
    """
    Effective daily HP including short rest hit dice recovery.
    A PC's daily XP ≈ 2× their per-encounter XP due to short rest recovery.
    """
    return hp_max + level * (hit_die_avg + con_modifier) + in_combat_healing
```

> **Key Finding:** A PC's average encounter XP is approximately half of their adventuring day XP budget. Martial classes (barbarian, fighter, paladin) have significantly higher eHP than spellcasters at equivalent levels, making them worth more XP as encounter participants. Spellcasters compensate through multi-target capabilities not reflected in single-target XP.

### 4. Short Adventuring Day Scaling

When the adventuring day contains fewer than the standard number of encounters, XP thresholds must be recalibrated. Fewer encounters mean PCs arrive more resourced, making each encounter effectively harder for the DM to balance. This is not encoded as a single formula but as a lookup/scaling policy:

- **1 encounter/day:** XP thresholds increase significantly (monsters see a near-full-resource party).
- **2 encounters/day:** Moderate threshold increase.
- **Standard day (6-8 encounters):** Baseline thresholds apply.

### 5. Magic Items and Encounter Difficulty

*Source: [Magic Items and Encounter Balancing](https://tomedunn.github.io/the-finished-book/classes/magic-items-and-encounter-balancing/), [part 2](https://tomedunn.github.io/the-finished-book/classes/magic-items-and-encounter-balancing-p2/)*

Magic items shift PC XP by modifying eHP and eDPR. The key findings:

- Items that increase AC raise eHP exponentially (via the 1.077 base), not linearly.
- Items that increase AB raise eDPR exponentially.
- The combination of a +1 weapon and +1 armor produces a significantly larger XP shift than their individual contributions suggest.

> **Engine Policy:** When loading character sheets from Foundry, magic items that grant flat AC or AB bonuses should be fed into `calc_ehp()` and `calc_edpr()` through modified eAC/eAB values. Items with conditional effects (e.g., advantage on certain saves) should use the condition valuation multipliers from Section VIII.

---

## VII. Rounds Per Day and Initiative

*Source: [Rounds of Combat Per Day](https://tomedunn.github.io/the-finished-book/theory/rounds-per-day/), [Initiative Probabilities](https://tomedunn.github.io/the-finished-book/theory/initiative-probabilities/)*

### 1. Rounds Per Encounter by Difficulty

The number of rounds in an encounter is not fixed at 2.5 — that is the *expected value for a standard encounter*. It varies with difficulty:

| Difficulty | Expected Rounds |
|---|---|
| Easy | ~1.5 |
| Medium | ~2.0 |
| Hard | ~2.5–3.0 |
| Deadly | ~3.0–4.0 |

These values feed into per-encounter XP calculations (Section VI).

### 2. Initiative Win Probability

The probability that side A (with initiative modifier `mod_A`) wins initiative against side B (with modifier `mod_B`), assuming both roll a d20:

**Mathematical Formula:**
```latex
$$ P(A\ wins) = \frac{20 + mod_A - mod_B}{20}, \quad \text{clamped to } [0.05, 0.95] $$
```

**Engine Representation (Python):**
```python
def calc_initiative_win_probability(mod_a: float, mod_b: float) -> float:
    """Probability that A wins initiative against B."""
    prob = (20.0 + mod_a - mod_b) / 20.0
    return max(0.05, min(0.95, prob))
```

> **Engine Note:** Going first is significant for nova strategies and alpha strikes. The initiative system gates whether PC resources land before monster actions. The full article includes multi-party ordering probabilities (who goes 1st, 2nd, Nth) for groups larger than two.

---

## VIII. Condition Valuation

*Source: [Valuing Conditions](https://tomedunn.github.io/the-finished-book/theory/valuing-conditions/)*

Conditions are valued by converting their mechanical components into equivalent AB, AC, DC, or SB adjustments, then into percent damage changes.

### 1. Component Values (Baseline Assumptions: ρ_h = 0.65, d_crit = 1.5)

| Component | Effective Stat Change | % Damage Change |
|---|---|---|
| Advantage on attacks (from target) | +5 AB | +37.2% damage dealt |
| Disadvantage on attacks (from target) | −5 AB | −37.2% damage dealt |
| Auto-crit on hit (against target) | +6 AB | +44.4% damage dealt |
| Disadvantage on saves (against target) | −(2.3–4.5) SB | +(13.8–35.0)% damage taken |
| Auto-fail saves (against target) | −(3.5–7.0) SB | +(21.2–53.8)% damage taken |
| Inability to take actions | 0 DPR | −100% damage dealt |
| Inability to move | Context-dependent | — |

### 2. Condition Reference Table

| Condition | Damage FROM Target | Damage AGAINST Target |
|---|---|---|
| Blinded | −37% (attacks) | +37% (attacks) |
| Frightened | −37% (attacks) | — |
| Incapacitated | −100% (all) | — |
| Invisible | +37% (attacks) | −37% (attacks) |
| Paralyzed | −100% (all) | +98% (atk), +(21–54)% (Str/Dex saves) |
| Petrified | −100% (all) | −35% (atk), −(27–55)% (Str/Dex saves) |
| Poisoned | −37% (attacks) | — |
| Prone | −37% (attacks) | +37% (melee), −37% (ranged) |
| Restrained | −37% (attacks) | +37% (atk), +(14–35)% (Dex saves) |
| Stunned | −100% (all) | +37% (atk), +(21–54)% (Str/Dex saves) |
| Unconscious | −100% (all) | +98% (atk), +(21–54)% (Str/Dex saves) |

### 3. Condition → eHP/eDPR Translation

**Mathematical Formula (advantage on attacks):**
```latex
$$ \Delta AB_{adv} = 20 \left( \rho_h(1 - \rho_h - 2\rho_c) + d_{crit} \cdot \rho_c(1 - \rho_c) \right) $$
```

**Mathematical Formula (disadvantage on saves, no-damage-on-save variant):**
```latex
$$ \Delta DC_{dis} = 20 \cdot \rho_f (1 - \rho_f) $$
```

**Engine Representation (Python):**
```python
def condition_delta_ab_advantage(p_hit: float, p_crit: float, d_crit: float = 1.5) -> float:
    """Effective AB increase from advantage on attack rolls."""
    return 20.0 * (p_hit * (1 - p_hit - 2 * p_crit) + d_crit * p_crit * (1 - p_crit))

def condition_delta_ab_disadvantage(p_hit: float, p_crit: float, d_crit: float = 1.5) -> float:
    """Effective AB decrease from disadvantage on attack rolls."""
    return -condition_delta_ab_advantage(p_hit, p_crit, d_crit)

def condition_delta_dc_disadvantage_save(p_fail: float, d_save: float = 0.0) -> float:
    """Effective DC increase from disadvantage on saving throws."""
    return 20.0 * (1.0 - d_save) * p_fail * (1.0 - p_fail)

def condition_delta_dc_auto_fail_save(p_fail: float, d_save: float = 0.0) -> float:
    """Effective DC increase from automatically failing a saving throw."""
    return 20.0 * (1.0 - d_save) * (1.0 - p_fail)
```

> **Engine Policy:** Conditions are not static. Their value scales with the CR of the target and the level of the caster. A Stun applied by a PC against a CR 20 monster is worth more in absolute DPR than the same Stun applied by a monster against a PC, because the monster has higher raw DPR. Feed condition modifiers back into eHP/eDPR calculations rather than treating them as fixed bonuses.

---

## IX. Variability

*Source: [Variability: Damage and Healing Rolls](https://tomedunn.github.io/the-finished-book/theory/variability-damage-healing-rolls/), [Variability: Attacks](https://tomedunn.github.io/the-finished-book/theory/variability-attacks/), [Variability: Saves](https://tomedunn.github.io/the-finished-book/theory/variability-saves/), [Variability: Combat](https://tomedunn.github.io/the-finished-book/theory/variability-combat/), [Variability: Encounter Difficulty](https://tomedunn.github.io/the-finished-book/theory/variability-encounter-difficulty/)*

All formulas in Sections I–VIII describe **expected values**. This section describes the **distributions around those values**. The engine must decide whether to use deterministic expected values or stochastic simulation — this section provides the framework for either.

### 1. Variance in DPR (Attack Rolls)

For a single attack with hit probability `p_h`, crit probability `p_c`, and on-hit damage `D_h`:

**Mathematical Formula:**
```latex
$$ \sigma^2_{DPR} = \sigma^2_{hit} + \rho_h \cdot \sigma^2_{damage} $$
```

The variance has two components: the binary hit/miss randomness and the damage roll randomness. Multiple attacks per round reduce relative variance (Central Limit Theorem).

**Engine Representation (Python):**
```python
def calc_attack_dpr_variance(
    p_hit: float,
    p_crit: float,
    d_hit_mean: float,
    d_hit_variance: float,
    d_crit_mean: float
) -> float:
    """Variance of damage from a single attack."""
    d_avg = p_hit * d_hit_mean + p_crit * d_crit_mean
    hit_variance = (p_hit + p_crit) * (1 - p_hit - p_crit) * d_avg**2
    damage_variance = (p_hit + p_crit) * d_hit_variance
    return hit_variance + damage_variance
```

### 2. Variance in Combat Outcome

The distribution of rounds to defeat a monster is approximately normal around the 2.5 round expected value. The standard deviation of encounter duration grows with encounter difficulty.

| Difficulty | P(win) | P(TPK) |
|---|---|---|
| Easy | ~95% | ~0% |
| Medium | ~75% | ~5% |
| Hard | ~50% | ~15% |
| Deadly | ~25% | ~30% |

### 3. Encounter Difficulty Probability

**Engine Policy Decision:** The engine must choose one of two modes:

**Mode A — Deterministic (Expected Value):** Use mean eHP, eDPR, and expected rounds. Fastest. Appropriate for encounter *design* tools and XP balance validation.

**Mode B — Stochastic (Monte Carlo):** Run N simulated combats, sample from damage distributions each round. Produces win/loss probability distributions. Appropriate for the simulator's actual combat resolution.

```python
# Mode A stub
def resolve_encounter_deterministic(party_ehp: float, party_edpr: float,
                                    monster_ehp: float, monster_edpr: float) -> dict:
    rounds_to_kill_monster = monster_ehp / party_edpr
    rounds_to_tpk = party_ehp / monster_edpr
    return {
        "expected_rounds": min(rounds_to_kill_monster, rounds_to_tpk),
        "party_wins": rounds_to_kill_monster < rounds_to_tpk,
        "damage_taken_pct": rounds_to_kill_monster * monster_edpr / party_ehp
    }

# Mode B: run many instances of the turn-by-turn simulator and aggregate.
```

---

## X. Known Coverage Gaps and Open Questions

These are areas where The Finished Book's math is incomplete, does not extend, or conflicts with real-world edge cases. The simulator must have a written policy for each before the relevant algorithm is written.

| Gap | Description | Recommended Policy |
|---|---|---|
| Legendary Actions / Lair Actions | Not modeled in eHP/eDPR framework. Legendary DPR scaling is given (Section I.3) but their action economy bonus is not formalized. | Treat legendary actions as bonus DPR added to `DPR_L`. Lair actions as +1 effective "monster." Flag for future revision. |
| Reaction Attacks (e.g., Opportunity Attacks) | No formula. | Ignore in v1. Add as optional eDPR modifier in v2. |
| Concentration Economy | No formula for the value of maintaining concentration vs. being hit. | Use condition valuation framework as proxy: concentration break = lost condition value per remaining round. |
| Subclass Effects | PC XP values underestimate by ~10% without subclasses. | Apply a flat 1.10 multiplier to PC XP for subclassed characters in v1. |
| Multi-target Spells (variable targets) | eff_MT assumes fixed target count. Variable AoE (e.g., Fireball) needs target count as input. | Parameterize `eff_mt` as a function of `n_targets`. Use `0.70 * min(n_targets, 4) / 4` as a first approximation. |
| Healing Spells | Not covered in offensive/defensive framework. | Value healing as eHP restoration: 1 HP healed = 1/√0.65 effective HP. |
| 2024 Rules Changes | Most articles are 2014-based. 2024 Monster Manual article provides updated monster scaling data. | Use 2024 monster stat regressions from Section I.3 for all monster-side calculations. Flag PC-side formulas as 2014-derived until updated articles publish. |
