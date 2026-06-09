# Addendum to the Red Team Review: Two Design Extensions

Append this to the original review request (`red_team_obstacle_course_prompt.md`).
Two extensions to the obstacle-course design have been proposed since the
original brief. Review both with the same adversarial posture.

---

## Addendum A: Premiere-Feature Coverage Matrix

The original encounter taxonomy is **encounter-centric** (what kind of fight is
this?). Class power, however, lives in **premiere features** — Aura of
Protection, Rage, Bardic Inspiration, Divine Smite, Channel Divinity, Action
Surge, Cunning Action, Metamagic, Wild Shape — and nothing in an
encounter-centric taxonomy guarantees that any given feature is ever *stressed*
(placed in a situation where its contribution swings the outcome).

Examples of the mismatch:

- **Aura of Protection** (+CHA to saves, allies within 10 ft): its real cost is
  positional — clustering for the aura conflicts with spreading against AoE.
  Only an encounter with BOTH save pressure AND AoE pressure reveals its true
  value.
- **Rage** (BPS resistance): overvalued by a physical-brute-heavy course,
  undervalued by a caster-heavy one. Its true power is the weighted average
  over realistic damage-type distributions.
- **Bardic Inspiration** (+d10 to a roll): worth far more at tight margins
  (AC 19 boss, DC 17 saves) than against low-AC fodder.
- **Divine Smite**: burst against single high-HP targets; wasted on swarms.

**Proposed fix:** after fixing the encounter list, build a coverage matrix
(feature × encounter) marking where each premiere feature is stressed. Adjust
or add encounters until every premiere feature has at least one stress test.
Validate empirically with the contribution ledger: a feature whose measured
contribution is ~zero across the whole course is either weak or untested — and
a single designed stress encounter distinguishes which.

**Your tasks:**

1. **Audit the concept.** Is feature-stress coverage the right validation
   layer, or is there a better formalism (e.g., capability-dimension coverage
   instead of per-feature)?
2. **The gerrymandering risk.** If we tune encounters until every feature
   "gets its moment," do we bias the course toward measuring features at their
   best — inflating versatile-looking scores for narrow features? Propose a
   principle that keeps the course NEUTRAL (e.g., encounter mix weighted by
   published-adventure frequency, not by feature-showcase needs) while still
   guaranteeing coverage.
3. **Enumerate the premiere-feature list** for the 2024 PHB classes (all 12)
   and flag which features our 7-category taxonomy already stresses vs which
   need a designed addition. Keep additions minimal — prefer modifying an
   existing encounter (e.g., adding an AoE threat to the save-heavy encounter)
   over adding new ones.

---

## Addendum B: eHP as the Unified Power Rating (Total / Offensive / Defensive)

### The framework

The simulator scores every action in **eHP (effective hit points)** — a single
currency where everything a character does is expressed as hit points swung:

- **Offensive eHP**: damage dealt, PLUS enablement of allies' damage (granting
  advantage, +to-hit buffs). Example: Web restrains 5 of 10 enemies (5 saved);
  the martials attacking restrained targets at advantage gain ~25% DPR — that
  uplift is offensive eHP created by the Web caster.
- **Defensive eHP**: healing delivered, damage prevented (AC buffs,
  disadvantage imposed on enemy attacks, save bonuses like Aura of
  Protection), and **denied enemy action** — control. Web restraining 5
  enemies with 10 DPR each denies up to 50 eHP/round for as long as they stay
  restrained ("stolen turns").

So a single Web cast might be worth 50 (denial) + 10 (advantage uplift) = 60
eHP in round 1, accruing further each round it holds.

The simulator already produces a per-round, per-actor contribution ledger
(damage dealt/taken, control eHP = denied enemy DPR × denial fraction, healing
eHP) from its event log, so realized-eHP accounting is an extension of
existing machinery, not new instrumentation.

### The proposal under review

Run specialty builds through the obstacle course and report, per build:

