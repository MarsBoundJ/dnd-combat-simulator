# First-Sim Findings — the "is a real fight plausible?" reality check

**Setup:** Tier-3 (level 13) party — Fighter/Champion, Cleric, Wizard/Evoker,
Bard/Lore — vs the Adult Red Dragon (CR 17). Seed 42. See `report.md` for
the round-by-round and `events.json` for the raw log.

**Result:** the dragon won in **2 rounds**, taking only **22 damage**
(234/256 HP left). 3 PCs dead, 1 fled. Dragon dealt **446**; party dealt
**22** — and **three of four PCs dealt ZERO**.

That outcome is **not plausible** — a level-13 party vs one CR-17 dragon
is a "deadly"-tier but winnable boss fight, not a 2-round flawless TPK.
The value is *why* it's wrong: the trace shows the **mechanics are
correct** and the **decision layer is naive**. This is stocktake risk #2
(the AI layer is the untouched soft underbelly) made concrete.

## ✅ Every mechanic fired correctly
- **Fire Breath**: 60-ft cone, DEX save DC 21, ~17d6 fire (~50–64 per PC).
- **Recharge**: spent round 1, rolled a 5 at the dragon's round-2 turn
  start → recharged → second breath. Exactly the recharge system working.
- **Legendary Actions**: Pounce fired after each PC's turn (3/round), pool
  reset at the dragon's turn. Working.
- **Saves, Second Wind, Healing Word** all resolved correctly.

The engine did its job. The problem is entirely in *how the agents chose
to act*.

## ❌ Decision-layer failures (the implausibility)

1. **PC retreat AI is monster-morale — and it fires on PCs.** The Bard
   fled on turn 1, triggered by `bloodied` (below half HP after one
   breath). PCs should not use creature flee-morale in a boss fight; this
   removed a whole PC from the encounter. **Fix:** suppress / heavily
   gate the retreat trigger for `side == pc` actors.

2. **Casters contributed ZERO damage.** Wizard and Bard each dealt 0;
   the Cleric only healed. The Wizard cast no offensive spell on its turn
   at all. The party's entire offense was the Fighter's 22. The casters
   aren't using their kits offensively (range/closing/candidate-selection
   issue). **Fix:** caster offensive decision-making — and note the
   adjacent trap: a fire-immune Red Dragon means the Evoker's Fireball
   would do nothing, so the AI also needs **damage-type / immunity
   awareness** in target/spell selection.

3. **The party started clustered inside the breath cone.** All four PCs
   were in one 60-ft cone, so a single breath hit everyone for ~55. Real
   parties spread out vs a dragon. **Fix:** encounter setup + spread-out
   positioning AI to avoid stacking in one AoE.

4. **Unanswered alpha strike.** The dragon won initiative, breathed turn 1
   (~55 × 4 ≈ 220 spread damage), then Pounced every PC turn. The party
   never landed a full round of offense before being crippled — a
   compounding effect of 1–3 above.

## Takeaway
Mechanics: trustworthy. eHP/DPR numbers: **not yet trustworthy** — not
because the rules are wrong, but because the decision layer plays PCs
badly (flees, idle casters, clusters in AoEs). The next high-leverage work
is the **AI/decision layer**, not more content. Concretely, in priority
order: (1) PC retreat suppression, (2) caster offensive selection +
damage-type/immunity awareness, (3) AoE-aware positioning.

This is exactly what the first sim was for. Stored for posterity — and as
the baseline we'll measure decision-layer fixes against.

---

# Run-2 Findings (2026-06-03) — post-casters re-run

