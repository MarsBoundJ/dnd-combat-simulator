# Positioning & Targeting Model — Red-Team Brief

*Self-contained snapshot for external review (2026-06-03). Design stage —
NOT yet implemented. Goal of this review: **soundness + completeness check.**
Poke holes, find edge cases, surface gaps or modeling errors. We are NOT
seeking new feature ideas — just a double-check. Our own known deferrals are
listed in §11 so you can look **past** them and find anything else.*

---

## 1. What this is

How a **D&D 5e (2024 rules) turn-based combat simulator** decides two
linked things:
1. **Positioning** — where a creature (PC or monster) moves on its turn.
2. **AoE targeting** — where/how a creature aims an area effect (dragon
   breath, Fireball, Lightning Bolt) to hit the most valuable set of targets.

The simulator runs encounters autonomously to measure combat balance, so the
AI must play *both* sides plausibly. A first end-to-end test (level-13 party
vs an Adult Red Dragon) exposed the problem: the party **clustered**, so one
60-ft breath cone hit all four PCs every round. "Spread out" is the obvious
fix — but naive spreading breaks other things (below), so we designed a
proper model instead.

## 2. Relevant simulator substrate (context you need)

- **Grid:** 2D square grid, integer `(x, y)`, 5 ft per square. **Chebyshev**
  distance (diagonals count as 5 ft, per the 2024 PHB). No z-axis yet.
- **AoE is already geometric:** functions return who is inside a `sphere`
  (radius), `cone` (length, snapped to 8 directions, grid rule = lateral ≤
  forward/2), `line` (length × width along a direction), or `cube` (axis-
  aligned). Membership = **a creature is hit iff its square's center is
  inside the shape.**
- **Barriers / walls:** a wall is a line segment with independent blocking
  channels — `move`, `sight`, `sound`, `light`. "Line of effect" between two
  points is broken if a blocking segment crosses the straight line between
  them. Movement, single-target targeting, and AoE spread all respect walls.
- **Concentration:** a caster maintaining a spell makes a Constitution save,
  `DC = max(10, floor(damage_taken / 2))`, on **each** instance of damage;
  failure ends the maintained spell. Most arcane casters lack CON-save
  proficiency.
- **Opportunity attacks:** leaving a hostile creature's melee reach (without
  Disengaging) provokes one melee attack from it.
- **Optimization dial (already exists):** a 1–5 scale governing how well an
  actor plays — 1 = clueless, 5 = optimal. Used to model parties/monsters of
  different skill.
- **Actors are single points** (one `(x, y)`); large creatures are not yet
  modeled as multi-square footprints.

## 3. Core idea: positioning is an eHP-utility tradeoff

**eHP = "effective hit points"** — the simulator's common currency: the
expected HP-equivalent value of an effect (damage prevented, damage dealt,
a denied enemy action, etc.).

Each turn, an actor's movement chooses the **reachable destination that
maximizes a positioning utility**:

```
utility(dest) =
      Σ ally-aura benefit         (+)
    − Σ AoE exposure              (−)   [adversary-aware; see §5]
    − concentration-break risk    (−)
    − melee exposure              (−)
    + cover                       (+)
    + support proximity           (+, small)
  subject to:  action enablement  (HARD CONSTRAINT)
```

