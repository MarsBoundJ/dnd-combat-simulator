# Sim Modes

Two distinct use cases for the simulator. **Same engine, two
configurations** — they differ in resource-start, pacing/session setup, and
which metrics matter. (Companion: `content-roadmap-and-calibration.md`.)

## Mode 1 — Encounter Tuning (DM-facing)
*"Will my next 1–3 fights before the long rest TPK the party?"*

For a DM mid-campaign tuning a challenging-but-survivable boss (or the
last couple of fights of a session).

- **Partial-resource PCs.** Before a boss the party isn't at 100% — model
  current HP < max, spent spell slots, used limited-use features. The
  engine already supports this via `actor_spec` overrides
  (`hp_current` / `spell_slots` / `resources`).
- **Pacing.** `encounters_remaining_today` = the number of fights left
  (including this one) before the long rest → conserve on the earlier
  ones, **nova on the last (the boss)**. A single boss = `1`.
- **Output.** The rich outcome taxonomy — party-victory / TPK /
  fled-enemy-alive / stalemate-timeout — plus *closeness* (survivor HP,
  resources spent). The point is tuning to "hard, not a guaranteed wipe."

## Mode 2 — Build Rubric (designer-facing)
*"Is this UA subclass / feat / class stronger than that one?"*

The universal yardstick for character power.

- **Standardized idealized adventuring day.** A fixed XP budget (N monsters
  at CR X, per the adventuring-day XP math), a set gauntlet of encounters
  with short rests between, **full-resource start**.
- **Vary only the build.** Run the *identical* gauntlet across different
  PC builds / subclasses / classes / party configs.
- **Measure** offensive eHP, defensive eHP, and total eHP per character →
  rank effectiveness. This is how we'd score UA subclasses vs existing,
  class vs class, feat X vs feat Y within one build, and (later) magic
  items on a common scale.
- Built on the existing `run_session` / `SessionSpec` harness + an
  XP-budget encounter generator. This is the Trusight build-power product.

## Shared dependency: the pacing dial (needs a deliberate re-calibration)
Both modes ride `encounters_remaining_today`, which *should* yield
**conserve-early, nova-late**. The current calibrated formula
(`slot_cost_ehp`) does **not**, on two counts (a nova-pacing attempt was
reverted after it broke the framework's reference tests):
1. **Direction inverted.** `urgency = encounters_remaining / 6`, so *more*
   remaining = *cheaper* (spend early), and the formula's own reference
   value treats the **last** fight (`encounters_remaining = 0`) as
   **maximum** cost — the opposite of "nova on the last fight."
2. **Semantics mismatch.** The formula's "last encounter" reference is
   `encounters_remaining = 0`; `session.py` passes **1** for the last fight
   (fights-ahead-including-current). They disagree on what "last" is.

⇒ Fixing this is a **framework re-calibration** (direction + semantics +
reference values + `docs/foundations/ehp-action-framework.md`), not a
patch — and Mode 2's idealized-day spec is the target. (Note: its payoff
is also gated on casters having high-level options to nova *with*, so it's
not the current binding constraint.)
