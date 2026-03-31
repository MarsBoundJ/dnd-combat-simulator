# eHP Action Framework

**Status:** 🟡 Specification complete — implementation pending  
**Last updated:** 2026-03-30  
**Location in engine:** `engine/math/conditions.py` + `engine/ai/decision.py`

---

## Core Insight

Every action in D&D 5e is an HP transaction. The AI's job is to find the action that produces the greatest net eHP swing in the actor's favor.

```
Total Action Value = Offensive eHP + Defensive eHP − Opportunity Cost
```

This framework extends The Finished Book's eHP/eDPR machinery from stat blocks to
*actions*, allowing the AI to compare any action — attack, heal, cast Fireball, cast
Hypnotic Pattern, Dodge, Disengage — on a single numeric scale.

**Offensive eHP:** damage dealt to enemies, expressed as expected HP removed  
**Defensive eHP:** damage prevented for allies, expressed as expected HP preserved  
**Opportunity Cost:** resource cost of the action (spell slots, HP, action economy)

---

## The Master Formula

```python
def action_value(action, actor, state) -> float:
    """
    Returns the total eHP value of an action in the current combat state.
    Positive = good for the actor. Negative = bad.
    All values in expected HP units.
    """
    offensive_ehp  = calc_offensive_value(action, actor, state)
    defensive_ehp  = calc_defensive_value(action, actor, state)
    opportunity_cost = calc_resource_cost(action, actor, state)

    raw_value = offensive_ehp + defensive_ehp - opportunity_cost

    # Behavioral weight from Ammann pillar (see ammann-behavior-framework.md)
    return raw_value * actor.aggression_coefficient
```

The AI enumerates all valid actions for the current actor, scores each with
`action_value()`, and executes the highest-scoring action.

---

## Effect Type Formulas

### 1. Direct Damage

```
Offensive eHP = Expected Damage × Hit/Fail Probability × Number of Targets
```

```python
def calc_direct_damage_value(damage_mean: float, hit_prob: float,
                              n_targets: int = 1) -> float:
    return damage_mean * hit_prob * n_targets
```

### 2. Direct Healing

```
Defensive eHP = Expected Healing × Number of Targets
```

Healing is always certain (no roll to hit), so probability = 1.0.
Priority weighting: healing a target at 10% HP is worth more than healing a target
at 80% HP. Apply a desperation multiplier:

```python
def calc_healing_value(healing_mean: float, target_hp_fraction: float,
                        n_targets: int = 1) -> float:
    desperation = 1.0 + max(0.0, (0.5 - target_hp_fraction))  # bonus below 50% HP
    return healing_mean * desperation * n_targets
```

### 3. Offensive Buff (Advantage / Attack Bonus for Allies)

Increases ally DPR by raising hit probability. Value is the additional damage
generated over the buff's expected duration.

```
Offensive eHP = Ally DPR × Δhit_probability × Expected Rounds Remaining
```

```python
def calc_offensive_buff_value(ally_dpr: float, delta_hit_prob: float,
                               expected_rounds: float = 2.5) -> float:
    return ally_dpr * delta_hit_prob * expected_rounds
```

**Reference values:**
- Bless (+1d4 to hit ≈ +12.5% hit chance): `ally_dpr × 0.125 × rounds`
- Advantage (≈ +20–25% hit chance at baseline): `ally_dpr × 0.225 × rounds`
- Faerie Fire (advantage on attacks against target): multiply by number of attackers

### 4. Defensive Buff (Bonus to AC / Saving Throws)

Reduces enemy hit probability against allies. Value is damage prevented over
the buff's expected duration.

```
Defensive eHP = Ally Expected Damage Taken × Δmiss_probability × Expected Rounds
```

```python
def calc_defensive_buff_value(ally_damage_taken_per_round: float,
                               delta_miss_prob: float,
                               expected_rounds: float = 2.5) -> float:
    return ally_damage_taken_per_round * delta_miss_prob * expected_rounds
```

**Reference values:**
- Shield of Faith (+2 AC ≈ +10% miss chance): `damage_taken × 0.10 × rounds`
- Paladin Aura +3 to saves (≈ +15% save chance): `aoe_damage × 0.15 × party_size`
- Blur (disadvantage on attacks ≈ −20% hit chance): `damage_taken × 0.20 × rounds`

### 5. Action Denial / Hard Control

Completely removes a creature's action(s) for one or more rounds.
Value is the DPR that creature would have dealt, now set to zero.

