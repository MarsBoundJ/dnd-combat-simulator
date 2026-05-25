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

    Pulls from actor.template's actions; pairs each with reachable
    targets per the action's target shape:
      - weapon_attack / hard_control  → one candidate per living enemy
      - multiattack                    → one candidate (own target loop)
      - heal / defensive_buff          → one candidate per living ally
                                          (allies = same side, includes self)

    Defensive candidates (heal/buff/control) ride on the same scoring
    path as offensive ones — `score_candidate` dispatches by action type
    to the appropriate eHP formula.
    """
    candidates: list[dict] = []
    template = actor.template
    actions = template.get("actions", [])

    enemies = [a for a in state.encounter.actors
               if a.side != actor.side and a.is_alive()]
    allies = [a for a in state.encounter.actors
              if a.side == actor.side and a.is_alive()]

    for action in actions:
        action_type = action.get("type")
        if action_type == "weapon_attack":
            for enemy in enemies:
                candidates.append({
                    "kind": "weapon_attack",
                    "action": action,
                    "target": enemy,
                    "actor": actor,
                })
        elif action_type == "multiattack":
            # Multiattack picks its own targets per sub-attack inside
            # _execute_multiattack. Generate one candidate, scored as a
            # single "do my multiattack" choice. Target is informational.
            primary_target = enemies[0] if enemies else None
            candidates.append({
                "kind": "multiattack",
                "action": action,
                "target": primary_target,
                "actor": actor,
            })
        elif action_type in ("heal", "defensive_buff"):
            # Per-ally enumeration. Self counts as an ally (you can heal /
            # buff yourself); decision_layer's scoring decides whether to.
            for ally in allies:
                candidates.append({
                    "kind": action_type,
                    "action": action,
                    "target": ally,
                    "actor": actor,
                })
        elif action_type == "hard_control":
            for enemy in enemies:
                candidates.append({
                    "kind": "hard_control",
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
    """Step 5: Utility AI single-scoring-stage.

    Delegates to engine.ai.decision_layer.score_candidates_v1 which
    consults the actor's targeting and ability-selection dial presets
    (resolved from behavior_profile/archetype on the template) and
    scores candidates that match the actor's preferences higher.

    Full eHP scoring + RP weighted preferences + behavioral coefficients
    per pillars-reconciliation.md §7 step 5 are deferred to follow-on PRs.
    """
    # Lazy import to avoid potential circular dependency at module load
    from engine.ai.decision_layer import score_candidates_v1
    return score_candidates_v1(candidates, actor, state)


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
    """Step 8: dispatch chosen action through its primitive pipeline.

    Special-cased: action.type == 'multiattack' loops the sub-attack
    pipelines N times. Each sub-attack independently picks its target.
    """
    if not chosen:
        return
    actor = chosen["actor"]
    action = chosen["action"]

    if action.get("type") == "multiattack":
        _execute_multiattack(actor, action, state, event_bus, primitives)
    else:
        _execute_single(chosen, state, event_bus, primitives)

    # Mark main action used
    actor.actions_used_this_turn["action"] = True


def _execute_single(chosen: dict, state: CombatState, event_bus, primitives) -> None:
    """Execute one action's primitive pipeline."""
    actor = chosen["actor"]
    target = chosen.get("target")
    action = chosen["action"]

    state.current_attack = {
        "actor": actor,
        "target": target,
        "action": action,
        "state": None,
        "had_advantage": False,
        "had_disadvantage": False,
    }

    for step in action.get("pipeline", []):
        primitive_name = step["primitive"]
        params = step.get("params", {})
        when = step.get("when")
        if when:
            cond = when.get("condition", "")
            if cond and not _evaluate_simple_condition(cond, state):
                continue
        primitives.invoke(primitive_name, params, state, event_bus)


def _execute_multiattack(actor, action: dict, state: CombatState,
                         event_bus, primitives) -> None:
    """Loop the attack pipeline N times for a multiattack action.

    action shape:
      type: multiattack
      count: 2
      sub_actions: [a_scimitar, a_shortbow]   # ids of attacks in actor.template.actions
      target_per_attack: independent | same    # skeleton: same target (closest)
    """
    count = action.get("count", 1)
    sub_action_ids = action.get("sub_actions", [])
    if not sub_action_ids:
        return

    # Find the sub-actions in the actor's template
    template_actions = actor.template.get("actions", [])
    sub_actions_by_id = {a.get("id"): a for a in template_actions}

    # Pick target: closest living enemy (skeleton)
    enemies = [a for a in state.encounter.actors
               if a.side != actor.side and a.is_alive()]
    if not enemies:
        return
    target = enemies[0]  # skeleton: just the first

    for i in range(count):
        # If target died, pick next
        if not target.is_alive():
            remaining = [a for a in state.encounter.actors
                         if a.side != actor.side and a.is_alive()]
            if not remaining:
                return
            target = remaining[0]
        sub_action_id = sub_action_ids[i % len(sub_action_ids)]
        sub_action = sub_actions_by_id.get(sub_action_id)
        if sub_action is None:
            continue
        sub_chosen = {"actor": actor, "target": target, "action": sub_action,
                       "kind": "weapon_attack"}
        _execute_single(sub_chosen, state, event_bus, primitives)


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
