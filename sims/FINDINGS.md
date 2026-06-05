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

**Conclusion (Monte Carlo):** the "squishy alpha-death" concern is **largely
resolved** — no PC dies to the round-1 breath anymore. The residual is (a)
the Wizard's slightly-exposed start (27% R2 death) and (b) inherent
deadliness (33% win is a real calibration datapoint for a solo-CR-17 boss,
useful to Trusight). No engine fix warranted; the AI/formation is behaving
reasonably. The Monte Carlo harness itself is the deliverable.

---

# Adventuring-day harness (2026-06-03) — nova-pacing exercised

Built `sims/adventuring_day.py`: one L13 party run through a graduated
6-encounter day (manticores → ogres → *short rest* → wyverns → vampire
spawn → *short rest* → fire giant → **Adult Red Dragon climax**), with
persistent HP / slots / resources, `encounters_remaining` decrementing each
fight, a Hit-Dice short-rest heal approximation, and an end-of-day long
rest. This is what finally *exercises* the nova-late slot-cost fix (#180)
and seeds the adventuring-day build-rubric.

**Result (seed 42):** the party clears all five mediums, then **wipes on
the dragon in 2 rounds** — but the *high-level* slot count tells the story:

| enc | rem | spent (all) | **hi-slots (≥4) left** | outcome |
|---|--:|--:|--:|---|
| manticores | 5 | 12 | 15 | win |
| ogres | 4 | 11 | 13 | win |
| wyverns | 3 | 3 | 13 | win |
| vampire spawn | 2 | 0 | 13 | win |
| fire giant | 1 | 0 | 13 | win |
| **dragon** | 0 | 0 | **13** | **LOSS** |

**Nova-pacing IS working** — the casters spent only **2 high-level slots
all day** (15→13), winning the mediums on *low* slots + the martials, and
arrived at the climax with **13 big guns conserved**. The early "12/11
spent" were 1st–2nd-level slots. (Initial hypothesis "they blew big slots
early" was *wrong* — the hi-slot column disproved it before write-up.)

**The real bottleneck is survival, not pacing.** The party reached the
dragon *depleted* (HP) and got alpha-struck before deploying the conserved
nova — a 2-round wipe with 13 high slots unspent. *"You conserved for the
boss but arrive too wounded to use it."* So the **danger-override (c) is
moot here** (climax `rem=0` ⇒ cost already 0; nothing to override) — it
only matters for a deadly fight *early* in the day. The dominant lever is
the same **climax-deadliness / arrive-depleted** dynamic, not slot pacing.

**Status:** PR-1 (nova-late formula) validated end-to-end; the day harness
is the deliverable (+ adventuring-day build-rubric foundation). Deferred:
richer rest/recovery (a pre-boss long rest); encounter XP-budget tuning.

**(c) early-deadly-fight override — DONE.** `encounter_danger(actor, state)`
(in `engine/core/spell_slots.py`) returns 0→1 from two reactive HP signals
(aggregate party depletion ramping 50%→15%; acute single-ally peril below
25% own-HP), and `candidate_slot_cost` scales the nova-late penalty by
`(1 − danger)` — so a deadly EARLY fight collapses the conserve-early cost
and casters nova now. Reactive by design (nova once a fight *reveals* itself
deadly, not pre-emptively at full HP); predictive enemy-DPR term deferred to
v2. No-op at the climax by construction (rem=0 ⇒ base already 0), matching
the moot-at-climax note above. Unit-locked in `test_deadly_fight_override.py`;
the graduated day-42 seed is survivable-to-climax so the override rarely
fires there — its job is the *off-curve* deadly fight, and the dominant
remaining lever stays the climax arrive-depleted dynamic (separate item).

---

## 2024 DMG budget calibration — the day was never a real attrition day

Built `engine/core/encounter_budget.py` (2024 DMG model: Low/Moderate/High,
per-character × party-size, spend = **raw stat-block XP sum, no 2014
multiplier, no daily budget**) and ran the *old* `adventuring_day.py` roster
through it for the 4×L13 party (budgets: low **10,400** / mod **16,800** /
high **21,600**):

| old encounter | spent XP | 2024 difficulty |
|---|--:|---|
| Manticore flight | 2,100 | sub-Low |
| Ogre raiders | 1,800 | sub-Low |
| Wyvern pair | 4,600 | sub-Low |
| Vampire spawn ambush | 5,400 | sub-Low |
| Fire giant | 5,000 | sub-Low |
| **Adult Red Dragon** | **18,000** | **High** (3,600 headroom) |

So **every pre-climax fight was SUB-LOW** — the "day" was five trivial
skirmishes then a High boss, *not* a graduated attrition day. The earlier
"arrive depleted" reading was an artifact: depletion came from fights
*grinding 20-30 rounds* (decision-layer inefficiency), not from honest
budget pressure. (The climax itself is a textbook RAW **High** for 4×L13 —
**not** over-budget — so the boss difficulty was never the problem.)

**Recalibrated the day** to a real budget ramp — `Skirmish line` (Low 9,700)
→ four Moderates (15,000-16,500, two short rests) → `Adult Red Dragon` (High
18,000); all ≤2 monsters/character (no "Many Creatures" advisory).

**The calibrated day exposes the binding constraint.** Across seeds 1/7/42
the party can't reliably clear even the **Low** warm-up (seed 7 TPK'd on it)
or the first **Moderate** (seeds 1, 42 wiped on `Giant raiders`, a 3-fire-
giant Moderate that ground **45 rounds**). A Moderate 3-monster fight should
end in ~4-6 rounds. The cascade: **naive decision-layer → fights run ~10×
too long → PCs drop → the danger-override (PR #184) novas → 25-31 slots gone
on a *Low* fight → next fight unwinnable.** The override isn't wrong (the
party genuinely *is* depleted after a 23-round slog); the **upstream combat
decision-quality is the root cause** — which is exactly the #1 lever the
stocktake named ("optimized buildable, not accurate; decision layer naive").

