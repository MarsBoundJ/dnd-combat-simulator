# Stocktake — June 2 2026

A deliberate pause after a large engine + content push, to assess where
the simulator stands before building more. (Companion: `sims/FINDINGS.md`,
the first end-to-end fight that grounds this.)

## Built this arc
- **8 monster-engine systems**, each a merged PR with tests + green full
  suite: Recharge, Legendary Resistance, Legendary Actions, Spellcasting
  (+ v2 hardening), Shape-Shift, Regeneration, Swallow (+ v2 regurgitate),
  Aura traits, Summoning. Plus the **Druid** (first form-system consumer).
- **5 parallel content batches** (browser lane): M5 critters → M9 caster
  NPCs. ~146 monsters; ~2174 → 2323 tests; zero regressions over ~140 commits.

## What's working
- **Parallel lanes** (engine vs content, queue doc as contract) — a real
  force-multiplier; content batches adversarially found engine bugs (M8 →
  two Spellcasting expander gaps).
- **Composition** — new behaviors fall out of existing pieces with no glue
  (Legendary Resistance auto-applies to Swallow regurgitate; aura-traits
  ride persistent_aura; Frightful Presence = `casts: f_fear`).
- **Discipline under velocity** — RAW from the PDF (caught CR-6 Mage),
  pause-and-ask merges, small green PRs.

## The strategic gap: buildable ≠ accurate
We optimized **coverage**, not **calibration**. The sim can *represent* an
adult dragon; until today it had never been validated to produce sane
eHP/DPR. The first end-to-end fight (see `sims/`) confirmed the worry:
**mechanics correct, decision layer naive** — a 2-round flawless TPK where
3 of 4 PCs dealt zero damage, caused by PC flee-morale firing on PCs, idle
casters, and the party clustered in one breath cone.

## Highest-leverage next work (revised by the first sim)
**The AI/decision layer, not more content.** In priority order:
1. PC retreat suppression (PCs shouldn't use monster flee-morale).
2. Caster offensive selection + damage-type/immunity awareness (a fire
   dragon shrugs off Fireball).
3. AoE-aware positioning (don't stack the party in one cone).

Secondary: re-triage the queue (3 "already done in 2024 RAW" findings show
it's partly stale); decide which deferral-debt asterisks actually move
eHP/DPR; instrument per-sim metric buckets (DPR / to-hit% / control-eHP /
healing) — the Trusight data asset — for which `sims/` is the prototype.

## Direction (Phil)
- **Foundry VTT visualization** as the trust mechanism — users *see*
  combat play out; wrong behavior is obvious. (Runner observation-mode is
  already designed for an external driver.)
- **Per-combat data buckets** (monster/PC choices, optimization level,
  playstyle, outcome metrics) are a DDB-style revealed-preference firehose
  Trusight would own — the real long-term payoff.