1. **Total eHP** — the headline power rating for the build/class/subclass.
2. **Offensive / Defensive split** — the build's power *shape* (a Champion is
   ~all offense; a Lore Bard is mostly enablement + denial).
3. **Like-to-like comparisons** — e.g., compare the 3rd-level subclass
   features of all Bard colleges by measuring each variant's eHP delta against
   the same base-class chassis (paired seeds, feature swapped).

### Your tasks — attack these specific problems

1. **Double-counting / attribution (the central problem).** The Web caster's
   advantage-uplift shows up inside the martials' realized damage. If we
   credit the uplift to the caster AND leave the damage with the martial, the
   party's summed eHP exceeds what actually happened. Propose a principled
   attribution rule. Candidates to evaluate:
   - *Counterfactual/marginal credit*: enabler gets (ally damage WITH effect −
     expected damage WITHOUT); attacker keeps the baseline. Cheap but
     order-dependent when multiple buffs stack (advantage + Bless + Inspiration
     on the same attack — who gets the overlap?).
   - *Shapley-value attribution* across contributing effects: order-independent
     and sums exactly to the realized total, but combinatorial. Is there a
     practical approximation at our scale?
   - Anything better from your knowledge of credit-assignment literature
     (sports analytics plus-minus, MMO damage-meter design, cooperative game
     theory).

2. **The counterfactual baseline for denial.** "Web denies 50 eHP/round"
   assumes all 5 restrained enemies would have dealt their full DPR. They
   might have missed, been out of range, or attacked a tank who'd absorb it
   harmlessly. Should denial be priced at expected DPR (cheap, biased high),
   simulated counterfactual (re-run the round without the control — expensive),
   or a discounted expectation? Also: denial of an enemy that dies next round
   anyway is worth one round, not 2.5 — how should remaining-enemy-lifetime cap
   the denial credit?

3. **Caps and saturation.** Offensive eHP is capped by enemy remaining HP
   (overkill is worthless); denial is capped by what enemies would actually
   have done. Are there other saturation effects (over-healing, stacked
   disadvantage sources where the second is worthless) the accounting must
   handle to avoid inflated totals?

4. **Normalization — what is "total" eHP a rate OF?** A Wizard's eHP is
   front-loaded (novas, then cantrips); a Champion's is flat forever. Compare:
   eHP per round, eHP per encounter, eHP per adventuring day, eHP per resource
   spent. A single number hides pacing. What's the right primary
   normalization for a power RATING, and what small set of companion numbers
   (e.g., eHP/day + eHP/round-at-rest-3-encounters-in) captures the shape?

5. **Validation against ground truth.** Total eHP is only a valid power
   rating if it predicts outcomes. Specify the calibration test: across
   builds, does total eHP correlate with win rate / rounds-to-win? What
   correlation threshold would you demand before trusting eHP rankings where
   win-rate deltas are too expensive to resolve? What does it mean if a build
   is high-eHP but low-win-rate (metric broken, attribution broken, or a real
   finding about non-converting power)?

6. **Like-to-like protocol.** For "compare all 3rd-level Bard college
   features": confirm the right design is paired-seed feature-swap on an
   otherwise identical chassis, with the eHP DELTA (not the build totals) as
   the endpoint. Identify where this breaks — features that change the build's
   playstyle enough that the AI's action distribution shifts (e.g., a college
   that adds a damage cantrip changes every turn's candidate set, not just the
   feature's own contribution). Is the delta then still attributable to "the
   feature"?

7. **Offensive/defensive split validity.** Some effects are genuinely both
   (killing an enemy faster IS damage prevention; a Spirit Guardians zone
   does damage AND area denial). Propose the bucketing rule, or argue the
   split should be a spectrum/third bucket (enablement, denial, sustain,
   burst) rather than binary O/D.

### Deliverable for this addendum

- Severity-ranked findings, as in the main brief.
- Your recommended attribution rule (task 1) stated precisely enough to
  implement, with its known failure modes.
- The validation protocol (task 5) as a concrete experiment we can run.
