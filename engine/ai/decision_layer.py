"""Decision layer orchestration — the public face of the AI module.

Two complementary public functions:

  - `score_candidates_v1(candidates, actor, state)` — the score_candidates
    socket from pipeline.py §7 step 5. Currently returns scores reflecting
    the actor's targeting + ability-selection preferences. eHP-based
    scoring with behavioral coefficients is deferred to a follow-on PR.

  - `select_action_v1(actor, state)` — alternative API: instead of scoring
    a pre-generated candidate list, this picks the (action, target) tuple
    directly via the dial-driven AI. Useful when generate_candidates is
    too restrictive (e.g., it currently only enumerates weapon_attacks;
    select_action_v1 considers multiattack too).

Both share the same underlying logic: resolve the actor's dial presets,
delegate to targeting + ability_selection, return the result.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState
from engine.ai import targeting, ability_selection, behavior_profile


def score_candidates_v1(candidates: list[dict], actor: Actor,
                         state: CombatState) -> list[tuple[float, dict]]:
    """Score each candidate (action × target) tuple.

    A candidate matching the actor's preferred (target, action) per their
    dials gets a high score; others lower. Selection then picks max.

    v1 scoring scheme:
      - +10 if target matches the targeting-dial preset's pick
      - +5 if action matches the ability-selection-dial preset's pick
      - +0 baseline for any legal candidate
      (Future: full eHP scoring + behavioral coefficients per
       pillars-reconciliation.md §7 step 5.)
    """
    if not candidates:
        return []

    targeting_preset = behavior_profile.resolve_targeting_preset(actor)
    ability_preset = behavior_profile.resolve_ability_selection_preset(actor)

    # Get the actor's preferred (target, action) per dials
    enemies = [c["target"] for c in candidates
                if c.get("target") and c["target"].is_alive()]
    enemies = list({e.id: e for e in enemies}.values())  # dedupe by id
    preferred_target = targeting.pick_target(actor, enemies, state, targeting_preset)
    preferred_action = ability_selection.pick_action(
        actor, preferred_target, state, ability_preset
    )

    scored: list[tuple[float, dict]] = []
    for c in candidates:
        score = 0.0
        if preferred_target and c.get("target") and \
                c["target"].id == preferred_target.id:
            score += 10
        if preferred_action and c.get("action") and \
                c["action"].get("id") == preferred_action.get("id"):
            score += 5
        scored.append((score, c))
    return scored


def select_action_v1(actor: Actor, state: CombatState) -> dict | None:
    """Pick the actor's full (action, target) for their turn — alternative
    to the candidate-scoring path. Returns a chosen dict, or None.

    Useful when the candidate generator is too restrictive (currently it
    only enumerates weapon_attacks; this function considers multiattack too).
    """
    enemies = [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    if not enemies:
        return None

    targeting_preset = behavior_profile.resolve_targeting_preset(actor)
    ability_preset = behavior_profile.resolve_ability_selection_preset(actor)

    target = targeting.pick_target(actor, enemies, state, targeting_preset)
    action = ability_selection.pick_action(actor, target, state, ability_preset)

    if action is None:
        return None
    return {
        "kind": action.get("type") or "weapon_attack",
        "action": action,
        "target": target,
        "actor": actor,
    }