```
Defensive eHP = Enemy DPR × Fail Probability × Expected Rounds Controlled
```

```python
def calc_action_denial_value(enemy_dpr: float, fail_prob: float,
                              expected_rounds_controlled: float,
                              n_targets: int = 1) -> float:
    return enemy_dpr * fail_prob * expected_rounds_controlled * n_targets
```

**Critical caveat — time horizon:**  
Expected rounds controlled must account for:
- Concentration breaking (party hits the controlled creature → spell ends)
- Legendary Resistance (burns through control in round 1)
- Creature's own saves on subsequent rounds (for ongoing save effects)

```python
def expected_control_duration(base_duration: float,
                               concentration_required: bool,
                               party_targeting_discipline: float,  # 0–1
                               legendary_resistances: int) -> float:
    """
    Estimates how many rounds a control effect actually lasts.
    party_targeting_discipline: 1.0 = party never hits controlled targets
                                0.0 = party randomly hits controlled targets
    """
    if legendary_resistances > 0:
        return 0.0  # Legendary creature burns resistance — control fails
    
    effective_duration = base_duration
    if concentration_required:
        # Discount for risk of concentration breaking
        effective_duration *= party_targeting_discipline
    return effective_duration
```

### 6. Soft Control / Movement Denial

Reduces enemy speed or imposes conditions that prevent reaching targets.
Value is the fraction of DPR lost due to movement restriction.

```
Defensive eHP = Enemy DPR × Movement Denial Fraction × Expected Rounds
```

```python
def calc_movement_denial_value(enemy_dpr: float,
                                denial_fraction: float,
                                expected_rounds: float = 2.5) -> float:
    """
    denial_fraction: 0.0 = no effect, 1.0 = enemy cannot reach any target
    """
    return enemy_dpr * denial_fraction * expected_rounds
```

**Examples:**
- Web (halved speed, difficult terrain): denial_fraction ≈ 0.5 for melee enemies
- Plant Growth (10 ft movement): denial_fraction ≈ 0.8 for enemies > 15 ft away
- Grease (prone on failed save): denial_fraction ≈ 0.3 (costs movement to stand)

### 7. Debuff (Disadvantage on Attacks / Saves)

Reduces enemy offensive or defensive effectiveness.

**Disadvantage on enemy attacks:**
```
Defensive eHP = Ally Expected Damage Taken × Δmiss_probability × Rounds
```
(Same formula as Defensive Buff — the math is identical, source differs.)

**Disadvantage on enemy saves:**
```
Offensive eHP = Enemy DPR × Δfail_probability × Rounds
```

```python
def calc_debuff_value(baseline_value: float, delta_probability: float,
                       expected_rounds: float) -> float:
    """Generic debuff formula — works for attack or save debuffs."""
    return baseline_value * delta_probability * expected_rounds
```

---

## Opportunity Cost

Every action has a cost that must be subtracted from its raw eHP value.

```python
def calc_resource_cost(action, actor, state) -> float:
    """
    Returns the opportunity cost of an action in eHP-equivalent units.
    """
    cost = 0.0

    # Spell slot cost
    if action.spell_slot_level > 0:
        slots_remaining = state.spell_slots_remaining[actor.id]
        encounters_remaining = state.encounters_remaining_today
        cost += spell_slot_ehp_value(
            action.spell_slot_level,
            slots_remaining,
            encounters_remaining
        )

    # Action economy cost (using action vs. bonus action vs. reaction)
    if action.uses_action:
        # Opportunity cost = value of best alternative action foregone
        # Approximation: baseline attack DPR for martial, cantrip DPR for casters
        cost += actor.baseline_action_dpr

    return cost


def spell_slot_ehp_value(slot_level: int, slots_remaining: int,
                          encounters_remaining: int) -> float:
    """
    The eHP value of conserving a spell slot scales with scarcity.
    A 3rd-level slot in encounter 6 of 6 is worth less than in encounter 1 of 6.
    """
    scarcity = 1.0 / max(1, slots_remaining)
    urgency  = encounters_remaining / 6.0  # normalized to standard adventuring day
    return slot_level * 3.0 * scarcity * (1.0 - urgency)
```

**Note:** Full strategic resource conservation (when to spend slots across an
adventuring day) is handled in `engine/ai/strategy.py` — a future module.
The formula above is a tactical approximation only.

---

## Time Horizon and Discounting

