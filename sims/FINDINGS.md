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
