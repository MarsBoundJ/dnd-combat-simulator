# Red Team Review Request: D&D 5e Feature-Power Measurement Harness

## Your Role

You are a red-team reviewer. Your job is to find the flaws in our experimental
design BEFORE we spend compute and engineering time on it. We want you to be
adversarial: assume the design is broken until proven otherwise. You have three
areas of expertise:

1. **Experimental design & statistics** — Monte Carlo methods, power analysis,
   variance reduction, multiple-comparison corrections, confound analysis.
2. **D&D 5e (2024 rules) game balance** — class/subclass design, encounter
   math, the optimization community's findings (Treantmonk, CMCC, etc.).
3. **Simulation methodology** — what simulated agents can and cannot tell you
   about a game played by humans.

Do NOT review code. Assume the simulator's combat mechanics are correct (they
are extensively tested). Review the EXPERIMENT we plan to run on it.

## Context: The Simulator

We have a D&D 5e (2024) combat simulator with:

- **Full combat engine**: initiative, actions/bonus/reactions, spell slots,
  concentration (with break-on-damage saves), conditions, death saves &
  revival, legendary actions/resistances, recharge abilities, opportunity
  attacks, readied actions.
- **3D spatial model**: grid positions + elevation, Chebyshev-3D distance,
  flying/kiting, AoE templates (cone/sphere/line) with placement optimization,
  walls/barriers (incl. Wall of Force), line-of-effect.
- **AI decision layer**: every action-target pair is scored in "eHP" (effective
  HP — a unified currency where damage dealt, damage prevented, healing, and
  control denial are all expressed as hit points). Actors pick the
  highest-scoring candidate. Spell slots carry opportunity cost that scales
  with scarcity and encounters remaining in the day.
- **Optimization dial (1-5) per side**: the probability that a side applies an
  optimal tactic when warranted. Dial 1 = casual table (never), dial 3 = WotC
  baseline (67%), dial 4 = optimizer play (87.5%), dial 5 = perfect play
  (100%). The dial gates focus-fire, kiting, AoE repositioning, readied-spell
  combos, etc.
- **Adventuring-day harness**: sequences of encounters with persistent HP,
  slots, hit dice, short rests; between-encounter recovery.
- **Per-round contribution ledger**: for every actor every round — damage
  dealt/taken, real attacks vs out-of-range, hit %, control eHP (denied enemy
  DPR × denial fraction), healing eHP. Reconstructed from a complete event log.
- **Monte Carlo runner**: N-seed batches with full per-seed artifacts.

Baseline test party: 4 PCs, level 13 (Fighter/Champion, Cleric, Wizard/Evoker,
Bard/Lore) — but party composition is configurable and parties at other levels
will be built for tier-specific testing.

## The Plan Under Review: "The Obstacle Course"

**Goal (Purpose 1 of the sim):** measure the power of individual game features
— subclasses, spells, magic items, feats, and (secondarily) monsters — with a
margin of error low enough to resolve small deltas. D&D is built for balance:
subclasses within a class are SUPPOSED to be close in power, so we may need to
resolve differences as small as **1% or less** in whatever outcome metric we
settle on.

**Design:** a fixed, stable "obstacle course" of roughly 20 encounters (the
number is arbitrary — challenge it), structured as one or more adventuring
days, run identically for every variant. Hold everything constant, swap ONE
variable (e.g., Champion → Battlemaster on the same Fighter chassis), run N
seeds, measure the delta.

**Planned encounter taxonomy** (each category isolates a capability):

| Category | What it tests |
|---|---|
| Melee-only brutes | raw DPR, survivability |
| Ranged kiters | closing ability, ranged options |
| Save-heavy casters | save proficiencies, Counterspell access |
| Swarms of weak creatures | AoE efficiency |
| Single legendary boss | nova capability, Legendary Resistance interaction, control |
| Mixed groups | target priority, action-economy choices |
| Varied resistances/immunities | damage-type flexibility |

**Planned protocol:**
- Same party chassis, swap one feature.
- Same encounter sequence, same starting positions.
- Optimization dial held constant (probably dial 3 = WotC baseline; possibly a
  second sweep at dial 4-5 to measure each feature's "optimization ceiling" —
  some features are flat across skill, others spike).
- N seeds per (variant × course) cell; outcome metrics: win rate, rounds to
  win, per-actor DPR / eHP contribution shares from the ledger, resources
  spent, PC deaths.

## Your Tasks

### 1. Blind spots in the encounter taxonomy

What capability dimensions does our 7-category taxonomy fail to test? For each
blind spot: name the capability, name a feature whose power would be
mismeasured without it, and propose the minimal encounter that tests it.
Candidate areas we suspect but want your independent list first: condition
spam, grapples/forced movement, enemy healing/regeneration, summoner enemies,
stealth/invisibility, burrowing/teleporting enemies, environmental hazards,
terrain (chokepoints, difficult terrain, cover, verticality), darkness/vision,
very long range artillery, anti-magic, swarm-of-casters, mounted/vehicle.

### 2. Confound analysis (this is where we most need adversarial eyes)