Actions that pay off in round 1 are worth more than actions that pay off in
round 3, because the encounter may already be over by then.

Use The Finished Book's 2.5-round benchmark as the discount baseline:

```python
EXPECTED_ENCOUNTER_ROUNDS = 2.5

def discount_future_value(value: float, rounds_until_payoff: float) -> float:
    """
    Discounts eHP value for actions whose benefit arrives in future rounds.
    Actions paying off after the expected encounter end are worth near zero.
    """
    if rounds_until_payoff >= EXPECTED_ENCOUNTER_ROUNDS:
        return value * 0.1  # minimal value — encounter likely over
    discount_rate = rounds_until_payoff / EXPECTED_ENCOUNTER_ROUNDS
    return value * (1.0 - discount_rate * 0.5)
```

---

## Behavioral Weights (Ammann Layer)

The raw eHP value is modified by the actor's behavioral profile before the
final action is selected. These coefficients are defined in
`docs/foundations/ammann-behavior-framework.md` and encoded in
`engine/ai/decision.py`.

| Coefficient | Description | Range |
|---|---|---|
| `aggression_coefficient` | Scales overall action value | 0.5 – 1.5 |
| `self_preservation_coefficient` | Multiplier on defensive eHP | 0.0 – 2.0 |
| `pack_tactics_bonus` | Bonus for coordinating with allies | 0.0 – 0.5 |
| `morale_threshold` | HP% at which creature considers fleeing | 0.1 – 0.5 |

```python
def action_value_with_behavior(action, actor, state) -> float:
    offensive  = calc_offensive_value(action, actor, state)
    defensive  = calc_defensive_value(action, actor, state)
    cost       = calc_resource_cost(action, actor, state)

    # Apply self-preservation weight to defensive component
    weighted_defensive = defensive * actor.self_preservation_coefficient

    raw = offensive + weighted_defensive - cost

    # Apply overall aggression scaling
    return raw * actor.aggression_coefficient
```

**Morale check** (Ammann-derived):
```python
def should_flee(actor, state) -> bool:
    hp_fraction = actor.hp_current / actor.hp_max
    return (hp_fraction < actor.morale_threshold and
            actor.self_preservation_coefficient > 1.0)
```

---

## Worked Example: Hypnotic Pattern vs. Fireball

**Scenario:** Wizard, level 7. 4 enemies (10 DPR each, 30 HP each). Round 1.  
Party targeting discipline = 0.9 (they mostly avoid hitting sleeping targets).

**Hypnotic Pattern (4th-level slot):**
```
- Save fail prob: 0.50
- Targets affected on average: 2
- Expected control duration: 2.5 rounds × 0.9 discipline = 2.25 rounds
- Action denial value: 10 DPR × 0.50 × 2.25 × 2 targets = 22.5 Defensive eHP
- Opportunity cost: 4th-level slot ≈ 12.0 eHP (early in day, slots plentiful)
- Net value: 22.5 − 12.0 = 10.5 eHP
```

**Fireball (3rd-level slot, 8d6 = 28 avg damage):**
```
- Save fail prob: 0.50 (half damage on success)
- Expected damage per target: 28 × 0.50 + 14 × 0.50 = 21.0
- 4 targets: 21.0 × 4 = 84.0 Offensive eHP
- Opportunity cost: 3rd-level slot ≈ 9.0 eHP
- Net value: 84.0 − 9.0 = 75.0 eHP
```

**Conclusion:** In round 1 against 4 enemies with 30 HP each, Fireball scores
75.0 vs Hypnotic Pattern's 10.5. The AI correctly chooses Fireball.

**But:** If enemies have 80 HP each, Fireball deals 21 damage (doesn't kill them),
and the control duration extends to 3+ rounds (more HP = longer to kill = longer
control lasts). Hypnotic Pattern's value rises significantly. The AI self-corrects
based on enemy HP without any hard-coded rule.

---

## Known Gaps (Future Work)

| Gap | Module |
|---|---|
| Strategic spell slot conservation across adventuring day | `engine/ai/strategy.py` |
| Positioning and movement value (reach, cover, flanking) | `engine/ai/positioning.py` |
| Reaction economy (when to hold reaction vs. use it) | `engine/ai/decision.py` |
| Concentration management (when to drop old spell for new) | `engine/ai/decision.py` |
| Multi-target optimization (which enemies to include in AoE) | `engine/ai/decision.py` |
| Per-creature behavioral profiles | `docs/foundations/ammann-behavior-framework.md` |
