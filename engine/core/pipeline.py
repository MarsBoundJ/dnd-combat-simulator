"""Decision pipeline — the 8-step pattern from pillars-reconciliation.md §7.

The 8 steps:
  0. Resolve effective profile (static + dynamic layers)
  1. Retreat trigger check
  2. Generate candidates
  3. Apply RP Hard Filters
  4. Apply RP Forced Choices
  5. Score each candidate (single coherent scoring pass — Utility AI shape)
  6. Select max-scoring candidate
  7. Apply Action Economy per slot
  8. Execute

For the SKELETON: the AI decision layer is a trivial implementation
("attack nearest enemy with first available attack"). The full pipeline
shape is preserved; primitives + behavior-profile-driven decisions slot
in incrementally.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


def resolve_effective_profile(actor: Actor, state: CombatState) -> dict:
    """Step 0: collapse static + dynamic profile layers into effective profile.

    Static: archetype → faction → instance.
    Dynamic: form transition → runtime overrides.

    SKELETON: returns the actor's template's behavior_profile directly,
    plus runtime_overrides from applied conditions. Full inheritance
    chain is post-MVP.
    """
    base = dict(actor.template.get("behavior_profile") or {})
    # TODO: walk archetype → faction → instance hierarchy
    # TODO: apply form_transition if active
    # TODO: apply runtime_overrides from conditions
    return base


def check_retreat_trigger(actor: Actor, state: CombatState) -> dict | None:
    """Step 1: retreat trigger check.

    SKELETON: returns None (no retreat). Real implementation reads the
    retreat dial preset + 3-mode selection + DMG p48 algorithm.
    """
    return None


def generate_candidates(actor: Actor, state: CombatState) -> list[dict]:
    """Step 2: enumerate all legal (action × target) candidate tuples.

    Pulls from actor.template's actions, bonus_actions, and reactions;
    pairs each with reachable targets.
    """
    candidates: list[dict] = []
    template = actor.template
    actions = template.get("actions", [])

    enemies = [a for a in state.encounter.actors
               if a.side != actor.side and a.is_alive()]

    for action in actions:
        if action.get("type") == "weapon_attack":
            for enemy in enemies:
                candidates.append({
                    "kind": "weapon_attack",
                    "action": action,
                    "target": enemy,
                    "actor": actor,
                })
    return candidates


def apply_hard_filters(candidates: list[dict], actor: Actor,
                       state: CombatState) -> list[dict]:
    """Step 3: RP Hard Filters remove candidates from the set.

    SKELETON: no filters (no RP constraints in skeleton fixtures).
    """
    return candidates


def apply_forced_choices(candidates: list[dict], actor: Actor,
                         state: CombatState) -> list[dict]:
    """Step 4: RP Forced Choices narrow to required subset when triggered.

    SKELETON: no forced choices in skeleton fixtures.
    """
    return candidates


def score_candidates(candidates: list[dict], actor: Actor,
                     state: CombatState) -> list[tuple[float, dict]]:
    """Step 5: Utility AI single-scoring-stage. All considerations baked in.

    SKELETON: trivially score by proximity to target (closer = higher).
    Real implementation invokes eHP scoring + RP weighted preferences +
    behavioral coefficients per pillars-reconciliation.md §7.
    """
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        # Skeleton: prefer the closest enemy
        # (Real engine: eHP_value × weighted_prefs + forced_weights + behavior_coeffs)
        score = 1.0  # all weapon attacks scored equally for now
        scored.append((score, c))
    return scored


def select_max(scored: list[tuple[float, dict]]) -> dict | None:
    """Step 6: pick max-scoring candidate. Ties broken by first-listed."""
    if not scored:
        return None
    return max(scored, key=lambda x: x[0])[1]


def apply_action_economy(actor: Actor, chosen: dict, state: CombatState) -> dict:
    """Step 7: per-slot stochastic on optimal-vs-default.

    SKELETON: always uses the chosen action (optimal preset). Real
    implementation reads action_economy preset's per-slot percentages
    (signature_bonus, tactical_bonus, OA_reaction, sophisticated_reaction)
    and rolls per slot.
    """
    return chosen


def execute(chosen: dict, state: CombatState, event_bus, primitives) -> None:
    """Step 8: dispatch chosen action through its primitive pipeline."""
    if not chosen:
        return
    actor = chosen["actor"]
    target = chosen.get("target")
    action = chosen["action"]

    # Set up scratch space for the attack pipeline
    state.current_attack = {
        "actor": actor,
        "target": target,
        "action": action,
        "state": None,        # hit/miss/crit set by attack_roll
        "had_advantage": False,
        "had_disadvantage": False,
    }

    for step in action.get("pipeline", []):
        primitive_name = step["primitive"]
        params = step.get("params", {})
        when = step.get("when")
        # Skeleton: check 'when' condition rudimentarily
        if when:
            cond = when.get("condition", "")
            if cond and not _evaluate_simple_condition(cond, state):
                continue
        primitives.invoke(primitive_name, params, state, event_bus)

    # Mark action used
    actor.actions_used_this_turn["action"] = True


def _evaluate_simple_condition(cond: str, state: CombatState) -> bool:
    """Trivial condition evaluator for the skeleton.

    Handles a tiny vocabulary: 'combat.attack_state == hit', etc.
    Real engine has a proper expression evaluator.
    """
    if "combat.attack_state == hit" in cond:
        return state.current_attack.get("state") == "hit"
    if "combat.attack_had_advantage" in cond:
        return state.current_attack.get("had_advantage", False)
    return True
