# Positioning Model — eHP-utility, dial-gated

*2026-06-03. Design doc written before implementation (per Phil). Companion
to `content-roadmap-and-calibration.md` (the optimization dial) and
`sim-modes.md`. Motivated by the boss-sim finding "party clustered → one
Fire Breath hit all four" (`sims/FINDINGS.md`).*

---

## 1. The reframe: positioning is a tradeoff, not a rule

"Spread out vs. a dragon" is **not** the behavior — it's what *falls out*
of a tradeoff. Each turn, an actor's movement chooses the reachable
destination that **maximizes a positioning utility**, denominated in the
same **eHP** currency as everything else in the engine:

```
positioning_utility(dest) =
      Σ ally-aura benefit (+)
    − Σ AoE exposure (−)
    − concentration-break risk (−)
    − melee exposure (−)
    + cover (+)
    + support-proximity (+, small)
  subject to: action-enablement (hard constraint)
```

Both "spread" and "cluster" emerge from the math. A party with a Paladin
Aura of Protection may correctly **cluster** (the aura's saved-eHP beats
the breath risk); a party without one **spreads**. The model decides — no
hand-coded doctrine (Phil, 2026-06-03: pure computed eHP for now).

### Why a single "maximize ally separation" heuristic is wrong
The shelved v1 (`shelf/aoe-spacing-v1`) maximizes min-distance-to-allies
whenever an enemy has an AoE. That ignores the aura-benefit term and would
**pull allies out of a 10-ft Aura of Protection to "spread,"** costing more
eHP than the breath. Kept only as the reusable destination-search scaffold;
its scoring is superseded by the utility below.

---

## 2. The terms (all eHP-denominated)

1. **AoE exposure (−).** Expected eHP lost to known enemy area attacks if
   they catch you. **Party-coupled** (reads *all* allies' positions, not
   just self) **and adversary-aware**: the AoE is mobile and the enemy is a
   maximizer, so exposure is evaluated against the boss's *best response* —
   it will move (up to speed) and orient the shape to catch the most PCs,
   net of the OA / movement cost it's willing to pay. The effective danger
   is therefore **`AoE footprint + boss reach/move − OA-cost-it'll-eat`**,
   not "is an ally within radius R right now." Computed by the **AoE
   coverage routine (§9)**, run **single-ply** (boss places its best AoE
   against the formation; no deeper recursion — Phil 2026-06-03). The
   canonical cases are a 60-ft cone and a 20-ft sphere; **a line is
   effectively up to 2 rows wide (straddling) and freely angled** (§9), so
   spread *perpendicular* to it, not just along it.

2. **Concentration-break risk (−).** If the actor is concentrating, a hit
   forces a CON save, `DC = max(10, floor(damage/2))`. A ~55-damage breath
   ⇒ DC ~27; Wizards/Sorcerers lack CON proficiency, so they usually fail.
   Cost = `P(hit) × P(fail) × (remaining eHP value of the maintained
   spell)`. **This is the link to control-eHP**: losing concentration on
   Polymorph / Wall of Force / Hold Monster ≈ losing the entire control
   investment. For a controller, dodging the breath is existential, not
   cosmetic.

3. **Melee exposure (−).** Being inside an enemy's reach × that enemy's
   expected melee eHP output, weighted by your AC. Squishies (low AC, low
   HP) are punished hard ⇒ the "casters stay out of melee" doctrine is an
   *emergent* result, not a rule. Exceptions (Bladesinger, Enchanter)
   emerge because their features add melee/near-melee *benefit* terms.

4. **Ally-aura benefit (+).** eHP gained by standing inside an ally's
   beneficial aura: Aura of Protection (+CHA to saves → defensive eHP),
   Spirit Guardians (the cleric moving so its aura engulfs an ally's
   enemies → offensive eHP), Bless range, etc. The counterweight to AoE
   exposure — the crux of the cluster-vs-spread tradeoff.

5. **Action enablement (HARD CONSTRAINT).** A destination must keep ≥1
   useful action in range *and* with clear line of effect, or the actor's
   offensive eHP → 0. A square that disarms you is invalid regardless of
   how safe it is.

6. **Cover (+).** +AC / +DEX-save → defensive eHP. We now have walls +
   line-of-effect (the barrier substrate), so cover-from-terrain is
   computable; self-made cover (Minor Illusion) is a later term.

7. **Support proximity (+, small).** Within one move (speed) of an ally who
   might need a touch-range rescue (Dimension Door, Cure Wounds). Soft,
   low weight — keeps casters from wandering uselessly far.

---

## 3. The cluster-vs-spread tradeoff (the crux)

