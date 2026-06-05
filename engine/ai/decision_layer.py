"""Decision layer orchestration — the public face of the AI module.

Two complementary public functions:

  - `score_candidates_v1(candidates, actor, state)` — the score_candidates
    socket from pipeline.py §7 step 5. Computes real offensive eHP per
    candidate (via engine.ai.ehp_scoring), then adds preset preference
    bonuses so the targeting / ability-selection dials still steer toward
    archetype-appropriate picks when eHP values are close.

  - `select_action_v1(actor, state)` — alternative API: instead of scoring
    a pre-generated candidate list, this picks the (action, target) tuple
    directly via the dial-driven AI. Useful when generate_candidates is
    too restrictive (e.g., it currently only enumerates weapon_attacks;
    select_action_v1 considers multiattack too).

Both share the same underlying logic: resolve the actor's dial presets,
delegate to targeting + ability_selection, return the result.

Scoring formula (v1):

    score = eHP_value × aggression_coefficient
          + TARGET_PREFERENCE_BONUS   if target matches preset's pick
          + ACTION_PREFERENCE_BONUS   if action matches preset's pick

The preference bonuses are deliberately small (a few eHP-equivalent units)
relative to typical eHP values — eHP carries the signal, dial preferences
break ties and steer when expected damage is comparable.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState
from engine.ai import targeting, ability_selection, behavior_profile
from engine.ai.ehp_scoring import aggression_coefficient, score_candidate


# Preference bonuses — small enough not to overpower real eHP differences,
# large enough to break ties between equivalently-rated candidates.
TARGET_PREFERENCE_BONUS = 2.0
ACTION_PREFERENCE_BONUS = 1.0


def score_candidates_v1(candidates: list[dict], actor: Actor,
                         state: CombatState) -> list[tuple[float, dict]]:
    """Score each candidate (action × target) tuple with eHP + preferences.

    Pipeline:
      1. Compute raw offensive eHP per candidate (via ehp_scoring).
      2. Scale by aggression_coefficient from the actor's archetype.
      3. Add a small preference bonus if the candidate matches the actor's
         preset-preferred target / action — this steers tie-breaking and
         keeps the archetype dials meaningful even when eHP is close.
    """
    if not candidates:
        return []

    # Resolve dials + preferred picks for the preference layer.
    targeting_preset = behavior_profile.resolve_targeting_preset(actor)
    ability_preset = behavior_profile.resolve_ability_selection_preset(actor)
    # IMPORTANT: filter to ACTUAL enemies (other-side, alive). Defensive
    # candidates (heal/buff/Dodge/etc.) target allies or self; including
    # those in this list would let the targeting dial accidentally pick
    # self as the "preferred enemy" (distance 0 → closest_enemy wins),
    # inflating Dodge / Disengage scores via the TARGET_PREFERENCE_BONUS.
    enemies = [c["target"] for c in candidates
                if c.get("target") and c["target"].is_alive()
                and c["target"].side != actor.side]
    enemies = list({e.id: e for e in enemies}.values())   # dedupe by id

    preferred_target = targeting.pick_target(actor, enemies, state,
                                              targeting_preset)
    preferred_action = ability_selection.pick_action(
        actor, preferred_target, state, ability_preset
    )
    aggression = aggression_coefficient(actor)

    # Focus-fire (optimization dial): when this side's dial says to concentrate
    # fire THIS decision (situational gate + dial-probability roll), LOCK
    # single-target offense onto the lowest-HP enemy. A bonus wouldn't suffice
    # — the eHP overkill-cap actively prefers fat high-HP targets (that's WHY
    # the party spreads), so we drop the other single-target offensive options
    # and retarget multiattack onto the focus enemy. AoE / heal / buff / control
    # are LEFT to compete normally, so a minion swarm still routes to AoE (it
    # out-scores the locked single-target) — exactly the right call.
    from engine.core.optimization_dial import (
        should_focus_fire, focus_fire_target)
    _ST_OFFENSE = {"weapon_attack", "save_attack", "multiattack"}

    def _is_st_offense(c: dict) -> bool:
        return (c.get("kind") in _ST_OFFENSE
                or (c.get("action") or {}).get("type") in _ST_OFFENSE)

    if should_focus_fire(actor, state):
        focus = focus_fire_target(actor, state, enemies)
        if focus is not None and any(
                _is_st_offense(c) and c.get("target")
                and c["target"].id == focus.id for c in candidates):
            kept = []
            for c in candidates:
                if not _is_st_offense(c):
                    kept.append(c)            # AoE / heal / buff / control
                    continue
                kind = c.get("kind") or (c.get("action") or {}).get("type")
                if kind == "multiattack":
                    c["target"] = focus       # focus the whole multiattack
                    kept.append(c)
                elif c.get("target") and c["target"].id == focus.id:
                    kept.append(c)            # the focus-target single attack
                # else: a spread option — dropped
            candidates = kept

    # Lazy import to keep core engine free of AI ↔ core circularity
    from engine.core.spell_slots import candidate_slot_cost

    scored: list[tuple[float, dict]] = []
    for c in candidates:
        ehp = score_candidate(c, state)
        # Subtract spell slot opportunity cost BEFORE aggression scaling.
        # Cost is in eHP units per ehp-action-framework.md §"Opportunity
        # Cost"; same scale as the gain. Free actions / cantrips → 0.
        cost = candidate_slot_cost(actor, c.get("action") or {}, state)
        ehp -= cost
        score = ehp * aggression
        if preferred_target and c.get("target") and \
                c["target"].id == preferred_target.id:
            score += TARGET_PREFERENCE_BONUS
        if preferred_action and c.get("action") and \
                c["action"].get("id") == preferred_action.get("id"):
            score += ACTION_PREFERENCE_BONUS
        scored.append((score, c))

    # Apply RP Constraint score modifications (Tier 2 forced choices +
    # Tier 3 weighted preferences). Per §6.3 + §6.4 these run AFTER the
    # base eHP + preference scoring as part of the single coherent
    # scoring pass. Hard filters (Tier 1) already ran in pipeline step 3.
    from engine.ai.rp_constraints import apply_score_modifications
    scored = apply_score_modifications(scored, actor, state)
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