Attack the "hold everything constant, swap one variable" claim. Specifically:

- **Party-context confound**: a subclass's measured power depends on the other
  3 party members (a Battlemaster looks better next to a control Wizard than
  next to another martial?). Is a single fixed party chassis fatally
  confounded? Do we need a party-composition panel (k different parties per
  variant)? How big must k be?
- **AI-skill confound**: the sim AI may use Feature A optimally and Feature B
  poorly — then we're measuring our AI's skill WITH the feature, not the
  feature. (Example: maneuvers with situational triggers vs always-on damage
  riders.) How do we detect and bound this bias? Is there an audit metric
  (e.g., feature-usage rate vs theoretical optimum) we should compute per
  variant?
- **Ordering/attrition confound**: in an adventuring day, encounter 5's
  difficulty depends on resources spent in encounters 1-4 — a feature that
  saves resources early looks better late. Is this signal (resource efficiency
  IS power) or noise (sequencing artifacts)? Should the course be both
  isolated-encounter AND full-day variants?
- **Dial confound**: does measuring at dial 3 systematically undervalue
  features that only pay off under coordinated play (and vice versa at 5)?
- **Seed-reuse correlation**: we plan paired seeds (same dice for both arms).
  Where does pairing break down (e.g., variant A kills an enemy one round
  earlier, after which the dice streams diverge)? Does divergence-after-first-
  difference invalidate the pairing variance reduction?
- Any other confounds we haven't named.

### 3. Statistical power analysis (show your math)

We want to rank features and detect deltas as small as ~1%. For each outcome
metric below, derive the required N per arm at 95% confidence / 80% power, and
state how paired-seed designs change it:

- **Binary win rate** (worst case: p ≈ 0.5, detect Δ = 1 percentage point)
- **Continuous metrics** (DPR, eHP contribution share, rounds-to-win) — state
  what assumptions about variance you need, and propose how we estimate
  variance from a pilot run.
- **Rank-order questions** ("is subclass X the strongest of 8?") — what
  multiple-comparison correction applies, and what does it do to N?

Then answer the practical question: **how many simulated adventuring days per
comparison** (a) subclass vs subclass, (b) spell vs spell, (c) magic item vs
baseline, (d) feat vs feat, (e) monster vs monster — given that one adventuring
day ≈ 20 encounters and we can run thousands of days of compute. If 1% on win
rate is computationally unreasonable, say so and propose the best achievable
precision ladder (e.g., "1% on DPR is cheap; 1% on win rate costs 40k days;
here's the metric hierarchy that gets you decision-grade answers cheapest").
Recommend variance-reduction techniques in priority order (common random
numbers, antithetic variates, control variates using the contribution ledger,
stratification by encounter, CUPED-style regression adjustment — whatever you'd
actually use).

### 4. Resistance/immunity testing design

"Varied resistances/immunities" is one category but damage types are many
(fire, cold, lightning, radiant, necrotic, poison, psychic, force, B/P/S...).
Design the minimal encounter set that fairly scores damage-type flexibility
WITHOUT exploding the course size. Consider: should resistance coverage be a
weighted average reflecting the actual Monster Manual distribution of
resistances/immunities (e.g., fire immunity is common, radiant resistance is
rare)? Propose the weighting method.

### 5. Metric validity

Is win rate the right headline metric at all, given most encounters are
designed to be winnable (ceiling effects)? Critique our candidate metrics
(win rate, rounds-to-win, DPR share, eHP contribution share, resources spent,
deaths) and propose better ones if they exist — e.g., marginal contribution
measured by leave-one-out (replace the PC with a commoner / remove them),
Shapley-style attribution across the party, time-to-kill vs damage-taken
exchange ratios. What's the single best primary endpoint for "power of feature
X" and what composite would you report?

### 6. The adventuring-day structure

Critique "20 encounters as the course." How many encounters per day, how many
rest points, and how many distinct days should the course contain? Should
encounter difficulty be uniform (all Moderate) or a designed curve (Low through
High)? Justify with reference to what resource-dependent features (casters,
short-rest classes) need in order to be measured fairly against resource-free
features (Champion).

### 7. Monster power measurement (secondary)

Sketch how the same course inverts to measure MONSTER power: what's the
yardstick party, what's the outcome metric, and what's the equivalent of
"swap one variable" for a monster? Flag any asymmetries that make monster
measurement harder than PC-feature measurement.

## Deliverable Format

1. **Findings ranked by severity** (CRITICAL = invalidates conclusions /
   MAJOR = biases conclusions materially / MINOR = adds noise or cost). For
   each: the flaw, why it matters, the concrete fix.
2. **The sample-size table** (task 3) with assumptions stated and arithmetic
   shown.
3. **Your redesigned course** if you believe the current one is structurally
   wrong — otherwise the amended version of ours.
4. **The top 3 things you would do differently** if this were your experiment,
   in one paragraph each.

Be direct. We would rather hear "your 1% precision goal is unachievable on win
rate and here is why" than receive polite hedging. Where you are uncertain,
state your uncertainty and what pilot experiment would resolve it.
