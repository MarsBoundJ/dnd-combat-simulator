# Pillars Reconciliation Policy

**Status:** 🔴 NOT YET DRAFTED — blocked on `ammann-behavior-framework.md`

---

## Purpose

This document establishes binding policy for resolving conflicts between the two foundational pillars of the combat simulator engine:

- **Pillar 1 — The Finished Book** (mathematical framework)
- **Pillar 2 — The Monsters Know What They're Doing** (behavioral framework)

No algorithms may be written until this document is complete.

---

## The Core Tension

The Finished Book optimizes for mathematical accuracy — it will always identify the action that maximizes expected damage output or minimizes damage taken. Ammann's framework optimizes for behavioral authenticity — it constrains monsters to act according to their nature, intelligence, and instincts, which is often *not* the mathematically optimal move.

A goblin, mathematically, should coup de grace an unconscious Paladin. Ammann's framework says goblins are cowardly opportunists who flee when their side is losing, not cold calculators. The engine needs a policy for which wins.

---

## `[DRAFT BEGINS HERE]`

> This document has not yet been drafted. The next session working on reconciliation should:
> 1. Enumerate the known conflict classes (targeting, retreat, ability selection, action economy)
> 2. For each class, establish a named policy: Math Wins / Behavior Wins / Weighted Blend
> 3. Define how the weighting is expressed in engine terms (probability, override flag, etc.)
> 4. Document any simulator "mode" switches (e.g., "optimal AI" vs "authentic AI")
