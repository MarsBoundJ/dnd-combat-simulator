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