Cluster **iff** `Σ aura benefits > Σ (AoE + concentration + melee) risk` at
that position. Pure computed eHP. Worked intuition:

- **Aura comp** (Paladin): +5 to saves for 3 allies vs a DC-21 breath is a
  large defensive-eHP swing; the model may keep the party *tight behind the
  paladin* even eating smaller hits — unless the breath is outright lethal,
  in which case spread wins.
- **No aura**: nothing offsets AoE/melee/concentration risk ⇒ the party
  spreads. This is the realistic dragon-fight picture.

No "doctrine" override lever for now (Phil). If pure-eHP ever produces a
clearly-unrealistic choice, revisit then.

### The mobile-adversary refinement (worked example)
Because the boss repositions (§2), spreading is about **raising the boss's
marginal cost to group you**, not raw distance. Worked case: a Paladin's
aura is worth ~6 eHP to a melee Fighter, but standing apart so the breath
hits *one* PC instead of *two* saves ~37 eHP — spread wins by far. Yet a
smart dragon will **pay ~15 eHP of opportunity attack to move and line up a
2-target cone worth ~74** (it pays, since 74 ≫ 15), so two melee PCs get
grouped *regardless* of which side of the dragon they stand on. The
emergent optimum the eHP terms produce: **one durable PC tanks melee; the
rest attack from range, spread beyond the boss's cone-alignment reach** —
so the boss's best AoE catches ~1 PC/round. Caveats: (a) **composition-
bound** — a two-melee party can't reach the one-tank ideal, so the model
outputs "least-bad" (stand far apart, tax the boss's movement + OAs); (b)
the lever is the boss's *marginal cost* to catch the 2nd target, which wide
spacing inflates; (c) **flight is a deferred amplifier** — a flying boss
repositions in ~3D nearly for free, so our 2D v1 understates its mobility.

---

## 4. The optimization dial governs TWO axes

The 1–5 dial (see `content-roadmap-and-calibration.md`) controls positioning
along **two independent axes**:

**A. Information quality** — what the actor *knows*:
- **Dial 5:** perfect — exact AoE footprints, recharge odds, aura ranges,
  enemy reach. Solves the tradeoff exactly.
- **Dial 1:** none — no AoE foresight ⇒ the naive clustering the sims show.
- **Mid (≈3, "WoTC baseline"):** qualitative — "it's a dragon, don't all
  stand together" without exact numbers. Model with noised / under-resolved
  AoE estimates (e.g. assume a generic cone, not the real 60 ft).

**B. Optimization breadth** — how many terms are even considered:
- **Dial 1:** none (no repositioning; greedy move-to-engage only).
- **Dial ~3:** AoE + melee + action-enablement.
- **Dial 5:** all terms + the full cluster-vs-aura tradeoff.

Encode as a `dial → (info_quality, active_terms)` config, consistent with
the calibration doc. **The clustering we observe is the dial-1 baseline**;
the shelved v1 is roughly "dial-2, no-aura."

---

## 5. Starting geometry + initiative (encounter setup)

Boss fights open with the party **entering the lair** — they generally know
the boss room is the boss room. So:

- Seed PCs at an **approach distance (~50–75 ft)** with maneuver room, not
  stacked at 15 ft. Realistic setup matters as much as movement AI.
- Setup is itself **dial-flavored**: a high-dial party enters spread and
  cautious; a dial-1 party bunches in the doorway.
- `sims/run_first_sim.py`'s 15-ft cluster is a worst-case (dial-1) setup;
  future sims should place PCs realistically and/or pre-spread at high dial.

**The boss does NOT automatically act first.** Initiative is rolled every
encounter, so boss-first is *probabilistic*, not guaranteed — there is a
good chance one or more PCs act before the boss. Implications:

- **2024 surprise = Disadvantage on the initiative roll**, NOT a lost turn
  (the 2014 "skip your first turn" rule is gone). Even a surprised party
  still rolls, and some PCs may beat the boss.
- An **intelligent, high-dial boss engineers initiative advantage** — sets
  up surprise, casts Invisibility / uses advantage-granting effects, or
  simply has a high initiative bonus (a genius lich plans the ambush; a
  dragon in its lair may gain surprise). But this only *shifts the odds*;
  it does not guarantee acting first. This is a **sibling dial-gated
  behavior** to positioning (smarter actors optimize the pre-fight),
  tracked separately from this doc.
- So the **round-1 alpha strike is a RISK, not a certainty.** The first sim
  (the dragon won initiative on seed 42) is *one draw*, not the rule.
  Starting geometry hedges the risk; PCs who *do* act first can preempt —
  spread out, take cover, or land control before the breath. **The
  positioning model must not assume the party always eats a turn-1 AoE**;
  it weighs AoE exposure as an expected cost over the initiative
  distribution, not a guaranteed one.

---

## 6. Implementation order (by what exists today)

| Phase | Terms / work | Depends on | Status |
|---|---|---|---|
| **seed** | reachable-destination search + AoE-exposure only | walls/LoE (done) | **shelved** `shelf/aoe-spacing-v1` |
| **1** | AoE-exposure + melee-exposure + action-enablement; dial breadth wiring | computable now | next |
| **2** | ally-aura benefit | **Aura of Protection NOT built yet**; Spirit Guardians exists | blocked on aura content |
| **3** | concentration-break risk | a "remaining eHP value of a maintained spell" estimate (ties to the deferred control-eHP scorer) | blocked |
| **4** | cover (+AC/+save from walls) + self-made cover | cover→AC/save mapping | later |
| **5** | starting-geometry / approach-distance setup + dial-flavored pre-spread | encounter-setup surface | parallel |
| **6** | information-quality axis (noised AoE estimates at low/mid dial) | dial config surface | parallel |

## 7. Open dependencies (tracked)

- **Aura of Protection not modeled** — term 4 has little to read for Paladin
  comps until it's built (content-lane). Spirit Guardians (the cleric
  offensive case) *is* modeled.
