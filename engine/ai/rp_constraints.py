"""RP Constraints — identity / personality / story-bound behavior that
doesn't fit the four gradient dials.

Per `docs/foundations/pillars-reconciliation.md` §6:

Three categories (§6.2):
  - Hard Filter — Removes actions from the candidate set entirely
    (e.g., "Strict Pacifist — never deals damage")
  - Forced Choice — When triggered, narrows candidates to a required
    subset (e.g., "Heal-First — must cast Healing Word on ally < 50% HP")
  - Weighted Preference — Modifies scoring within the eHP pipeline
    (e.g., "Resource Hoarder — penalizes spell-slot use")

Severity (§6.3):
  - Hard Filter: always 100% binary
  - Forced Choice: score priority weight (+severity × original eHP) on
    qualifying candidates
  - Weighted Preference: score multiplier ((1 + severity) × original)
    on matching candidates — supports negative severity for penalties

Priority resolution (§6.4):
  - Tier 1 (Hard Filters) — set intersection; empty → pass turn fallback
  - Tier 2 (Forced Choices) — when multiple trigger, only the highest-
    priority one's boost applies (ties broken by registration order)
  - Tier 3 (Weighted Preferences) — all apply additively in single pass

**v1 scope:**
  - 4 canonical constraints to demonstrate all 3 types end-to-end:
    pacifist_strict, heal_priority, signature_first, resource_hoarder
  - Hard-filter empty-set → pass turn fallback (no Dodge primitive)
  - Schema: behavior_profile.rp_constraints on actor template

**Deferred:**
  - 8 of 12 canonical constraints (recipes documented in §6.5)
  - User-authored custom predicates
  - Dodge primitive (Pass turn for v1)
  - Surrendered-creature non-targetable system (oath_protector)
  - Positioning-dependent constraints (frontline, library_protect)
  - Parley action (Pacifist intersection)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from engine.core.state import Actor, CombatState


# Type aliases for readability
PredicateOnCandidate = Callable[[dict, Actor, CombatState], bool]
PredicateOnState = Callable[[Actor, CombatState], bool]


# ============================================================================
# Constraint definition (library entry shape)
# ============================================================================

@dataclass(frozen=True)
class ConstraintDef:
    """Library entry for a canonical RP constraint."""
    id: str
    type: str                            # 'hard_filter' | 'forced_choice' | 'weighted_preference'
    default_severity: float
    default_priority: int                # higher = wins forced-choice ties
    # For Hard Filter: predicate returns True if candidate should be KEPT.
    # For Forced Choice + Weighted Preference: applies_to identifies the
    # qualifying / matching candidates that receive the score modification.
    applies_to: PredicateOnCandidate
    # Forced Choice only — trigger checks whether the constraint fires at all.
    # Weighted Preference is always-on; Hard Filter is always-on.
    trigger: PredicateOnState | None = None


# ============================================================================
# Active constraint (per-actor instance with resolved overrides)
# ============================================================================

@dataclass
class ActiveConstraint:
    """An RP constraint as applied to a specific actor (may override
    default severity / priority from the library)."""
    definition: ConstraintDef
    severity: float
    priority: int

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def type(self) -> str:
        return self.definition.type


# ============================================================================
# Predicate helpers (used by the canonical library)
# ============================================================================

def _action_has_primitive(action: dict, primitive_name: str) -> bool:
    """True if any pipeline step uses the given primitive."""
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == primitive_name:
            return True
    return False


def _candidate_deals_damage(candidate: dict, actor: Actor,
                              state: CombatState) -> bool:
    """A candidate "deals damage" if its action's pipeline has a `damage`
    primitive step. Multiattack candidates are checked via their sub-actions."""
    action = candidate.get("action") or {}
    if action.get("type") == "multiattack":
        # Look up sub-actions in actor template
        template_actions = (actor.template.get("actions") or [])
        by_id = {a.get("id"): a for a in template_actions}
        sub_ids = action.get("sub_actions") or []
        return any(_action_has_primitive(by_id.get(sid, {}), "damage")
                    for sid in sub_ids)
    return _action_has_primitive(action, "damage")


def _candidate_uses_spell_resource(candidate: dict, actor: Actor,
                                     state: CombatState) -> bool:
    """Proxy for "this action consumes a spell slot" — looks for spell-
    pipeline primitives that don't show up on weapon attacks.

    v1 proxy: forced_save or apply_condition primitives in the pipeline.
    Future: explicit spell_slot field on action."""
    action = candidate.get("action") or {}
    if action.get("type") == "multiattack":
        return False    # multiattacks don't burn slots
    pipeline = action.get("pipeline") or []
    spell_prims = {"forced_save", "apply_condition", "recurring_save"}
    return any(step.get("primitive") in spell_prims for step in pipeline)


def _candidate_is_signature(candidate: dict, actor: Actor,
                              state: CombatState) -> bool:
    """True if the action is flagged is_signature."""
    return bool((candidate.get("action") or {}).get("is_signature", False))


def _candidate_heals_wounded_ally(candidate: dict, actor: Actor,
                                    state: CombatState) -> bool:
    """True if the candidate is a heal targeting an ally below 50% HP."""
    if candidate.get("kind") != "heal" and \
            (candidate.get("action") or {}).get("type") != "heal":
        return False
    target = candidate.get("target")
    if target is None or target.hp_max <= 0:
        return False
    return (target.hp_current / target.hp_max) < 0.50


# Trigger predicates

def _trigger_round_one(actor: Actor, state: CombatState) -> bool:
    """signature_first triggers only in the opening round."""
    return state.round <= 1


def _trigger_any_wounded_ally(actor: Actor, state: CombatState) -> bool:
    """heal_priority triggers when any same-side ally is below 50% HP."""
    for a in state.encounter.actors:
        if a.side != actor.side or not a.is_alive():
            continue
        if a.hp_max > 0 and (a.hp_current / a.hp_max) < 0.50:
            return True
    return False


# ============================================================================
# Canonical constraint library — v1 ships 4 of 12 to prove the framework
# ============================================================================

CANONICAL_CONSTRAINTS: dict[str, ConstraintDef] = {
    "pacifist_strict": ConstraintDef(
        id="pacifist_strict",
        type="hard_filter",
        default_severity=1.0,        # hard filters are always binary
        default_priority=100,
        # For hard_filter: applies_to identifies candidates to REMOVE.
        # Returns True for "this candidate should be filtered out."
        applies_to=_candidate_deals_damage,
    ),
    "heal_priority": ConstraintDef(
        id="heal_priority",
        type="forced_choice",
        default_severity=0.70,       # +70% boost on qualifying candidates
        default_priority=80,
        applies_to=_candidate_heals_wounded_ally,
        trigger=_trigger_any_wounded_ally,
    ),
    "signature_first": ConstraintDef(
        id="signature_first",
        type="forced_choice",
        default_severity=0.50,       # +50% boost in round 1
        default_priority=50,
        applies_to=_candidate_is_signature,
        trigger=_trigger_round_one,
    ),
    "resource_hoarder": ConstraintDef(
        id="resource_hoarder",
        type="weighted_preference",
        default_severity=-0.30,      # -30% penalty on spell-using candidates
        default_priority=10,
        applies_to=_candidate_uses_spell_resource,
    ),
}


# ============================================================================
# Reading constraints from actor template
# ============================================================================

def get_active_constraints(actor: Actor) -> list[ActiveConstraint]:
    """Resolve all rp_constraints declared on the actor's template.

    Schema shape on actor.template.behavior_profile.rp_constraints:
      [
        {id: 'pacifist_strict'},
        {id: 'heal_priority', severity: 0.6, priority: 90},
      ]

    Unknown constraint IDs are silently skipped (logged in production
    real engine; skeleton just drops them).
    """
    bp = (actor.template.get("behavior_profile") or {})
    raw_list = bp.get("rp_constraints") or []
    active: list[ActiveConstraint] = []
    for raw in raw_list:
        cid = raw.get("id") if isinstance(raw, dict) else raw
        if not cid or cid not in CANONICAL_CONSTRAINTS:
            continue
        definition = CANONICAL_CONSTRAINTS[cid]
        severity = raw.get("severity") if isinstance(raw, dict) else None
        if severity is None:
            severity = definition.default_severity
        priority = raw.get("priority") if isinstance(raw, dict) else None
        if priority is None:
            priority = definition.default_priority
        # Hard filter severity is locked at 1.0 per §6.3
        if definition.type == "hard_filter":
            severity = 1.0
        active.append(ActiveConstraint(definition=definition,
                                          severity=severity,
                                          priority=priority))
    return active


# ============================================================================
# Tier 1 — Hard Filters (§6.4)
# ============================================================================

def apply_hard_filters(candidates: list[dict], actor: Actor,
                         state: CombatState) -> list[dict]:
    """Remove candidates that any hard_filter constraint marks for removal.

    Per §6.4 "set intersection of all active filters" — a candidate must
    survive ALL hard filters to remain. An empty result is legal; the
    caller (pipeline) handles fallback.
    """
    active = [c for c in get_active_constraints(actor)
               if c.type == "hard_filter"]
    if not active:
        return candidates

    survivors: list[dict] = []
    for cand in candidates:
        if all(not c.definition.applies_to(cand, actor, state)
                for c in active):
            survivors.append(cand)
    return survivors


# ============================================================================
# Tier 2 — Forced Choices (§6.4 priority resolution, §6.3 score boost)
# ============================================================================

def apply_forced_choice_boosts(scored: list[tuple[float, dict]],
                                  actor: Actor,
                                  state: CombatState) -> list[tuple[float, dict]]:
    """Tier 2 score modification.

    Per §6.4: when multiple forced_choice constraints trigger, only the
    highest-priority one's boost applies. Ties broken by registration
    order (the order they appear on the actor's rp_constraints list).

    Per §6.3: severity is a score boost — qualifying candidates get
    `+ severity * |original_score|` added (or a baseline floor if the
    original was 0; otherwise the constraint would be inert on zero-eHP
    candidates).
    """
    active_forced = [c for c in get_active_constraints(actor)
                      if c.type == "forced_choice"]
    if not active_forced:
        return scored

    # Filter to triggered constraints
    triggered = [c for c in active_forced
                  if c.definition.trigger is None
                  or c.definition.trigger(actor, state)]
    if not triggered:
        return scored

    # Highest priority wins; ties broken by registration order (which is
    # the order they appear in the actor's rp_constraints — preserved by
    # get_active_constraints iteration). sorted() is stable in Python.
    triggered.sort(key=lambda c: -c.priority)
    winner = triggered[0]

    return [_apply_score_boost(s, c, winner) for s, c in scored]


def _apply_score_boost(score: float, candidate: dict,
                         constraint: ActiveConstraint) -> tuple[float, dict]:
    """Apply a Forced Choice boost to a single (score, candidate) pair."""
    if not constraint.definition.applies_to(candidate, None, None):
        return (score, candidate)
    # If original score is positive: + severity × original. If zero/negative,
    # use the severity as an absolute floor so the constraint isn't inert.
    if score > 0:
        boost = constraint.severity * score
        return (score + boost, candidate)
    # Floor boost — give qualifying candidates SOMETHING so the dial
    # actually does work even on a previously-uninteresting action.
    floor_value = constraint.severity * 10.0  # arbitrary but stable scale
    return (floor_value, candidate)


# ============================================================================
# Tier 3 — Weighted Preferences (§6.4 cumulative additive)
# ============================================================================

def apply_weighted_preferences(scored: list[tuple[float, dict]],
                                 actor: Actor,
                                 state: CombatState) -> list[tuple[float, dict]]:
    """Tier 3 score modification — cumulative across all matching constraints.

    Per §6.4: "Cumulative additive in single scoring pass." So if two
    weighted_preference constraints both match a candidate, both
    severity-deltas are summed.

    Per §6.3: severity is a multiplier — (1 + severity) × original.
    Supports negative severity for penalties (e.g., resource_hoarder = -0.3
    → matching candidates score 70% of original).
    """
    active_weighted = [c for c in get_active_constraints(actor)
                        if c.type == "weighted_preference"]
    if not active_weighted:
        return scored

    out: list[tuple[float, dict]] = []
    for score, cand in scored:
        # Sum severities from all matching constraints
        delta = sum(c.severity for c in active_weighted
                     if c.definition.applies_to(cand, actor, state))
        if delta == 0:
            out.append((score, cand))
            continue
        if score > 0:
            out.append((score * (1.0 + delta), cand))
        else:
            # Negative or zero scores — apply as flat additive so penalties
            # / boosts don't silently no-op on zero-eHP candidates.
            out.append((score + delta * 10.0, cand))
    return out


# ============================================================================
# Convenience: chained score modification (used by decision_layer)
# ============================================================================

def apply_score_modifications(scored: list[tuple[float, dict]],
                                actor: Actor,
                                state: CombatState) -> list[tuple[float, dict]]:
    """Chain Tier 2 then Tier 3 score modifications per §6.4 ordering."""
    scored = apply_forced_choice_boosts(scored, actor, state)
    scored = apply_weighted_preferences(scored, actor, state)
    return scored