- **AoE exposure (−):** expected eHP lost to enemy area attacks that could
  catch you; **party-coupled** (clustering raises the chance one AoE hits
  multiple allies, so this reads all allies' positions).
- **Concentration-break risk (−):** if concentrating, `P(hit) × P(fail CON
  save) × (remaining eHP value of the maintained spell)`. A ~55-damage breath
  ⇒ DC ~27 ⇒ a non-proficient caster usually fails ⇒ loses the spell. For a
  controller this can be the single biggest term.
- **Melee exposure (−):** being inside an enemy's reach × its expected melee
  output, weighted by your AC. Squishies are punished hard.
- **Ally-aura benefit (+):** eHP gained by standing inside an ally's
  beneficial aura (e.g. a Paladin's +CHA-to-saves aura, a Cleric's damaging
  aura engulfing an ally's enemy).
- **Action enablement (hard constraint):** a destination must keep ≥1 useful
  action in range AND with clear line of effect, else the actor's offensive
  eHP is 0. A square that disarms you is invalid no matter how safe.
- **Cover (+):** +AC / +DEX-save → defensive eHP (incl. self-made cover via
  illusions, later).
- **Support proximity (+, small):** within one move of an ally who may need a
  touch-range rescue.

**"Spread out" and "cluster up" both emerge from this math.** There is **no
hard-coded doctrine** — we resolve the cluster-vs-spread question purely by
computed eHP. (Design decision; we are open to being told this is wrong.)

## 4. The cluster-vs-spread crux — worked example

A Paladin is in melee with a dragon; a melee Fighter must decide whether to
stand in the Paladin's +save aura.

- **Aura value to the Fighter:** breath = 50 dmg, Fighter saves ~50% ⇒
  expected ≈ 37 eHP taken; +5 to the save (say → ~75%) drops it to ≈ 31 ⇒
  **aura benefit ≈ 6 eHP.**
- **Spread value to the party:** if standing apart forces the breath to hit
  **one** PC instead of **two**, that erases ≈ 37 eHP (a whole target's
  breath). **37 ≫ 6**, so spread dominates — *unless the dragon can re-group
  them anyway:*
- **Adversary response:** a smart dragon will **spend ~15 eHP of opportunity
  attack to move and line up a 2-target cone worth ~74** (37 × 2). 74 ≫ 15,
  so it pays — two melee PCs get grouped regardless of which side of the
  dragon they stand on.
- **Emergent optimum:** **one durable PC tanks melee; the rest fight from
  range, spread beyond the boss's cone-alignment reach** ⇒ the best boss AoE
  catches ~1 PC/round.
- **Caveats:** (a) **composition-bound** — a two-melee party can't reach the
  one-tank ideal; the model outputs "least-bad" (stand far apart, tax the
  boss's movement + OAs). (b) The real lever is the **boss's marginal cost to
  catch a 2nd target**, which wide spacing inflates. (c) **Flight** lets a
  boss reposition almost for free — our 2D model understates this.

## 5. Adversary-aware exposure + single-ply minimax

The AoE is **mobile and the enemy is a maximizer**, so AoE exposure is
evaluated against the **boss's best response**: it will move (up to speed)
and orient the shape to catch the most PCs, net of the OA/movement cost it
will pay. Effective danger ≈ **`AoE footprint + boss reach/move − OA-cost-
it'll-eat`** — *not* "is an ally within radius R right now."

We resolve this **single-ply**: the boss places its single best AoE against
the formation; PCs evaluate a move against that one best response. No deeper
back-and-forth (we-move-anticipating-its-move-anticipating-ours) for now.

## 6. The optimization dial governs two axes

1. **Information quality** — dial 5: knows exact AoE footprints, recharge
   odds, aura ranges, enemy reach (solves the tradeoff exactly). Dial 1:
   none → naive clustering. Mid: qualitative ("it's a dragon, don't bunch")
   with under-resolved estimates.
2. **Optimization breadth** — how many utility terms are even considered.
   Dial 1: none (greedy move-to-enemy only). Mid: AoE + melee + enablement.
   Dial 5: all terms + the full tradeoff.

The observed clustering is the **dial-1 baseline**.

## 7. Starting geometry + initiative

- Boss fights open with the party **entering the lair** at ~**50–75 ft**
  with maneuver room — not stacked at 15 ft. Realistic setup matters because
  of the next point.
- **The boss does NOT automatically act first.** Initiative is rolled every
  encounter, so boss-first is *probabilistic*. **2024 surprise = Disadvantage
  on the initiative roll, NOT a lost turn.** A smart boss only *engineers*
  initiative advantage (surprise setup, Invisibility, high init mod), which
  shifts odds but doesn't guarantee going first.
- Therefore the **round-1 alpha strike is a RISK, not a certainty.** The
  positioning model weighs AoE exposure as an **expected cost over the
  initiative distribution**; PCs who act first can preempt (spread, take
  cover, land control before the breath).

## 8. The AoE coverage routine (shared by both sides)

**One function** answers "how many agents can this shape catch given the
caster's movement?" — used by the **monster** (maximize targets hit) AND by
the **PC exposure term** (run the boss's routine adversarially: "worst AoE
the boss can land on us").

```
max_aoe_coverage(shape, attacker, reachable_apexes, targets)
  -> { apex, orientation/center, covered:[ids], n_covered }
```

**Unifying principle:** the optimal placement can always be slid/rotated
until its boundary grazes actual target points, so we enumerate a finite,
**target-derived** candidate set rather than sweeping continuous space.

| Shape | Method |
|---|---|
| **Cone** | **Angular interval stabbing.** From an apex, each in-range target `p` gives an arc `[bearing(p)−α, bearing(p)+α]` of facings that would hit it. The best orientation = the **direction covered by the most arcs** (sort the 2n arc endpoints, sweep a +1/−1 counter). The optimal facing is always an arc endpoint. O(n log n) per apex. |
| **Line** | "Max points through the apex" — bucket targets by bearing (thin line) or fatten arcs by `width÷distance` (slab) and stab as above. **Also evaluate the straddle option** (see §9). |
| **Sphere** | **Max-coverage disk.** Candidate centers = the (≤2) radius-`r` circles through each target pair ≤ `2r` apart; score coverage at each. O(n²). |
| **Cube (axis-aligned)** | **Sliding-window sweep** — sort by x, slide an `s`-wide strip; within it slide an `s`-tall window in y. Axis-alignment (no tilt) keeps this cheap. |

- **Movement:** useful apexes are target-derived (reachable squares within
  the shape's length of ≥2 targets), pruned with grid/spatial hashing.
- **Now vs scalable:** at our scale (≤ ~8 agents, 8-direction grid cones),
  brute-force pruned-apex × 8 directions using the existing membership
  functions is exact and trivially fast. The angular methods above are the
  scalable upgrade for finer/continuous orientation or many targets (e.g. a
  wizard Fireballing 20 enemies); hybrid = angular *proposes* facings, the
  grid functions *verify* membership.

## 9. Line attacks — straddling, angling, membership

A "5-ft-wide" line is a **floor, not a ceiling** for an optimizing caster:
- **Straddling:** aiming the line down a grid *border* (not a row center)
  makes it catch **both adjacent rows** — effectively 2 squares wide,
  roughly doubling coverage. The coverage routine evaluates **both** the
  centered (1-wide) and straddled (2-wide) placements and keeps the better.
- **Free angling:** lines need not follow rows/columns; a clever angle
  threads off-axis targets. (Deferred: we currently snap to 8 directions.)
- **Membership = center-based** (a square is hit iff its center is in the
  strip), consistent across all shapes. The stricter "any square the
  template touches" variant is out of scope.
- **Dial-gated:** dial 5 straddles/angles to maximize; dial 1 fires straight.
- **Exposure implication:** an enemy line is effectively **2 rows wide and
  freely angled**, so allies in *adjacent* rows aren't safe — spread
  **perpendicular** to the likely line, not just along it.

## 10. Renderer compatibility (Foundry VTT)

The sim will later visualize in Foundry VTT. We verified our choices match
Foundry's model: center-based membership = Foundry's core default; our
move/sight/sound/light wall channels = exactly what Foundry's wall-aware
template tooling keys off (so "Wall of Force blocks a Fireball" maps ~1:1);
free-angle/straddling are natively supported by Foundry (continuous
placement). **The sim stays authoritative** for who-is-hit; Foundry renders.
(Included only to confirm the model isn't painting us into a corner — not
core to the logic you're reviewing.)

## 11. Our KNOWN deferrals / assumptions (look PAST these)

These are already on our list — please find issues **beyond** them:
- **Single-point actors** — large creatures not modeled as multi-square
  footprints (affects both who-they-hit and who-hits-them).
- **8-direction grid only** — no free-angle cones/lines yet.
- **2D only** — no flight / z-axis / vertical positioning; understates
  flying-boss mobility.
- **Single-ply minimax** — no deeper recursion.
- **Cover term not built**; needs a cover→AC/save mapping from wall geometry.
- **Ally-aura term** needs aura content that isn't all built yet.
- **Concentration term** needs an estimate of "remaining eHP value of a
  maintained spell."
- **Dial → (info, breadth) config surface** not yet specified.
- **Grid cone/line approximation** may differ from a continuous renderer at
  the shape's rim.
- **No modeling yet of:** difficult terrain, readied actions, forced
  movement as a positioning tool, escape-route/kiting value, or
  total-vs-partial cover grades.

## 12. Specific things to stress-test (soundness/completeness)

1. **Is a utility term missing or mis-signed?** (threat/focus-fire, being
   surrounded, escape routes, terrain, readied reactions, control-denial
   value, the value of *forcing* the boss to spend movement/OAs.)
2. **Does single-ply produce exploitable/dumb play** in any common setup
   (e.g. the boss "wastes" its best AoE because it can't see the PC's
   follow-up; PCs over-spreading and losing focus fire)?
3. **Are the coverage algorithms correct/complete?** Cone angular-stabbing
   edge cases (apex on a target; ties; cone wider than 180°?); line straddle
   + diagonal; disk pair-center enumeration; cube sweep.
4. **Does center-based membership systematically mis-target** vs real grid
   play (large creatures, partial overlaps, corners)?
5. **Is the concentration model sound?** `DC = max(10, floor(dmg/2))`,
   per-instance, and the "value of the maintained spell" weighting.
6. **Is "pure computed eHP, no doctrine" safe**, or are there situations
   where it yields clearly-unrealistic positioning a real player would never
   choose?
7. **Mutual-dependency / move-ordering:** within one party's turn sequence,
   PC A's best position depends on where PC B ends up (and vice versa). Does
   a per-actor greedy choice mis-handle this? Should it?
8. **Are two dial axes (info, breadth) enough**, or is a third needed (e.g.
   risk tolerance / aggression)?