- **Control-eHP scorer deferred** — needed for term 2's "value of the
  maintained spell" and for valuing control generally. Same bucket as the
  Wall-of-Force AI-scoring deferral.
- **Cover → AC/save mapping** — walls + LoE exist; need the cover-grade
  (half / three-quarters / total) derivation from wall geometry.
- **Dial config surface** — where the 1–5 dial lives and how
  `(info, terms)` are read. Align with `content-roadmap-and-calibration.md`.

---

## 8. Throughline to the architectural spine

Positioning is pure **enumerate-then-select** sim depth (the sim selects;
Trusight only measures). The concentration↔control-eHP link makes
positioning and the control-spell work (this session's Wall of
Force/Polymorph/Hold Monster) **the same problem**: a controller that eats
the breath loses its control. No Trusight-facing signal crosses; firewall
intact.

---

## 9. AoE coverage routine (shared monster-offense / PC-exposure spec)

**One function, both directions.** A single routine answers "how many
agents can this area shape catch, given the caster's movement?" — used by

- **monster offense**: maximize targets hit by a breath / Fireball / line;
- **the PC AoE-exposure term (§2)**: run the *boss's* routine adversarially
  (single-ply) → "the worst AoE the boss can land on our formation."

```
max_aoe_coverage(shape, attacker, reachable_apexes, targets, state)
  -> { apex, orientation/center, covered: [agent_id...], n_covered }
```

### Unifying principle
The optimal placement can always be slid/rotated until its boundary grazes
actual target points, so enumerate a **finite, target-derived candidate
set** rather than sweeping continuous space. Per shape:

| Shape | Method | Cost / apex |
|---|---|---|
| **Cone / sector** | **Angular interval stabbing** — each in-range target `p` gives an arc `[β_p−α, β_p+α]` of facings that hit it (`β_p = atan2(Δy,Δx)`); the best orientation is the **max-overlap of arcs** (sort 2n endpoints, +1/−1 sweep). Optimal facing is always an arc endpoint. | O(n log n) |
| **Line / slab** | "Max points through the apex" — bucket targets by snapped bearing (thin line), or fatten to angular arcs by `width÷distance` (slab) and stab as above. **Evaluate centered *and* straddled placements** (see below). | O(n log n) |
| **Sphere / burst** | **Max-coverage disk** — candidate centers are the (≤2) radius-`r` circles through each target *pair* ≤ `2r` apart; score coverage at each. | O(n²) |
| **Cube (axis-aligned)** | **Sliding-window sweep** — sort by x, slide an `s`-wide strip; within it slide an `s`-tall window in y (two pointers). Axis-alignment (no tilt) is what keeps this cheap. | O(n log n) |

### Movement (apex isn't fixed)
The caster may move before placing the shape. Useful apexes are
**target-derived** (reachable squares within the shape's length of ≥2
targets), not the whole move region. Prune with the existing **grid /
spatial-hash** to fetch only nearby agents; conceptually an **influence
map** (rasterize "agents hit if placed here" and pick the hot cell).

### Implementation: now vs. scalable
- **Now (our scale: ≤ ~8 agents, cones snapped to 8 grid directions):**
  brute-force **pruned-apex × 8 directions** using the existing
  `actors_in_cone / actors_in_line / actors_in_radius` — exact on the grid,
  no new geometry, trivially fast.
- **Scalable upgrade** (finer/continuous orientation, or a wizard nuking 20
  goblins): the **angular-stabbing** method above. Clean hybrid — the
  angular method *proposes* candidate facings; the grid functions *verify*
  membership so results stay grid-exact.

