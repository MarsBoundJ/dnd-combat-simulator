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
   they catch you. **Party-coupled**: clustering raises the chance one AoE
   catches multiple members, so this term reads positions of *all* allies,
   not just self. (A 60-ft cone or 20-ft sphere is the canonical case.)

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
