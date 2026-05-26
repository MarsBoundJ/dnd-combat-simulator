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


def check_retreat_trigger(actor: Actor, state: CombatState,
                            rng=None) -> dict | None:
    """Step 1: retreat trigger check — DMG p48 algorithm (dmg_ammann mode).

    Delegates to `engine.ai.retreat.check_retreat`. A non-None return
    means the actor flees this turn and the runner short-circuits the
    rest of the pipeline.

    The `rng` parameter is the runner's seeded rng (for reproducibility);
    omitted in tests it falls back to a fresh random.
    """
    from engine.ai.retreat import check_retreat
    return check_retreat(actor, state, rng)


def generate_candidates(actor: Actor, state: CombatState,
                         slot: str = "action") -> list[dict]:
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

    Args:
      slot: which turn slot is being filled. Default 'action' enumerates
        main-slot candidates (actions tagged `slot: 'action'` or untagged).
        Pass 'bonus_action' to enumerate bonus-slot candidates. The runner
        calls this twice per turn: once for the main slot, once for bonus.
    """
    from engine.core.geometry import is_within_ft

    candidates: list[dict] = []
    template = actor.template
    actions = [a for a in (template.get("actions") or [])
                if a.get("slot", "action") == slot]

    enemies = [a for a in state.encounter.actors
               if a.side != actor.side and a.is_alive()]
    allies = [a for a in state.encounter.actors
              if a.side == actor.side and a.is_alive()]

    for action in actions:
        action_type = action.get("type")
        if action_type == "weapon_attack":
            reach = _action_reach_ft(action)
            for enemy in enemies:
                if not is_within_ft(actor, enemy, reach):
                    continue
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
            # Reach uses the MAX reach across the sub-actions — multiattack
            # is reachable if at least one sub-attack can land on the
            # primary target (multiattack execution re-picks per sub-attack
            # for now; positioning-aware sub-targeting is a future PR).
            reach = _multiattack_max_reach(action, actor.template)
            in_range = [e for e in enemies if is_within_ft(actor, e, reach)]
            if not in_range:
                continue
            primary_target = in_range[0]
            candidates.append({
                "kind": "multiattack",
                "action": action,
                "target": primary_target,
                "actor": actor,
            })
        elif action_type in ("heal", "defensive_buff"):
            # Per-ally enumeration. Self counts as an ally (you can heal /
            # buff yourself); decision_layer's scoring decides whether to.
            # v1: generous range on ally-targeted abilities (defer touch-
            # range gating).
            for ally in allies:
                candidates.append({
                    "kind": action_type,
                    "action": action,
                    "target": ally,
                    "actor": actor,
                })
        elif action_type == "hard_control":
            # Spells have a `range_ft` in the action; default to 60 ft for
            # v1 since most save-or-lose spells in 5e are 30-90 ft range.
            reach = int(action.get("range_ft", 60))
            for enemy in enemies:
                if not is_within_ft(actor, enemy, reach):
                    continue
                candidates.append({
                    "kind": "hard_control",
                    "action": action,
                    "target": enemy,
                    "actor": actor,
                })
    return candidates


def _action_reach_ft(action: dict) -> int:
    """Resolve the reach/range for a weapon_attack action.

    Inspects the action's pipeline for the attack_roll step. Uses
    `range_ft` if present (ranged attacks), else `reach_ft` (melee,
    default 5).
    """
    for step in (action.get("pipeline") or []):
        if step.get("primitive") != "attack_roll":
            continue
        params = step.get("params") or {}
        if "range_ft" in params:
            return int(params["range_ft"])
        if "reach_ft" in params:
            return int(params["reach_ft"])
    # Top-level shorthand (rare): action.range_ft / action.reach_ft
    if "range_ft" in action:
        return int(action["range_ft"])
    if "reach_ft" in action:
        return int(action["reach_ft"])
    return 5  # melee default


def _multiattack_max_reach(action: dict, template: dict) -> int:
    """Max reach across a multiattack's sub-actions (for candidate gating).

    A multiattack with one melee + one ranged sub-action is reachable at
    the longer range; execution re-checks per sub-attack.
    """
    sub_ids = action.get("sub_actions") or []
    by_id = {a.get("id"): a for a in (template.get("actions") or [])}
    reaches = [_action_reach_ft(by_id[sid]) for sid in sub_ids
                if sid in by_id]
    return max(reaches) if reaches else 5


def apply_hard_filters(candidates: list[dict], actor: Actor,
                       state: CombatState) -> list[dict]:
    """Step 3: RP Hard Filters remove candidates from the set.

    Delegates to `engine.ai.rp_constraints.apply_hard_filters`. Per §6.4
    Tier 1: set intersection of all active hard_filter constraints;
    candidate must survive ALL to remain. Empty result is legal — the
    runner falls back to a pass-turn event.
    """
    from engine.ai.rp_constraints import apply_hard_filters as _apply
    return _apply(candidates, actor, state)


def apply_forced_choices(candidates: list[dict], actor: Actor,
                         state: CombatState) -> list[dict]:
    """Step 4: RP Forced Choices.

    Pass-through: per §6.3 Forced Choice severity is a SCORE WEIGHT, not
    a narrowing filter — the actual work happens at scoring time
    (`apply_forced_choice_boosts` inside score_candidates_v1). This stub
    preserves pipeline shape and is a natural seam if filter-style
    semantics are ever added.
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


def apply_action_economy(actor: Actor, chosen: dict, state: CombatState,
                           rng=None) -> dict | None:
    """Step 7: per-slot stochastic on optimal-vs-default.

    For the Main slot, this rolls vs `main_optimality` per the actor's
    action_economy preset; on miss, the chosen candidate is replaced by
    the actor's default attack (first weapon_attack) keeping the same target.

    Bonus and Reaction slots are handled by the runner (it loops a separate
    bonus-action turn after the main, gated by per-slot percentages from
    `action_economy.should_use_bonus_action`).

    The `rng` parameter is required when `chosen` is non-None. If omitted,
    a module-default random is used (test convenience; production passes
    the runner's seeded rng for reproducibility).
    """
    if chosen is None:
        return None
    # Lazy import: ai package depends on core.state (already imported here);
    # this keeps action_economy out of the core package's import graph.
    from engine.ai.action_economy import resolve_main_slot
    if rng is None:
        import random as _r
        rng = _r.Random()
    return resolve_main_slot(actor, chosen, state, rng)


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

    # Mark the right slot used — read the action's `slot` field (default 'action').
    # Lets bonus_action / reaction tracking work without separate plumbing.
    slot = action.get("slot", "action")
    if slot in actor.actions_used_this_turn:
        actor.actions_used_this_turn[slot] = True
    else:
        actor.actions_used_this_turn[slot] = True   # safe to add


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