### Line width, straddling & angling
A "5-ft-wide" line is a **floor, not a ceiling**, for an optimizing caster:
- **Straddling (Xanathar variant) ≈ 2-wide.** Aiming the line down a grid
  *border* instead of a row center catches **both adjacent rows** —
  effectively doubling coverage. `max_aoe_coverage` therefore evaluates
  **both** the row-centered (1-wide) and border-straddled (2-wide)
  placements per direction and keeps the better. Roughly doubles a line's
  threat/value over the naive reading (matters for blue/bronze dragon
  lightning breath and a foe's Lightning Bolt).
- **Free angling.** Lines needn't follow rows/columns; a clever angle
  threads off-axis targets. Same deferred upgrade as continuous cone
  orientation — today: **8 grid directions + the straddle offset**; later:
  thin-slab angular stabbing with a straddle-inclusive width tolerance.
- **Membership convention: center-based** (a square is hit iff its center
  lies in the strip) — consistent with `actors_in_radius/cone`. The
  "any-square-the-template-touches" table variant is more generous and is
  **out of scope**; straddling is the one sanctioned way to get a 2-wide
  line. **Dial-gated:** dial-5 straddles/angles to maximize; dial-1 fires
  straight down a row.
- **Exposure implication (§2):** an enemy line is effectively up to **2
  rows wide and freely angled**, so PCs in *adjacent* rows aren't safe —
  spread **perpendicular** to the likely line, not just along it.
- **Implementation gap:** current `actors_in_line` is 8-dir, center-based,
  **no straddle** → Phase 1 adds the straddle option; free-angle deferred.

### Minimax depth
**Single-ply** (Phil 2026-06-03): the boss places its single best AoE
against the PCs' formation; PCs evaluate a move against that one best
response. No deeper back-and-forth (we-move-anticipating-its-move-…) until
much later, if ever.

### Where it plugs in
- Monster turn: pick the AoE action + apex + orientation maximizing
  `n_covered` (weighted by per-target eHP, allies-as-negatives for the
  monster's own friendly fire).
- PC positioning (§2 AoE-exposure term): for a candidate PC destination,
  the cost = the eHP of `max_aoe_coverage` run for the boss over its
  reachable apexes against the resulting formation.

---

## 10. Foundry-VTT interoperability (target acquisition + AoE)

Verified against Foundry/dnd5e behavior. **Verdict: our model folds in
cleanly — our two core choices ARE Foundry's model.**

- **Membership = Foundry core default.** Foundry core targets a token iff
  its **square's center** is under the template (all shapes) — exactly our
  center-based rule. (Strict 5e-PHB "any touched space" — except circles,
  which use center — is a module override, *DF Template Enhancements*; we
  use the cleaner center rule = Foundry core, and can opt into 5e-touch
  later.)
- **Wall-blocked AoE = the *Walled Templates* module, same channel model.**
  Foundry templates don't respect walls natively; the standard module adds
  it and keys off the **exact move / sight / sound / light wall-restriction
  types we built into `Wall`**, with Block / Spread / Reflect modes. "Wall
  of Force stops a Fireball's spread" = a template set to **Block,
  restriction = move** — a ~1:1 map. (It also spreads-around / reflects,
  which we don't — our Block is a subset.) The Phase-A channel choice was
  prescient: same vocabulary the Foundry wall ecosystem speaks.
- **Shapes + angles.** Phase D exports circle / cone@53.13° / ray / rect.
  **Free-angle + straddling are NATIVE to Foundry** (continuous placement),
  so our 8-dir grid is the *limiter* — adding free-angle later is zero
  Foundry-side work.
- **Large creatures.** Foundry core is also center-point based, matching our
  single-(x,y)-per-actor model today; they diverge only if we add
  multi-square footprints (then both sides need the same footprint rule).

**The one architectural lock: the SIM is authoritative for target
acquisition.** We compute who's in the AoE (our routine + center membership
+ wall occlusion) and hand Foundry the template + resolved targets to
render — Phase D's one-way export. Foundry's own auto-target need not match
in *sim mode*. For a future *observation mode* (Foundry/GM drives, we
record), configure Foundry to match us: **core center targeting + Walled
Templates (Block, restriction = move)** — Foundry's defaults plus the one
standard wall module, so alignment is natural.

**Verify when wiring:** (a) cone edge-cell rule (Foundry's rendered cone vs
our grid `lateral ≤ forward/2` may differ at the rim); (b) the dnd5e
square/cube template quirk; (c) *Walled Templates* is a known module
dependency for wall-aware AoE in Foundry.
