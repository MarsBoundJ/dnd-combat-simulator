# Pillars Reconciliation Policy

**Status:** ✅ Drafted 2026-05-25  
**Supersedes:** the 2026-03-30 stub of this file  
**Authority:** binding on the AI decision layer and any engine code that reads creature/PC behavior

This document defines the runtime behavior-policy layer that resolves conflicts between the two foundational pillars of the simulator:

- **Pillar 1 — The Finished Book** (Tom Dunn) — *mathematical framework* — answers *"how much is this action worth?"*
- **Pillar 2 — The Monsters Know What They're Doing** (Keith Ammann) — *behavioral framework* — answers *"which action would this creature actually choose, and why?"*

The pillars are not in opposition; they answer different questions and operate at different layers. This document defines how they compose in the engine.

See also:
- `docs/CONTEXT.md` — Cross-Project Architecture, Validation-Oracle Rules, §Config Locked Design Conditions, Firewall Rules
- `docs/foundations/finished-book-summary.md` — Pillar 1 framework
- `docs/foundations/ammann-behavior-framework.md` — Pillar 2 schema + archetypes
- `docs/foundations/ehp-action-framework.md` — the unified scoring function

---

## 1. The Core Tension and the Resolution

### The original framing (March 2026)

The Finished Book identifies the action that *maximizes expected damage output or minimizes damage taken*. Ammann's framework constrains creatures to act *according to their nature, intelligence, and instincts*, which is often **not** the mathematically optimal move. The original framing presented this as a binary conflict requiring per-conflict policy ("Math Wins" or "Behavior Wins").

### The resolution (May 2026)

The binary framing was insufficient. The pillars compose along **multiple independent axes**, with per-creature defaults and user-controllable tuning. Specifically:

1. **Unified actor-behavior model.** Both monsters and PCs share the same `BehaviorProfile` system — because real players don't play optimally either, and the simulator's eHP-scoring use case (Phase 3) requires modeling DM-side AND player-side variability.

2. **Four discrete behavioral dials**, each with named presets (parameter bundles):
   - **Retreat** — when does this actor consider leaving the fight?
   - **Ability Selection** — which action does it choose, given the option space?
   - **Targeting** — who does it attack?
   - **Action Economy** — does it use all its turn slots, and how optimally?

3. **A separate RP Constraints system** for identity / personality / story-bound behavior that doesn't fit gradient dial settings (pacifism, oath-bound restrictions, signature-opener requirements).

4. **Three execution modes** that govern which engines participate in the decision (Strict RAW / Rules + Behavior + eHP / Behavior Engine).

5. **Sanity Hints** (not "validation") that catch likely-misconfigured combinations without claiming correctness.

The rest of this document specifies each piece.

---

## 2. Three Execution Modes

The simulation runs in exactly one mode at a time. The mode determines which engines participate in the per-turn decision.

### Mode definitions

| Internal name | UI label | What runs |
|---|---|---|
| `dmg` | **Strict RAW** | DMG p48 algorithms + stat-block-described tactics + minimal undead/construct/INT≤2 → FtD override. No Ammann archetype layer. No eHP scoring of candidate actions. |
| `dmg_ammann` | **Rules + Behavior + eHP** ★ Recommended | DMG p48 algorithms + Ammann archetype-driven per-creature parameter modulation + full eHP scoring (Sampled mode for control). All three engines compose. |
| `ammann` | **Behavior Engine** (lightweight) | Ammann archetype-driven behavior + simpler heuristics. Skips eHP scoring (faster, less accurate for high-INT creatures). |

### UI presentation (gradient-bias mitigation)

The three modes do NOT lie on a linear "more sophistication" spectrum, despite appearing to. **Rules + Behavior + eHP includes the other two**; Behavior Engine is *lighter* than the default, not heavier. Without explicit UX treatment, users tend to interpret distance-from-default as quality — exactly inverted from reality.

Four required UI affordances:

**Comparison strip** showing what each mode includes:

```
                        Rules    Behavior   eHP Scoring
  Rules Engine            ✓         —          —
  Rules + Behavior + eHP  ✓         ✓          ✓     ★ Recommended (default)
  Behavior Engine         —         ✓          —
```

**Use-case-framed first-run wizard:**

> Why are you running this simulation?
> - "Test how an encounter would play at my table" → **Rules + Behavior + eHP**
> - "Settle a strict-RAW rules debate" → **Rules Engine**
> - "Quick behavioral playthrough without compute overhead" → **Behavior Engine**

**Inline warning on selecting Behavior Engine:**

> ⚠ Behavior Engine skips eHP scoring. Boss-level enemies (Lich, Beholder, Ancient Dragon) will play *less* optimally in this mode, not more. For accurate boss-fight simulation, use **Rules + Behavior + eHP** (the default).

**Default-selected = Rules + Behavior + eHP** for any new encounter.

---

## 3. The BehaviorProfile Schema

`BehaviorProfile` is the per-actor data object the AI decision layer consults at runtime. The continuous-coefficient form (encoded in `ammann-behavior-framework.md`) is the underlying parameter space; the dial-based presets defined in §5 are the user-facing abstraction that compiles to those coefficients.