**What changed since the baseline:** PC-retreat model (suppress monster
flee-morale for PCs), target-effectiveness gate, the Wizard's spell list
(#162), and the control spells (Polymorph #159, Hold Monster #160, Wall of
Force #165). Same setup + seed 42. Artifact: `report_run2_post_casters.md`
+ `events_run2.json`.

**Result:** the dragon still won, but in **4 rounds** (vs 2), brought to
**134/256** (~**122** damage dealt, vs 22). Casters **acted** this time;
the Bard correctly **fled as the last conscious PC** (not turn-1 morale).

| | Run 1 (baseline) | Run 2 (post-casters) |
|---|--:|--:|
| Rounds | 2 | **4** |
| Party damage dealt | 22 | **122** |
| Casters dealing 0 | 3 of 4 | Wizard + Bard now act |
| Retreat trigger | turn-1 `bloodied` (wrong) | `last_conscious_pc` (correct) |

## ✅ Confirmed fixed from Run 1
1. **PC retreat** — Bard now flees only as the last conscious PC, not on
   turn-1 morale. (Run-1 failure #1 resolved.)
2. **Casters act** — the Wizard casts and the Bard casts control;
   party offense is no longer "the Fighter alone." (Run-1 failure #2's
   "idle casters" half resolved.)

## ❌ Remaining decision-layer gaps (the new priority list)
1. **Big-gun selection** — the Wizard spent its one turn on a **cantrip
   (Ray of Frost, 19)** instead of Disintegrate / Polymorph. This is the
   deferred **nova-pacing / slot-opportunity-cost recalibration**: a
   free cantrip still out-scores a 6th-level nuke even in a boss fight.
   Needs the framework "last-fight = max slot cost" inversion (Phil input).
   *Highest offensive lever.*
2. **AoE positioning** — the party started clustered, so every Fire Breath
   caught all four (R1: 53/64/50/56; recharged R2, dropped both squishies).
   Spread-out movement so one breath can't hit the whole party. *Highest
   defensive lever; self-contained, no framework question.* (Run-1 #3.)
3. **LR-aware control sequencing (NEW)** — the Bard cast single-target
   save-or-suck (Hold Monster / Hypnotic Pattern) at the dragon both
   rounds; Legendary Resistance ate the saves. The AI has no notion of
   *draining LRs with cheap effects first, then landing real control.*
   Against a legendary boss this is correct RAW — the AI just doesn't
   sequence for it.

## Calibration note (not purely a bug)
A **solo Adult Red Dragon** vs an *unoptimized, clustered* L13 party is a
genuinely brutal encounter — losing here is a legitimate datapoint, not
proof of an AI error. The party is effectively playing at **dial-1** (no
positioning, no nova, no LR-stripping). This run is a useful input to the
optimization-dial / encounter-tuning calibration, not just the AI backlog.

## Takeaway
Run 1 proved mechanics-correct / decision-naive. Run 2 shows the first
wave of decision fixes **working**, and sharpens the remaining list to:
(1) big-gun/nova selection, (2) AoE-aware positioning, (3) LR-aware
control. Content is still not the bottleneck — the AI/decision layer is.

---

# Run-3 Findings (2026-06-03) — positioning stack live + spread starts

**What changed:** the full positioning stack landed — `max_aoe_coverage`
(monster orients its breath to the eHP-max placement, #171) + PC
**de-cluster** movement (`best_position` wired into `_move_to_engage`,
#173) — and the boss sim now seeds the party in a **spread approach
formation** (~45-55 ft, fanned to y=±8) instead of stacked at 15 ft
(positioning-model §5; needed because the 2024 Adult Red Dragon has
**Initiative +12** and almost always breathes first — RAW). Artifacts:
`report_run3_positioning.md` + `events_run3.json`; reproducible via
`sims/run_boss_sim.py` (seed 42 headline + a 5-seed distribution).

## ✅ The headline: the alpha-strike is defused
**The round-1 breath caught 2 PCs, not 4 — across ALL FIVE seeds.** The
flanking Bard + Cleric (y=±8) sat outside the dragon's best cone entirely.
Fights stretched from 2-4 rounds (runs 1-2) to **9-51**.

| seed | first to act | rounds | breath-1 hits | party dmg | dragon HP | PCs standing |
|---|---|--:|--:|--:|--:|--:|
| 42 | Dragon | 9 | **2** | 87 | 169/256 | 0 (1 fled) |
| 1 | **Cleric** | 30 | **2** | 144 | 119/256 | 0 |
| 7 | Dragon | 50+ | **2** | 112 | 163/256 | 2 |
| 13 | Dragon | 8 | **2** | 103 | 153/256 | 0 |
| 99 | **Bard** | 50+ | **2** | 32 | 243/256 | 2 |

Initiative is genuinely rolled — seeds 1 and 99 show a PC winning it. The
spread + coverage worked exactly as designed: **breath-1 hits 4 → 2.**

## ❌ New finding: defense-only positioning over-corrects into passivity
The party still loses or **stalemates to the 50-round cap** (seeds 7, 99)
with tiny damage (seed 99: **32** over 50+ rounds, dragon barely scratched).
Cause: `best_position` is **defense-only** — it minimizes AoE exposure
subject to a *binary* "can act" gate, with **no offensive gradient**. So
casters pick the safest in-range square and plink, never committing. The
derived stats are damning: Wizard 1 attack (a 12-dmg cantrip), Bard 0 dmg
(control-only), Cleric 0 (heals) — the Fighter's 75 is nearly the whole
party offense, same as run 1.

## ❌ Still open from run 2 (unchanged — these weren't this phase's job)
- **Big-gun selection** — Wizard still casts a cantrip, not Disintegrate/
  Polymorph (the deferred nova-pacing / slot-opportunity-cost
  recalibration; needs Phil's framework call). *Now clearly the #1
  offensive blocker.*
- **LR-aware control** — Bard's saves still eaten by Legendary Resistance.

## Takeaway
Run 3 **confirms the positioning fix** (alpha-strike defused, survival 3-10×
longer) and isolates the next problem precisely: **the party now survives
but can't kill**, because (a) positioning is defense-only with no offensive
pull, and (b) casters still don't fire their big guns. The next levers are
offensive: an **offensive term** in the positioning utility (stop
over-prioritizing safety) and the deferred **nova/big-gun selection**.
Defensive AI is now good; offensive AI is the frontier.

### Run-3 ROOT CAUSE + fix (2026-06-03) — it was an empty dict
A round-1 candidate **trace** corrected the "casters don't fire big guns"
diagnosis: it was **neither the slot-cost formula nor knowledge** — the L13
Wizard had **`spell_slots: {}`**. All 22 leveled spells were filtered at
candidate generation (no slot to cast them), leaving only 2 cantrips; it
cast Ray of Frost because Fire Bolt scored 0 vs the fire-immune dragon.
Cause: `c_wizard.yaml` declared no `class_resources.spell_slots` (the #162
spell-list wiring never added the slot table; every other caster has it).

**Fix:** added the full-caster slot progression to `c_wizard`'s level_table
(mirrors `c_cleric`). The `report_run3_positioning.md` artifact is
regenerated post-fix:

| seed | party dmg (pre-fix) | **party dmg (slots fixed)** | dragon HP |
|---|--:|--:|--:|
| 42 | 87 | **247** | **9/256** (nearly dead) |
| 1 | 144 | **272** | **3/256** |

The Wizard now novas (Disintegrate / Cone of Cold). **Lesson: trace before
recalibrating** — we nearly rebuilt the slot-cost formula for a bug that
was an empty dict.

---

# Monte Carlo calibration (2026-06-03) — squishy alpha-death + variance

Ran the boss encounter over **60 seeds** (`sims/boss_montecarlo.py`) to
quantify the variance/alpha-death finding instead of guessing from 5 seeds.

**Headline numbers (full positioning + spell stack + engage fix):**
- **WIN 33% / LOSS 66%** vs a *solo* Adult Red Dragon (CR 17) — a
  legitimate "deadly-but-winnable" result for an unoptimized L13 party, not
  a broken AI. Party damage median **131** (of the dragon's 256), max 285.
- **Round-1 alpha-death = 0** across all four PCs. The original "one breath
  kills the whole party" is **solved** by the spread + positioning work.

**Per-PC death timing (the alpha-death signal):**
| PC | dies R1 | dies R2 | survives | note |
|---|--:|--:|--:|---|
| Bard | 0 | 0 | 95% | wide flank — escapes the breath |
| Cleric | 0 | 0 | 35% | flank; dies ~R7 |
| Wizard | 0 | 27% | 27% | residual: starts partially IN the cone |
| Fighter | 0 | ~2% | ~3% | tank, dies ~R4 absorbing |

**Counterintuitive result — protect VALUE, not HP.** Widening the
lowest-HP Wizard to a far flank eliminated its round-2 death (16 → 0 runs)
**but dropped the win rate 33% → 13%** — because it pushed the *Cleric*
(healer) into the cone, and losing the healer's sustain costs more wins
than the Wizard's nova. So the original formation is kept. **Design lesson
(feeds the positioning-value / superagent work): a PC's protect-priority is
its eHP CONTRIBUTION — the healer's party-wide sustain outranks the
glass-cannon's offense — not its raw HP.**

**Conclusion:** the "squishy alpha-death" concern is **largely resolved** —
no PC dies to the round-1 breath anymore. The residual is (a) the Wizard's
slightly-exposed start (27% R2 death) and (b) inherent deadliness (33% win
is a real calibration datapoint for a solo-CR-17 boss, useful to Trusight).
No engine fix warranted; the AI/formation is behaving reasonably. The
Monte Carlo harness itself is the deliverable — a reusable per-encounter
distribution / metric tool.
