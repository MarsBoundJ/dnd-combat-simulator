# Ammann Behavior Framework

**Source:** Keith Ammann — *The Monsters Know What They're Doing* (blog and books)  
**Blog:** https://www.themonstersknow.com  
**Status:** 🔴 NOT YET DRAFTED

---

## Purpose

This document encodes the behavioral decision-making logic for monster AI from Keith Ammann's framework. Where `finished-book-summary.md` answers "how much damage does this action deal?", this document answers "which action would this monster actually choose, and why?"

## Scope

- Monster targeting logic (which PC to attack)
- Ability usage priority (when to use special abilities vs basic attacks)
- Retreat and morale decisions
- Pack tactics and group coordination
- Self-preservation vs aggression thresholds by monster type
- Terrain and positioning awareness

## Relationship to Finished Book Pillar

This document governs *decisions*. The Finished Book governs *math*. When they conflict, see `pillars-reconciliation.md`.

---

## `[DRAFT BEGINS HERE]`

> This document has not yet been drafted. The next session working on the Ammann pillar should:
> 1. Review Ammann's blog categories at themonstersknow.com
> 2. Identify the generalizable decision framework (not per-monster entries)
> 3. Encode the framework as policy rules the engine can implement
> 4. Map each rule to its mathematical weight using the Finished Book's eHP/eDPR machinery