```python
@dataclass
class BehaviorProfile:
    # Identity
    archetype: str                        # "mindless_aggressor" | "cowardly_skirmisher" |
                                          # "pack_hunter" | "apex_predator" |
                                          # "territorial_beast" | "berserker_fanatic" | ...
                                          # (see ammann-behavior-framework.md)

    # The four dials (preset names; resolve to underlying parameters)
    retreat: RetreatPreset                # ftd | resolute | default | cowardly | pacifist
    ability_selection: AbilityPreset      # mindless | instinctive | default | tactical | optimal
    targeting: TargetingPreset            # closest | weakest | most_dangerous | caster_first | optimal_ehp
    action_economy: ActionEconomyPreset   # optimal | skilled | average | casual | reactive_only

    # RP constraints (separate filter/scoring system; see §6)
    rp_constraints: list[RPConstraint]    # ordered list; resolution per §6.3

    # PC-only
    play_context: Optional[str]           # "group" | "solo" (PCs only; group is default)

    # Underlying continuous parameters (computed from dial presets, or set directly)
    # See ammann-behavior-framework.md for full schema
    aggression_coefficient: float
    self_preservation_coefficient: float
    morale_threshold: float
    enrage_threshold: float
    # ... etc.
```

Per-creature defaults ship in the bundled SRD content (and in user-authored creature definitions); see §4 for resolution order.

---

## 4. Profile Resolution: Static and Dynamic Layers

Every actor in an encounter resolves its effective `BehaviorProfile` through a layered system. Layers fall into two classes:

- **Static layers** — set at encounter setup, immutable during play
- **Dynamic layers** — written by game systems during play (form transitions like Wild Shape / Polymorph / Shapechange; conditions like Frightened / Dominate Person / Confusion)

Dynamic layers override static layers. Within dynamic layers, form transition is the more fundamental change (replaces the active stat block); runtime overrides modify behavior on top of whatever the active stat block is.

### 4.1 Static Layers: Archetype → Faction → Instance

Every creature in an encounter resolves its static `BehaviorProfile` through three layers, in order:

```
  archetype defaults    (from creature type, per Ammann)
       ↓ overridden by
  faction profile       (optional intermediate layer — encounter / faction / squad scope)
       ↓ overridden by
  instance override     (optional per-actor layer — final say)
```

### Why a three-level hierarchy

- **Archetype only** — every goblin in every encounter behaves identically. Loses the "this DM's tribe plays fanatical" pattern.
- **Archetype + instance** — large encounters (10+ creatures) require per-instance overrides on every member. Tedious and error-prone.
- **Archetype + faction + instance** (this design) — DMs author a faction profile once ("Bloodbound Goblin Cult: Retreat=FtD"), apply it to all 12 goblins in the encounter, optionally override individual instances (the chieftain).

Ships with a small library of canonical faction profiles (fanatical cult, mercenary band, raiding party, defensive militia) for discoverability. Users author custom factions freely.

### `reason:` vs `suppress_hints:` — explicit separation

Two distinct fields on instance overrides (and faction profiles), serving different purposes:

```yaml
instance_override:
  targeting: optimal_ehp
  ability_selection: optimal
  reason: "Lich polymorphed into goblin form (Shapechange)"   # DOCUMENTATION
  suppress_hints: [god_ai_low_int, smart_suicide]             # CONTROL
```

- **`reason:`** — free-text human-facing explanation. Auditable in published outputs. Has **no behavioral effect** in the engine.
- **`suppress_hints:`** — explicit list of hint rule IDs to silence for this instance. New hint rules introduced in future releases are NOT auto-suppressed.

This split addresses the *global mute anti-pattern* (a single suppression flag silencing all current and future hints, hiding genuine misconfigurations). Modeled on ESLint / Roslyn precedent for rule-specific suppression.

### 4.2 Dynamic Layer: Form Transition Model

Effects that **replace the actor's active stat block** — Druid Wild Shape, Polymorph, True Polymorph, Shapechange, Magic Jar, certain stat-block features (e.g., a Werewolf's hybrid form) — are modeled as a paired-state transition, NOT as a runtime modification of the existing profile.

```yaml
actor_state:
  # ... static layers (§4.1) ...
  current_form:
    stat_block_ref: "druid_brown_bear_form"
    hp_current: 34
    hp_max: 34
    transitioned_at_round: 3
    transition_source: "wild_shape"          # spell/feature that caused the transition
    retains_mind: false                      # see table below
    revert_conditions:
      duration_remaining: "60_minutes"
      concentration_required: false         # Wild Shape doesn't; Polymorph does
      hp_zero_behavior: "revert_with_residual_damage"   # per-form-specific
      willing_revert: true
  underlying_identity:
    stat_block_ref: "druid_pc_id_42"
    hp_at_transition: 28                     # restored on revert
    behavior_profile: { ... }                # persists across form changes
```

**The `retains_mind` flag** is the key architectural distinction. Different D&D effects handle mental-stat replacement differently:

| Effect | retains_mind | HP behavior |
|---|---|---|
| **Wild Shape** (Druid) | false (uses beast's INT) | Separate HP pool; revert with remaining own HP |
| **Polymorph** (4th-level) | false | New form's HP pool; revert to remaining own HP |
| **Shapechange** (9th-level) | true (keeps caster's INT/WIS/CHA) | New form's HP |
| **True Polymorph** (9th-level) | depends on caster's choice + target intelligence | Permanent (1 hr concentration first) or until dispelled |
| **Magic Jar** | true (caster's mind into target body) | Target's HP |

When `retains_mind: false`, the effective `BehaviorProfile` derives its defaults from the *new form's* stats (mental ability scores, archetype-by-creature-type). When `retains_mind: true`, the `underlying_identity.behavior_profile` persists regardless of the form's stats.

**Per-spell rules** — exact durations, concentration requirements, HP-pool transition specifics, spell-casting availability in form — are spec work that lives in the spells/features doc. This document defines only the *architectural primitive* (the paired-state schema + the `retains_mind` switch) that those per-spell rules fill in.

**Static instance overrides still apply for permanent forms.** Setting up a "Lich permanently in goblin form" at encounter setup uses the static instance override mechanism (§4.1) — no runtime transition occurs. Use the form-transition layer for *runtime* changes during play (a Druid casting Wild Shape on turn 3; a Wizard targeted by Polymorph).

### 4.3 Dynamic Layer: Runtime Overrides

Conditions and effects that **modify behavior without replacing the stat block** — Frightened, Charmed, Dominate Person/Monster, Confusion, Calm Emotions, Suggestion, and similar — are modeled as entries in a `runtime_overrides` array that the conditions engine writes and removes during play:

```yaml
runtime_overrides:
  - source: "dominate_person"
    type: behavior_override
    override:
      targeting: "attacks_caster_party"
      ability_selection: "controlled"
    duration: "concentration_of_caster"

  - source: "frightened"
    type: targeting_constraint
    constraint:
      cannot_target: "fear_source"
      cannot_move_toward: "fear_source"
    duration: "save_each_turn_end"

  - source: "confusion"
    type: action_override
    override:
      roll_each_turn: "confusion_table"
    duration: "1_minute"
```

**Override types** — the architectural primitives:

| Type | Effect |
|---|---|
| `behavior_override` | Replaces specific dial settings (Dominate sets targeting + ability_selection) |
| `targeting_constraint` | Adds hard filters to candidate targets (Frightened can't target / approach fear source) |
| `action_override` | Replaces action selection logic for the turn (Confusion rolls on a table) |
| `forced_action` | Forces a specific action this turn (Banishment forces departure; Command forces compliance) |

**Per-condition rules** — exact override fields per condition, save mechanics, duration tracking — are spec work that lives in the conditions doc. This document defines only the *architectural primitive*.

**Multiple runtime overrides stack.** Resolution within the runtime layer:

1. All `behavior_override` entries apply first (modify the effective `BehaviorProfile`). Conflicts between two `behavior_override` entries on the same field are resolved by most-recent-wins.
2. All `targeting_constraint` entries layer additively (multiple filters AND-combine).
3. `action_override` and `forced_action` resolve in registration order; the most recent active one wins on conflict.

The conditions engine is responsible for maintaining the array, enforcing duration tracking, and removing expired entries.

### 4.4 Full Resolution Order

Computing the effective `BehaviorProfile` and effective stat block for a given turn:

```
  1. Start with archetype defaults (§4.1)
  2. Apply faction profile if present (§4.1)
  3. Apply instance override if present (§4.1)
        ← end of static layers
  4. If current_form is active (§4.2):
        - Replace stat block with current_form.stat_block_ref
        - If retains_mind = true: keep underlying_identity.behavior_profile
        - If retains_mind = false: derive new defaults from current_form's stats
  5. Apply each runtime_override in resolution order (§4.3)
        ← end of dynamic layers
  6. → effective profile passed to the decision pipeline (§7, Step 1)
```

---

## 5. The Four Dials

Each dial defines 5 named presets. Every preset is a **parameter bundle** — multiple underlying values that adjust together so the dial remains meaningful across creature HP scales and option-space complexity (see §5.1 for the worked-out scaling argument).

### 5.1 Retreat

Modulates when an actor considers leaving the fight. Operates *above* all other dials — a retreat trigger overrides every other decision.

**Three sub-modes** (selectable per encounter, inherits from the execution mode):

| Sub-mode | Algorithm | When parameters come from |
|---|---|---|
| **Strict RAW** | DMG p48 algorithm with default parameters (DC 10 WIS save, Bloodied trigger, compound conditions). Minimal undead/construct/INT≤2 → FtD override. | DMG p48 only; no per-creature variation. |
| **Rules + Behavior + eHP** (default) | DMG p48 algorithm runs; each creature's Ammann archetype profile modulates parameters (morale_threshold tightens/relaxes Bloodied trigger; SPC adjusts effective save DC). Mindless archetypes short-circuit to FtD. | DMG p48 + Ammann per-creature parameters. |
| **Behavior Engine** | Ammann's simpler algorithm: direct `HP_remaining ≤ morale_threshold` check + SPC modulation. No DMG compound triggers. | Ammann per-creature parameters; faster, less rules-faithful. |

**Five presets** (per-creature dial setting, parameter bundle):

| Preset | Pre-combat DC | Bloodied % | Ally-disparity required | Frightened-alone sufficient? | In-combat DC |
|---|---|---|---|---|---|
| **FtD** | n/a — algorithm disabled | n/a | n/a | n/a | n/a |
| **Resolute** | 13 | 35% | >75% allies down | No (must also be Bloodied) | 8 |
| **Default** | 10 | 50% | >50% allies down | Yes | 10 |
| **Cowardly** | 8 | 60% | 1 ally falls | Yes | 13 |
| **Pacifist** | 10 | 50% | >50% allies down | Yes (parley attempted before flight) | 10 |

**Conventions:**

- **`HP_remaining`** throughout (drops "HP lost" framing). Bloodied = `HP_remaining ≤ 50%`. Aligns with DMG-2024 + 3e tradition.
- The 50% Bloodied threshold is preferred over Ammann's 40% Cowardly Skirmisher value because (a) DMG-anchored, (b) easier mental math, (c) Ammann's 40% becomes a "Cowardly" preset value, not the baseline.

**Parley eligibility (deterministic engine rule):**

```
Parley is available iff:
  • the creature has ≥1 language in its stat block, OR
  • the creature carries an explicit `intelligent_beast: true` override flag
Beasts without language → Flight-only
If Flight is blocked (no exit) AND Parley unavailable → revert to FtD for this round
```

**Why bundles, not single thresholds:** HP-% thresholds are **scale-dependent**. On a 10-HP goblin, the difference between Default (50%), Resolute (35%), and Cowardly (60%) is meaningless — every martial hit puts the creature at Bloodied or below regardless. The bundle's other levers (save DC, ally-disparity threshold) dominate at the minion scale. On a 127-HP Young Black Dragon, the HP-% threshold dominates and the compound conditions become moot (dragon is usually solo). Same dial setting → coherent behavior at every HP scale because different levers do the work at different scales.

### 5.2 Ability Selection

Picks which action/spell/ability the actor uses on its turn, given the available option space.

**Five presets:**

| Preset | Algorithm | Scoring | Joint (target × ability) opt? | Typical INT |
|---|---|---|---|---|
| **Mindless** | Single fixed action repeated | None | No | INT 1–3 |
| **Instinctive** | Fixed signature per archetype | None | No | INT 4–6 + beasts (wolves with Pack Tactics; tigers with pounce) |
| **Default** | Archetype heuristics (proximity / range-based selection from available) | Damage-only | No (sequential: targeting → ability) | INT 7–12 |
| **Tactical** | Steps 1–4 of the 5-step Ammann+eHP hybrid (`ammann-behavior-framework.md` lines 433–439); archetype-filtered | eHP framework | No (sequential) | INT 13–16 |
| **Optimal** | Full 5-step pattern over (target × ability) tuples | eHP framework, **Sampled mode mandatory for control** | **Yes — joint optimization** | INT 17+ |

**The 5-step Ammann+eHP hybrid** is already encoded in `ammann-behavior-framework.md`:

```
1. Ammann: enumerate candidate actions filtered by behavioral constraints
2. Finished Book (eHP framework): score each candidate action
3. Ammann: apply behavioral weights (aggression, self-preservation)
4. Select highest-scoring action
5. Ammann: morale check — override with flee/surrender if triggered
```

**Beast/instinct exception via archetype, not INT.** Wolves (INT 3) ship with archetype = "Pack Hunter" + Ability Selection = "Tactical" — *not* "Mindless" — because pack tactics are evolved instinct that exceeds INT. The archetype assignment carries the instinctive intelligence; INT determines decision *depth*, archetype determines decision *style*.

**Joint-vs-sequential coupling at Optimal.** When Ability Selection = `optimal`, the engine performs joint (target × ability) optimization — the Ability dial's optimizer picks the target. **The Targeting dial becomes functionally inert at this level.** UI implication: when Ability=Optimal, the Targeting dial greys out and displays "Joint optimization — see Ability Selection."

### 5.3 Targeting

Picks who the actor attacks, given the action chosen by Ability Selection (or jointly with Ability at the Optimal preset).

**Five presets:**

| Preset | Algorithm | Driven by | Typical INT |
|---|---|---|---|
| **Closest Enemy** | Nearest valid target | Position only | 1–3 |
| **Weakest Target** | Lowest current HP — "bullies the wounded" | Visible HP | 4–9 (goblins, kobolds) |
| **Most Dangerous** | Threat heuristics: role assessment (heavy armor + glow → Paladin; robes + foci → Wizard) + observed damage dealt previous rounds | Observable behavior + role | 10–15 (pack hunters, hobgoblin warriors) |
| **Caster-First** | Explicitly prioritizes visible spellcasters; respects role hierarchy | Role detection + spellcasting indicators | 16–19 (apex — beholders, drow priestesses) |
| **Optimal eHP** | Joint optimization (target × likely ability); includes aura effects, combo dependencies, legendary-resistance preservation | Full eHP framework, perfect-information AI | 20+ (lich, ancient dragon) |

**Universal modifiers** (apply across all presets, not user-selectable):

- **Finish-off rule** — for INT ≥ 4, any preset deviates to attack a near-death target (`HP_remaining < 15%`) if reachable. Mindless creatures lack this awareness.
- **`focus_fire` flag** (from archetype) — if true and previous-turn target still valid, prefer continuing on them (overrides preset on ties). Pack Hunter archetype defaults to `focus_fire: true`.
- **Reachability** — only target what's actually attackable (range, line of sight, Frightened can't-approach constraint). Hard filter, not preset choice.

### 5.4 Action Economy

Modulates whether the actor uses all turn slots (Action / Bonus Action / Reaction) and how optimally within each slot.

**Five presets** (parameter bundle):

| Preset | Main optimality | Signature bonus % | Tactical bonus % | OA-type reaction % | Sophisticated reaction % | Combo recognition |
|---|---|---|---|---|---|---|
| **Optimal** | 100% | 100% | 100% | 100% | 100% | Always |
| **Skilled** | 90% | 95% | 85% | 100% | 80% | Usually |
| **Average** | 85% | 95% | 60% | 95% | 40% | Sometimes |
| **Casual** | 75% | 90% | 30% | 85% | 10% | Rarely |
| **Reactive only** | 65% | 80% | 0% | 80% | 0% | Never |

**Critical sub-category split** — within each turn slot, two cognitive-load tiers:

- **Signature bonus actions** — part of the creature/class identity (Goblin Nimble Escape; Wolf Pack Tactics; Rogue Cunning Action). High baseline rate, scaled slightly by skill. *Reflexive use.*
- **Tactical bonus actions** — situational (Healing Word when ally drops; secondary spells; Help action). Requires recognizing the moment. Scales hard with skill.
- **OA-type reactions** — instinctive triggers (Opportunity Attack; Hellish Rebuke when hit; Riposte after parry). Low decision overhead — *"they moved, I swing."* Even zombies do this.
- **Sophisticated reactions** — requires recognizing the trigger AND choosing to spend the reaction (Counterspell, Shield, Mage Slayer). High cognitive load.

**Authoring tags** on each ability in the creature/class definition:

```yaml
abilities:
  - name: Nimble Escape (bonus action: Disengage or Hide)
    is_signature: true       # part of goblin identity
  - name: Throw Torch (bonus action)
    is_signature: false      # tactical / situational
  - name: Opportunity Attack
    is_reactive_trigger: true   # instinctive
  - name: Counterspell
    is_reactive_trigger: false  # sophisticated
```

**Default classification rules:**
- Bonus actions in primary action loop → `is_signature: true`
- Bonus actions depending on external triggers → `is_signature: false`
- Reactions named "Opportunity Attack" or marked instinct → `is_reactive_trigger: true`
- Spell-based or recognition-required reactions → `is_reactive_trigger: false`

**"Miss" semantics** — when a slot rolls suboptimal, fall back to the *default action* (Attack for Main; nothing for Bonus and Reaction). Mirrors real-table behavior: a player who doesn't spot the combo defaults to "I attack."

**PC `play_context` setting** — group (default, table reminders available) vs solo (no reminders). When `solo`, the preset shifts down one tier (Casual → Reactive only). Captures the no-table-help effect without separate parameters.

**Realism over ceiling.** Default presets ship at **Average** or **Skilled** for most creatures, NOT **Optimal**. Optimal is reserved for boss-level genius creatures (Lich) + Phase 3 eHP scoring runs ("show me the ceiling"). An experienced DM does not play every monster at 100% optimal action economy at a real table.

---

## 6. RP Constraints

A separate system from the four dials, for identity / personality / story-bound behavior that doesn't fit gradient settings (pacifism, oath-bound restrictions, signature-opener requirements).

### 6.1 Why separate from dials

Different shape, vocabulary, and update cadence:

| | Dials | RP Constraints |
|---|---|---|
| **Shape** | Scoring biases / preset bundles | Action-space filters and scoring weights |
| **Vocabulary** | Skill gradients (Optimal → Reactive only) | Named identities (Pacifist, Oath-bound, Beast-Friend) |
| **Cadence** | Tuned per encounter | Usually session-stable |
| **Authoring** | Pick from 5 presets | Pick from library or compose |

Trying to encode "Pacifist won't attack family" as a dial setting either bloats the dial count past usability or forces it into a 1–5 gradient that loses fidelity. Keep separate; each system gets its right shape.

### 6.2 Three categories

| Category | Effect on decision pipeline | Example |
|---|---|---|
| **Hard Filter** | Removes actions from the candidate set entirely | "Strict Pacifist — never deals damage" |
| **Forced Choice** | When triggered, narrows candidates to a required subset | "Heal-First — must cast Healing Word on ally < 50% HP if available" |
| **Weighted Preference** | Modifies scoring within the eHP pipeline | "Prefers melee — +20% on melee scores, −10% on ranged" |

### 6.3 Severity as continuous score weight, not probability

**CRITICAL design point** — addresses a 3/3 cadre finding that probabilistic severity destroys Monte Carlo convergence and makes runs non-reproducible.

Severity is a **deterministic continuous parameter** in the eHP scoring pipeline, NOT a per-turn dice roll.

| Constraint type | Severity semantics |
|---|---|
| **Hard Filter** | Always 100% binary (in or out). The `severity` field is locked at 100% by schema; cannot be set otherwise. |
| **Forced Choice** | A **score priority weight**. A 70%-severity Heal-First constraint adds +70% to the eHP scores of qualifying actions (cast Healing Word on ally < 50%), pushing them above competing choices. No dice roll. |
| **Weighted Preference** | A **score multiplier**. +severity% on matching candidate scores in the eHP calculation. No dice roll. |

Same configuration → same outcome (modulo the simulator's seeded RNG for combat rolls). Severity behavior is fully reproducible.

### 6.4 Composition with priority tiers + fallback

**CRITICAL design point** — addresses a 3/3 cadre finding that constraint conflicts produced undefined behavior (deadlocks, empty candidate sets, non-deterministic resolution).

**Priority resolution:**

```
Tier 1 (Hardest) — Hard Filters
    Set intersection of all active filters
    Empty result triggers fallback action (see below)

Tier 2 (Strong)  — Forced Choices
    Narrow the candidate set when triggered
    Multiple triggered simultaneously: resolved by explicit `priority: int` on the constraint
    Ties broken by registration order
    Forced Choice action filtered out by Tier 1: skip this Forced Choice entirely

Tier 3 (Weight)  — Weighted Preferences
    Modify eHP scoring (see §6.3)
    Cumulative additive in single scoring pass (Amendment #3 / Utility AI pattern)
```

**Guaranteed-legal fallback** when candidate set drops to zero:
- **PCs** — default to Dodge action
- **Monsters** — default to Pass turn (or archetype-specified emergency action if defined)

No engine deadlock. Every actor has a guaranteed terminal action available.

### 6.5 Library of canonical constraints (ships with sim)

| ID | Name | Type | Applies to |
|---|---|---|---|
| `pacifist_strict` | Strict Pacifist | hard_filter | PCs |
| `pacifist_defensive` | Defensive Pacifist | hard_filter | PCs |
| `heal_priority` | Heal-First | forced_choice | PCs (healers) |
| `signature_first` | Signature-First Opener | forced_choice | PCs |
| `resource_hoarder` | Resource Hoarder | weighted_preference | PCs (casters) |
| `frontline` | Frontline Defender | forced_choice | PCs |
| `oath_protector` | Oath of Devotion (no attacking surrendered) | hard_filter | PCs + NPCs |
| `no_innocents` | Bystander Concern | hard_filter | PCs + monsters |
| `beast_friend` | Beast Friend | hard_filter | Druids, Rangers |
| `monologue_required` | Cult Leader Monologue | forced_choice | Monsters (boss-tier) |
| `treasure_protect` | Treasure Hoarder | weighted_preference | Dragons |
| `library_protect` | Won't Destroy Library | hard_filter | Liches, intellectual creatures |

Users compose from the library; advanced users author custom predicates (post-MVP).

Constraints apply to both PCs and monsters — RP nuance per-monster is exactly what Ammann's book provides at depth. A Lich with `library_protect` chooses Disintegrate over Fireball in the library chamber. A Dragon with `treasure_protect` forbids Breath Weapon over its hoard.

---

## 7. Decision Pipeline (Utility AI shape)

**CRITICAL design point** — addresses a 3/3 cadre finding that the previous pipeline applied Weighted Preferences AFTER target/ability selection (post-hoc; mathematically incoherent). The fix unifies scoring into a single coherent stage following the Utility AI pattern.

Per turn, per actor:

```
0. Resolve effective profile (§4.4)
       ↓ static layers → form transition (if active) → runtime overrides (if any)
       ↓ produces: effective BehaviorProfile + effective stat block for this turn

1. Retreat trigger check
       ↓ if firing → exit early with flee/parley action

2. Generate candidate (action × target) tuples
       ↓ enumerate all legal pairs from stat block + reachability

3. Apply Hard Filters (RP Tier 1)
       ↓ prune candidate set
       ↓ if empty → fallback action (Dodge for PC, Pass for monster) → execute

4. Apply Forced Choices (RP Tier 2)
       ↓ if any triggered → restrict candidates to forced subset
       ↓ priority resolution per §6.4

5. Score each remaining candidate in single pass:
       score = eHP_value(candidate)
             × Σ(matching Weighted Preferences)          # RP Tier 3
             + Σ(Forced Choice score weights)             # if any
             + behavioral coefficients                    # archetype aggression / SPC
             + universal modifiers                        # finish-off rule, focus_fire bias

6. Select max-scoring candidate
       ↓ ties broken by archetype tactical preference, then random

7. Apply Action Economy per slot
       ↓ for each slot (Main / Bonus / Reaction):
       ↓   per-slot stochastic on optimal-vs-default per preset (§5.4)
       ↓   if "miss" → fall back to default action for that slot

8. Execute
```

All considerations are first-class score contributors. No post-hoc patching of selected candidates. Matches Utility AI precedent (referenced by all three cadre members).

**Where the modes plug in:**
- **Strict RAW** — skips step 5's full eHP scoring; uses simple damage-only scoring. Skips Tier 3 Weighted Preferences (no eHP to weight). Steps 1, 7, 8 still run.
- **Rules + Behavior + eHP** — full pipeline as written.
- **Behavior Engine** — runs the pipeline but step 5 uses Ammann's simpler heuristic scoring instead of full eHP; Optimal-preset actors fall back to Caster-First behavior (no joint optimization possible without eHP).

---

## 8. Sanity Hints (reframed validation)

**CRITICAL design point** — addresses a 3/3 cadre finding that calling this system "validation" implied correctness guarantees that a finite static rule library cannot deliver. The reframe is honest: hints, not correctness.

### 8.1 What this system IS and IS NOT

| IS | IS NOT |
|---|---|
| Catches obvious / common misconfigurations | Exhaustive correctness checking |
| Helps novices learn the dial system | A safety mechanism |
| Flags suspicious combinations | A guarantee that absent-warning = valid |

The UI uses the label **"Sanity Hints"** (not "Validation"). The first-run wizard includes an explicit disclaimer: *"Sanity Hints catch likely-misconfigured combinations; the absence of a hint does not mean your configuration is correct."*

### 8.2 Statblock-aware hints

Hints cross-reference dial choices against the creature's *actual mechanical payload*, not just other dial choices. Example: "Ability=Optimal Healing on a creature with no healing abilities in its stat block" should fire a hint. Authoring uses the same `is_signature` / `is_reactive_trigger` ability tags from §5.4.

### 8.3 Hint rule library (initial)

| Rule ID | Trigger | Hint text |
|---|---|---|
| `god_ai_low_int` | Targeting=Optimal eHP on creature with INT<16 | "Optimal targeting is usually misconfigured on low-INT creatures. If intentional (disguised high-INT entity), add `reason:` to document and `suppress_hints: [god_ai_low_int]` to silence." |
| `smart_suicide` | Apex archetype + Retreat=FtD | "Intelligent creatures rarely fight to death. Did you mean Resolute?" |
| `ability_targeting_redundancy` | Ability=Optimal + Targeting≠Optimal eHP | "Ability=Optimal performs joint (target × ability) optimization; the Targeting setting is shadowed. Consider Targeting=Optimal eHP for UI clarity." |
| `ability_economy_mismatch` | Ability=Optimal + Action Economy<Skilled | "Optimal ability selection paired with Casual action economy is unusual — creature picks brilliantly but forgets bonus actions 70% of the time. Intentional?" |
| `dial_inert_on_statblock` | High preset on creature with minimal stat-block options (e.g., Action Economy=Skilled on Zombie) | "Dial has minimal effect for this creature (1 attack, no bonus, no reaction). Informational." |
| `rp_dial_conflict` | RP constraint shadows a dial choice (e.g., Pacifist + Most Dangerous targeting) | "Pacifist constraint prevents any attack; Targeting setting is functionally inert. Intentional combination?" |
| `rp_constraint_stack` | ≥3 hard_filter constraints on one actor | "Multiple hard filters can collectively prevent the actor from taking ANY action. Verify configuration." |
| `ability_no_payload` | Ability preset requires capabilities not in stat block (e.g., "Optimal Healing" on no-healing creature) | "Selected preset requires capabilities the stat block doesn't have. Falls back to next available behavior." |

Library grows organically; new rules introduced in future releases visibly fire on existing configurations (because `suppress_hints` is per-rule, not blanket).

### 8.4 Mode-relevance as text, not gating

A hint always fires when its trigger condition matches, regardless of execution mode. Mode-relevance is *content* of the hint text:

> ⚠ `ability_optimal_under_behavior_engine`: "Targeting=Optimal eHP requires the eHP scoring engine, which is disabled under Behavior Engine mode. Will fall back to Caster-First behavior."

Same configuration → same set of hints in every mode. Users can switch modes freely without warning-fatigue inversions. (Addresses the cadre's mode-aware-desync finding.)

### 8.5 UX presentation

Non-modal sidebar notes with three actions per hint:

```
⚠ smart_suicide
   Apex Predator archetype + Retreat=FtD
   Intelligent creatures rarely fight to death...
   
   [Acknowledge]  [Add Reason]  [Suppress this rule]  [Revert]
```

- **Acknowledge** — dismiss this firing; rule still active for other configs.
- **Add Reason** — open `reason:` editor (documentation only).
- **Suppress this rule** — add this rule ID to the instance's `suppress_hints` list.
- **Revert** — undo the dial change that triggered the hint.

---

## 9. Connection to Cross-Project Architecture

This document is binding on the AI decision layer. It composes with several other architectural commitments documented in `docs/CONTEXT.md`:

- **§Config Locked Design Conditions** — every behavioral decision is a policy-object with explicit read/write/event/scope contracts; the dial settings are config inputs; the decision-pipeline stages (§7) are the policy-objects. Reaction-cascade termination guard mandatory.
- **Validation-Oracle Rules** — eHP is a *disclosed input axis, never a gate*. Sim outputs feed Trusight as one of two analytical inputs; never auto-iterates against verdicts. Direction-B (community-prevalence → sim-default-ruling) is severed. RP-flavored runs (with RP Constraints active) are NOT canonical power-scoring runs; the Hybrid published-reports surface explicitly distinguishes "pure power eHP" from "RP-adjusted" runs.
- **Firewall Rules** — the sim implements creatures via clean-room functional reimplementation. The behavioral framework here operates on mechanics (uncopyrightable); no WotC behavioral prose is transcribed. Ammann's archetypes are *referenced* (his name + book cited); his per-creature recommendations are paraphrased into our schema, not copied.

---

## 10. Follow-On Architecture (Planned, Not MVP)

These items were identified during the May 2026 cadre red-team as architecturally important but not blocking the MVP. The schema and pipeline must NOT preclude them; full implementation is deferred.

- **Per-effect implementation specs** — exact rules per spell/feature/condition: Wild Shape's HP-pool mechanics, Polymorph's revert behavior, Shapechange's spell-casting rules, Frightened's save cadence, Dominate Person's target-selection logic, etc. The *architectural primitives* (form transition and runtime overrides) are fully specified in §4.2 / §4.3; the per-effect content lives in the spells/features doc and the conditions doc. Defer to when those docs are written.
- **Phase-shift constraints** — Bloodied → drop Pacifism filter; mythic phases that replace the active BehaviorProfile mid-combat. Distinct from form transitions (no stat-block change) and runtime overrides (no external source). Boss design pattern; needs a state machine the engine can host.
- **Temporal memory / stateful constraints** — track "already healed this turn" / resource depletion over time. Requires per-turn state the engine carries.
- **Dynamic / runtime validation** — post-hoc hints based on observed behavior across Monte Carlo runs (degenerate loops, zero-action turns, statistically suspicious outcomes). Static config Hints (§8) are the MVP; runtime Hints layer on later.
- **Alternative archetype "style" baselines** — Ammann is one author's interpretation. Schema should support alternative styles (e.g., "average DM," "tournament OP") as a future axis. Don't build alternatives yet; just don't preclude them.
- **Faction profile library expansion** — ship initial small library (fanatical cult, mercenary band, etc.); grow organically based on use.

---

## 11. Decision History

**Original design conversation:** Phil + Claude, 2026-05-24 → 2026-05-25 (dial-by-dial design across several sessions; reflected what an experienced DM thinks about when modeling combat behavior).

**Cadre red-team:** 2026-05-25. Three independent AI models (Gemini / ChatGPT / Perplexity) reviewed RP Constraints, granularity model, and validation system under explicit adversarial scoping. Six 3/3 convergent CRITICAL findings surfaced:

1. Severity-as-probability breaks Monte Carlo convergence → fixed by Amendment #1 (continuous score weight) — §6.3
2. Constraint conflict resolution underspecified → fixed by Amendment #2 (priority tiers + fallback) — §6.4
3. Pipeline ordering mathematically incoherent (weighted prefs post-hoc) → fixed by Amendment #3 (Utility AI single scoring stage) — §7
4. Validation system structurally insufficient → fixed by Amendment #4 (reframed as Sanity Hints) — §8
5. `reason:` field overloaded as global mute → fixed by Amendment #5 (split into `reason:` + `suppress_hints:`) — §4
6. Mode-aware validation desync → fixed by Amendment #6 (mode-relevance as text, not gating) — §8.4

Plus Amendment #7 (three-level inheritance: archetype → faction → instance) addressing a 2/3 convergent finding — §4.1.

The cadre red-team produced a substantially stronger architecture than the pre-cadre version. This is the same May 17 validation-oracle pattern: independent adversarial review catches structural issues that local design conversation cannot surface.

**Polymorph + runtime override layer — reconsidered same-day (2026-05-25).** Initially routed to §10 follow-on as "architect-for, defer-detail" — a triage error. The cadre had actually flagged these as CRITICAL (Gemini explicitly; ChatGPT and Perplexity on the polymorph variant); I read them as separate concerns and undersold their priority. On a same-day check of frequency in core gameplay — Druid Wild Shape (the Druid's identity feature, available from level 2), Polymorph (4th-level), Shapechange (9th-level), True Polymorph (9th-level), Magic Jar; plus the runtime-override class of conditions (Frightened, Charmed, Dominate Person, Confusion) — these are not edge cases. They are core gameplay across most levels and a large fraction of classes. Deferring would have produced an immediate "this can't model Druids" gap in Phase 1. Promoted to full specification at §4.2 (Form Transition) and §4.3 (Runtime Overrides). Per-effect implementation specs remain in §10 follow-on, but the architectural primitives are now in-doc.

**Follow-on items** identified by the cadre were accepted as architectural reservations (§10) — schema must not preclude them; full implementation deferred to post-MVP.

---

## When this document changes

This document is binding on engine code. Changes require:

- **Minor edits** (typos, clarifications, library additions): standard PR review.
- **Schema changes** (new dial, new constraint category, pipeline reordering): explicit cadre red-team round before merge.
- **Amendments to the 3-mode model or the firewall connections** (§9): cross-project review (sibling-repo / spine-doc implications).

Every change updates `Last updated` in the header.