The sub-Low day masked this (trivial fights win despite inefficiency); the
budget-calibrated day makes it measurable. **Next dominant lever: combat
decision efficiency (focus-fire / target selection / stop the grind), not
content or pacing.** `slot_cost_ehp`'s `ENCOUNTER_DAY_DIVISOR` reframed as
an explicit tunable (2024 has no daily budget to cite). Long-rest-before-boss
stays a deferred *measured* flag, not a default (would collapse the gradient).

---

## Decision-layer grind diagnosed: the control-thrash death-spiral

Traced the 3-fire-giant Moderate fight at full resources (`sims/_trace_grind.py`,
reconstructs each turn's action from the event log). The grind has a clear
cause — **only 6 of 35 PC turns (17%) dealt any damage**; the rest were
CONTROL (11) / CAST (9) / HEAL (3). The casters **re-cast Hypnotic Pattern
every round** (rounds 1-3), then **Cloudkill every round** (4-7); when stopped
from re-casting the *same* spell they **thrash between control spells**, each
switch DROPPING the working concentration to deploy another. They never
transition from control to *killing*. The giants ended at 103/103/61 of 162;
the party lost.

**Fix (this PR): concentration-aware candidate filter.** While already
concentrating, `generate_candidates` suppresses every concentration-spell
candidate (you hold only one effect; casting another wastes it or churns it).
The caster keeps its control and falls through to damage. Result on the
isolated 3-fire-giant fight: **~certain loss → 8/10 wins** (seeds 1-10, median
~13 rounds). Unit-locked in `test_concentration_candidate_filter.py`; the 51
Hex/Hunter's-Mark/Ranger/Warlock/Spirit-Guardians/Bless tests still pass.

**v1 limitation + revealed follow-ups:**
- The blunt rule also forbids a legitimate concentration *upgrade* (drop a
  stale Hunter's Mark for Hold Monster on the boss). Principled fix = score a
  concentration candidate NET of the active effect's value (cast only if
  strictly better). **Deferred (bug C-proper).**
- **Bug D — idle-while-concentrating: FIXED.** The IDLE(hold)=21 tally was
  **16 the Bard** — its only damage action was a melee rapier (no ranged
  cantrip), so a concentrating Bard at range had nothing to chip with.
  Root cause was a **content gap**: `f_vicious_mockery` + its save-cantrip
  builder existed but were never granted to / dispatched for the Bard. Wired
  it (pc_schema builder gate + `f_vicious_mockery` on the Bard's L1 features).
  Result on the isolated 3-fire-giant fight: **8/10 → 10/10 wins** (both
  long-loss tail seeds 4/10 flipped to 12-round wins); Bard idle 16→1; CONTROL
  14→3; damage-no turns 83%→58%. Unit-locked in `test_vicious_mockery.py`.
- **Bug E — Fighter idles ~half its turns: FIXED (and it was NOT engagement).**
  The Champion had valid in-reach attack candidates yet did nothing. Cause: the
  single `multiattack` candidate was stamped with `in_range[0]` (the FIRST
  enemy by actor order = a 5-HP incapacitated giant), and the scorer
  overkill-caps multiattack eHP at the stamped target's HP → score ~5, beaten
  by a self `defensive_buff` (~10.7) — while a 23-HP giant in reach went unhit.
  Fix: stamp the **highest-HP in-reach enemy** (the un-capped full-output
  value; execution re-picks targets anyway). Result: total idle 12→5 (Fighter
  6→3), median 12→10 rounds, 10/10 held. Unit-locked in
  `test_multiattack_target_stamp.py`.
- **Residual (bug B-ish):** a self `defensive_buff` scoring ~10.7 still edges a
  *5-eHP* kill when the only reachable enemy is near-dead (removing a whole
  creature is worth more than its scrap of HP). Defensive over-valuation +
  "finish the low-HP enemy" remain. Deferred.

### Cumulative checkpoint — end-to-end calibrated day (after 4 decision fixes)

After concentration-thrash (#187) + Vicious Mockery (#188) + multiattack-stamp
(#189), re-ran the full calibrated day (seeds 1/2/3/7/42). **Failure point
moved from encounter 0-1 → encounter 3-4:**

| seed | wipes at | encounters cleared |
|---|---|--:|
| 1 | enc 4 Giant vanguard | 4 |
| 2 | enc 1 Giant raiders | 1 |
| 3 | enc 3 Wyvern stoop | 3 |
| 42 | enc 3 Wyvern stoop | 3 |
| 7 | enc 4 Giant vanguard | 4 |

Baseline (pre-fixes) TPK'd at enc 0-1 every seed. The party now survives
**3-4 of 6** encounters; the dragon (enc 5) is still unreached but the binding
constraint has shifted off the early fights.

**New lead — Vampire ambush round-cap grind.** Enc 2 (6 vampire spawn + 2
wyvern, 8 creatures) consistently runs **49-51 rounds → `round_cap_reached`**
(seeds 1, 42). A *different* grind than the fire-giant one — likely
target-selection thrash across many small **regenerating** enemies (vampire
spawn regen). It's both a time-sink and the attrition source that softens the
party for the enc 3-4 wipes. **Next diagnostic target** (trace the vampire
ambush the way `_trace_grind.py` traced the fire giants).

### Vampire-ambush grind diagnosed → it's PERMANENT DEATH AT 0 HP (no revival)

Traced it, and the round-cap is a **symptom, not an encounter bug**:
- The vampire ambush in **isolation at full resources** is a 6-round crush
  (851 dmg, zero regen, clean win) — so the encounter AI is fine.
- In the **day**, enc 1 (Giant raiders) runs 23 rounds and **kills the Fighter
  AND the Wizard** — the party's two damage dealers. Enc 2 then has only the
  **Cleric + Bard** (both support) vs 8 enemies → 51-round stalemate
  (`round_cap_reached`), 42% idle, 4 enemies still near full HP, **Cleric ends
  at full HP (107/107)**.

Root cause: **`primitives.py` sets `is_dead = True` the instant a PC hits 0 HP**
— there is **no downed / dying / death-saving-throw state for PCs**, and no
revival. RAW 2024: a PC at 0 falls unconscious and **any healing returns it to
the fight**. The Cleric finishing enc 2 at full HP with Healing Word + Cure
Wounds unused is the tell — in real play it would pop the downed Fighter/Wizard
back up and the party would keep its damage. Instead they're permanently dead
from enc 1, so every later fight is a 2-support-PC stalemate.

**This is the dominant day-level lever — a RAW correctness gap, not a decision
bug.** A downed/death-save/revival subsystem (0 HP = unconscious + death saves;
healing revives; massive-damage instant-death rule; stabilization) would let
the party recover its fallen damage dealers mid-fight and likely transform the
end-to-end day result. Bigger than any single decision fix; scoped as its own
feature. (Secondary: a 2-PC fight that can neither win nor lose should *resolve*
or flee, not idle 42% to the round cap.)
- Healing un-threatened allies (HEAL spam) — heal eHP should scale with actual
  incoming danger, not missing HP. **Deferred (bug B).**

### Death-save subsystem SHIPPED (Stages 1-3) → day reaches encounter 4

Built the downed/death-save/revival subsystem the diagnosis called for:
- **Stage 1** (#191): 0 HP = unconscious + dying (death saves at turn start,
  3 successes stable / 3 fails dead, nat20 revive, damage-while-dying auto-fail,
  massive-damage instant death). Monsters still die outright.
- **Stage 2** (#192): any positive heal revives a dying ally; dying allies join
  the heal target pool; the heal scorer values reviving at max desperation.
- **Stage 3**: revival is explicitly prioritized — a "back in the fight" bonus
  = one round of the revived ally's DPR, so the AI prefers reviving (and prefers
  reviving the bigger damage dealer) over chip damage / topping off a healthy PC.

**End-to-end day (seeds 1/2/3/7/42): TPK at enc 0-1 → consistently reaching
enc 4** (the 5th of 6 fights). The **Vampire ambush no longer round-caps** — it
resolves as a win (30-40 rounds); the party **holds 3 PCs through enc 2** via
mid-fight revival (was dropping to 2). Seed 2 is a fast unlucky enc-1 wipe
(variance). The full subsystem is the single biggest day-level mover so far.

**New bottleneck (next):** the **Wyvern stoop (enc 3) grinds 43-45 rounds** and
drops the party to 2 PCs; with no long rest, terminal attrition finishes them at
enc 4 (Giant vanguard) — the dragon (enc 5) stays unreached. Two leads: (1) the
wyvern-stoop grind (5 wyvern + 1 fire giant — flying/kiting target-selection?),
(2) the recovery question (the deferred pre-boss long-rest *measured flag* / Hit
Dice between fights). Also still deferred: bug B (heal-spam on un-threatened
allies), and the unconscious-condition effects (advantage to attackers,
auto-fail STR/DEX) the death-save subsystem hasn't modeled yet.
