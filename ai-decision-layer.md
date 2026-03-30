# AI Decision Layer

**Status:** 🔴 NOT YET DRAFTED

---

## Purpose

This document records the decision between algorithm approaches for monster AI and encodes the chosen implementation policy.

## The Open Decision

| Approach | Description | Pros | Cons |
|---|---|---|---|
| **MCTS** (Monte Carlo Tree Search) | Search algorithm over discrete decision trees | Natural fit for turn-based combat; handles lookahead well | Computationally expensive per turn; requires tuned rollout policy |
| **Rules-Based** | Explicit priority-ordered decision rules from Ammann framework | Fast; transparent; directly encodes Ammann's behavioral logic | Brittle to novel situations; limited lookahead |
| **Hybrid** | Rules-based for behavioral constraints, MCTS within those constraints | Best of both; Ammann gates the search space | More complex implementation |

## Decision Criteria

Before choosing, answer:
1. Is the simulator a **play-out tool** (needs fast decisions, many simulations) or a **single-encounter tool** (can afford computation per decision)?
2. Does "authentic behavior" or "optimal play" take priority? (see `pillars-reconciliation.md`)
3. What is the acceptable latency per monster decision in Foundry's UI?

---

## `[DECISION RECORDED HERE WHEN MADE]`

> **Chosen approach:**  
> **Rationale:**  
> **Date decided:**  
> **Session reference:** (link to SESSIONS.md entry)
