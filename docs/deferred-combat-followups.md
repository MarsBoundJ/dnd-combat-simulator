# Deferred Combat Follow-ups → PC Decision Layer

**Purpose:** Combat features whose *mechanics* are wired (or deliberately
stubbed) but whose remaining work is gated on the **PC decision layer**
(AI action selection / `engine/ai/ehp_scoring.py`) or on new hot-path
infrastructure that wasn't worth building for marginal value. Distinct
from `deferred-noncombat-features.md` (Stage-4 / AI-DM items): everything
here IS combat-relevant — it's the *when-to-use* decision or the
risk/reward of new infra that's deferred, not the combat relevance.

Revisit this doc when working on the PC decision layer. Each entry says
exactly what's built, what's missing, and where the hooks are.

---

## 1. Overchannel (Evoker L14) — mechanics WIRED, AI selection deferred

**Session:** 2026-06-11 (Phase 3C, commit `860ec4c`).

**What's built (correct + directly testable, `tests/test_overchannel.py`):**
- `maximize_dice` flag on damage-step params, honored by the `damage`
  primitive via `_roll_dice_maximized` (`engine/primitives.py`) — every
  die deals max value, crit dice included.
- `engine/core/overchannel.py` — `apply_overchannel(action, caster,
  state, rng)` deep-copies the action (metamagic convention), stamps
  `maximize_dice` on every damage step (reuses metamagic's
  `_iter_damage_params` walker, so `forced_save` on_fail/on_success
  nesting is covered), increments the per-rest counter, and on a reuse
  applies the escalating necrotic self-damage straight to HP (RAW:
  ignores Resistance/Immunity). Eligibility gate: Wizard spell level
  1–5 with ≥1 damage step (`is_eligible`).
- `overchannel_uses_this_rest` counter: stamped 0 by
  `derive_pc_resources` (pc_schema), reset to 0 in
  `rest.apply_long_rest` (Wizard block).

**What's deferred — the decision layer (the actual follow-up):**
- *Nothing calls `apply_overchannel` in live sims.* Exactly like
  Metamagic (whose `apply_metamagic` is also correct-but-unselected),
  the WHICH-spell / WHEN decision is an `engine/ai` concern.
- The free first use is strictly beneficial → a v1 heuristic could
  auto-fire it on the Evoker's highest-damage eligible cast of the day.
  But "highest-damage of the day" needs encounter-pacing context
  (`feature_pacing` / `optimization_dial` are the likely substrate).
- Reuses are a real trade-off (escalating `(N×level)d12` self-damage vs.
  maximized output) → needs an expected-value comparison in scoring.
  **This touches `ehp_scoring.py` — Opus-owned per the Phase 3 plan §6.**
- Metamagic option selection is the same shape of problem; whatever
  selection framework lands should serve both. Suggested order: build
  the cast-decoration decision hook once (pre-cast transform chooser),
  then register Empowered/Quickened/Overchannel as candidates.

**Known v1 limitation (documented in `f_overchannel.yaml`):** per-slot-
level upcast extra dice (`_resolve_upcast_extra_dice`) are NOT
maximized — only base + crit dice. Base dice dominate and the typical
Overchannel target is a fixed-level damage spell. Fix would thread the
flag into the upcast roller if it ever matters.

---

## 2. Peerless Skill (College of Lore L14) — deliberate STUB

**Session:** 2026-06-11 (Phase 3C, commit `860ec4c`). Full rationale +
implementation path also lives in `f_peerless_skill.yaml`.

**Why stubbed (the call):** RAW covers "an ability check OR an attack
roll" — in a combat sim the ability-check half is out of scope, leaving
only the attack-roll sliver, which is marginal for a Lore Bard (rarely
attacks). Against that thin value, it needs genuinely-new infrastructure:
an **outcome-dependent refund** — the Bardic Inspiration use is restored
only if the boosted roll STILL misses. That differs in kind from every
existing refund (Rage refund is pre-execution at the candidate gate;
this is post-resolution) and would add a branch to the `_attack_roll`
hot path. Poor risk/reward → documented stub.

**Implementation path (when prioritized — e.g., if the Bard AI starts
weighing its own attack rolls, or ability checks enter the sim):**
1. `engine/core/bardic_inspiration.py` — a `maybe_add_to_attack` variant
   that spends `bardic_inspiration_uses_remaining` directly (Peerless
   uses the Bard's OWN pool, not a held inspiration-die marker) and
   records a `peerless_skill_die_spent` flag on `state.current_attack`.
2. `engine/primitives.py _attack_roll` — call it on the Bard's own
   would-be miss (the existing post-reaction self-add hook, at the
   `maybe_add_to_attack` call site), then at attack-state finalization
   (where state becomes `"miss"`) refund the use if the boosted roll
   still missed.
3. `f_peerless_skill.yaml` — add the reaction action_template (trigger
   `attack_roll_pending`, `feature_use:
   bardic_inspiration_uses_remaining`) once the refund path exists.

---

## 3. Minor approximations logged in the same batch (no action needed,
recorded for honesty)

- **Elemental Affinity (Draconic Sorcery L6):** the RAW "one damage
  roll" on multi-target AoE is modeled as once-per-cast — the +CHA lands
  on the first matching-type damage roll of the cast (dedup flag on
  `state.current_attack`). Defensible RAW reading; see
  `engine/core/draconic_sorcery.py`.
