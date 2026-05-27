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
    from engine.core.spell_slots import has_slot, required_slot_level
    from engine.core.basic_actions import (
        built_in_actions_for, is_self_targeted_defensive_buff,
        is_self_targeted_heal,
    )

    candidates: list[dict] = []
    template = actor.template
    actions = [a for a in (template.get("actions") or [])
                if a.get("slot", "action") == slot]
    # PR #45: reactions (declared with `trigger: <event_name>`) are
    # NOT main / bonus candidates — they fire from event triggers via
    # the reaction system, not from turn-initiated decisions.
    actions = [a for a in actions if not a.get("trigger")]
    # Append built-in basic actions (Dodge / Disengage on main slot)
    # not already declared on the template. Per RAW: every creature
    # has these available implicitly. The threat-range gate inside
    # built_in_actions_for skips when no enemy can hit `actor` this
    # turn (otherwise actors would dodge in place instead of closing).
    actions += built_in_actions_for(actor, slot, state)
    # Filter out spell actions whose required slot is unavailable. Free
    # actions (no `spell_slot_level`) pass through. Cantrips would have
    # `spell_slot_level: 0` and also pass.
    actions = [a for a in actions
                if has_slot(actor, required_slot_level(a))]
    # Filter out feature-use-gated actions whose resource is depleted.
    # Actions without a `feature_use` field pass through (not gated).
    from engine.core.feature_uses import (
        required_feature_use as _req_feat,
        has_use as _has_feat,
    )
    actions = [a for a in actions
                if _has_feat(actor, _req_feat(a))]

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
            # EXCEPTION: actions that target `self` only (e.g., Dodge,
            # Second Wind) emit ONE candidate. Otherwise we'd generate N
            # redundant candidates in a 2+ ally party, all scoring
            # identically and all executing the same self-effect.
            self_only = (
                (action_type == "defensive_buff"
                    and is_self_targeted_defensive_buff(action))
                or (action_type == "heal"
                    and is_self_targeted_heal(action))
            )
            if self_only:
                candidates.append({
                    "kind": action_type,
                    "action": action,
                    "target": actor,
                    "actor": actor,
                })
            else:
                for ally in allies:
                    candidates.append({
                        "kind": action_type,
                        "action": action,
                        "target": ally,
                        "actor": actor,
                    })
        elif action_type == "offensive_buff":
            # Per-ally enumeration; skip self (a caster doesn't Bless
            # themselves to raise their own hit chance in v1 — the AI
            # would need to weigh "buff self vs swing weapon" which
            # gets pulled in by the spell-slot opportunity cost PR).
            for ally in allies:
                if ally.id == actor.id:
                    continue
                candidates.append({
                    "kind": "offensive_buff",
                    "action": action,
                    "target": ally,
                    "actor": actor,
                })
        elif action_type == "help":
            # Help: pick an adjacent ally; grant advantage on their next
            # attack. RAW gates:
            #   1. Helper must be within 5 ft of at least one living enemy
            #      (the helped ally's advantaged attack must target a
            #      creature within 5 ft of the helper — if no such creature
            #      exists this turn, Help can't pay off).
            #   2. Helped ally must be within 5 ft of helper.
            #   3. Cannot Help yourself.
            from engine.core.geometry import is_within_ft as _within
            adjacent_enemy = any(_within(actor, e, 5) for e in enemies)
            if not adjacent_enemy:
                continue
            for ally in allies:
                if ally.id == actor.id:
                    continue
                if not _within(actor, ally, 5):
                    continue
                candidates.append({
                    "kind": "help",
                    "action": action,
                    "target": ally,
                    "actor": actor,
                })
        elif action_type == "persistent_aura":
            # Two flavors (PR #43 + PR #44):
            #
            # 1. anchor='caster' (Spirit Guardians-shape) — aura moves
            #    with the caster. One candidate per turn, no positioning
            #    choice. Target is closest in-radius enemy as scoring
            #    proxy.
            #
            # 2. anchor='point' (Moonbeam, Cloud of Daggers) — placed
            #    at a chosen point at cast time. Emit one candidate
            #    per living enemy position (same pattern as Fireball's
            #    sphere AoE) so the AI can pick the best anchor.
            #    `origin_point` is set on the candidate; the primitive
            #    reads state.current_attack.area_origin at execute.
            anchor = _persistent_aura_anchor(action)
            if anchor == "point":
                cast_range = _persistent_aura_cast_range(action)
                for anchor_enemy in enemies:
                    if cast_range > 0 and not is_within_ft(
                            actor, anchor_enemy, cast_range):
                        continue
                    candidates.append({
                        "kind": "persistent_aura",
                        "action": action,
                        "target": anchor_enemy,
                        "origin_point": anchor_enemy.position,
                        "actor": actor,
                    })
            else:
                # Caster-anchored — single candidate
                radius = _persistent_aura_radius(action)
                in_radius_enemies = []
                if radius > 0:
                    in_radius_enemies = [e for e in enemies
                                           if is_within_ft(actor, e, radius)]
                primary = in_radius_enemies[0] if in_radius_enemies else (
                    enemies[0] if enemies else actor)
                candidates.append({
                    "kind": "persistent_aura",
                    "action": action,
                    "target": primary,
                    "actor": actor,
                })
        elif action_type == "disengage":
            # Disengage is a self-targeted utility action — no enemy or
            # ally target. Single candidate per turn that the actor can
            # take. AI scoring is small (~2 eHP) so it rarely beats real
            # attack options; mostly available for fixtures that need
            # OA-suppressed movement (e.g., RP constraint that forces
            # disengage before retreat).
            candidates.append({
                "kind": "disengage",
                "action": action,
                "target": actor,    # self for telemetry; no real target
                "actor": actor,
            })
        elif action_type == "hide":
            # Hide is a self-targeted utility action (PR #48). Gated
            # at execute time on heavily-obscured / 3-quarters-cover.
            # PR #59: real eHP scoring via `offensive_ehp_hide`.
            candidates.append({
                "kind": "hide",
                "action": action,
                "target": actor,
                "actor": actor,
            })
        elif action_type == "search":
            # Search is a self-emitted utility action (PR #55). Built-in
            # version is injected by `built_in_actions_for` only when a
            # Hide-source hidden enemy exists beyond auto-spot range; if
            # the actor declares an explicit search action on their
            # template, we also emit it here. PR #59: real eHP scoring
            # via `offensive_ehp_search`.
            candidates.append({
                "kind": "search",
                "action": action,
                "target": actor,
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
        elif action_type == "aoe_attack":
            # AoE candidate shape depends on area.shape:
            #   - sphere: origin = enemy.position; no direction. Each
            #     living enemy in cast_range becomes a candidate origin
            #     (catches "cast on the cluster" naturally).
            #   - cone / line: origin = caster.position; direction =
            #     unit_vector toward enemy. Each living enemy in cast_range
            #     becomes a candidate direction (same enemy → same direction
            #     after snapping; duplicates score identically and tie-break
            #     by first listed).
            from engine.core.geometry import unit_direction
            area = action.get("area") or {}
            shape = (area.get("shape") or "sphere").lower()
            # `range_ft` semantics differ by shape:
            #   - sphere: how far the caster can place the origin
            #     (e.g., Fireball 150 ft)
            #   - cone / line: origin IS the caster, so range_ft is
            #     irrelevant. We gate by `length_ft` instead so we
            #     don't generate candidates pointed at enemies the
            #     spell can't reach at all.
            if shape == "sphere":
                cast_range = int(area.get("range_ft", 60))
                for anchor in enemies:
                    if not is_within_ft(actor, anchor, cast_range):
                        continue
                    candidates.append({
                        "kind": "aoe_attack",
                        "action": action,
                        "target": anchor,
                        "origin_point": anchor.position,
                        "actor": actor,
                    })
            elif shape in ("cone", "line"):
                # No range_ft filter; gate by length_ft so we skip
                # directions whose anchor enemy is beyond reach. The
                # scoring still handles "no affected enemies" gracefully
                # (returns 0) — this just trims obviously-useless
                # candidates.
                length_ft = int(area.get("length_ft", 30))
                for anchor in enemies:
                    if not is_within_ft(actor, anchor, length_ft):
                        continue
                    direction = unit_direction(actor.position, anchor.position)
                    if direction == (0, 0):
                        continue   # caster on top of enemy: skip
                    candidates.append({
                        "kind": "aoe_attack",
                        "action": action,
                        "target": anchor,
                        "origin_point": actor.position,
                        "direction": direction,
                        "actor": actor,
                    })
    return candidates


def _persistent_aura_radius(action: dict) -> int:
    """Return the radius_ft for a persistent_aura action by reading
    the first persistent_aura primitive in its pipeline. Returns 0 if
    no persistent_aura step is found (defensive)."""
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == "persistent_aura":
            params = step.get("params") or {}
            return int(params.get("radius_ft", 0))
    # Also check the action's `area:` block as a fallback shape
    area = action.get("area") or {}
    return int(area.get("radius_ft", 0))


def _persistent_aura_anchor(action: dict) -> str:
    """Return the anchor type ('caster' or 'point') from the
    persistent_aura step. Default 'caster' for backward compatibility."""
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == "persistent_aura":
            params = step.get("params") or {}
            return params.get("anchor", "caster")
    return "caster"


def _persistent_aura_cast_range(action: dict) -> int:
    """Return the cast range for placing a point-anchored aura. Reads
    from action.area.range_ft (parallel to Fireball-style AoE spells)
    with a default of 60 ft. Returns 0 only if explicitly set to 0."""
    area = action.get("area") or {}
    return int(area.get("range_ft", 60))


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

    Counterspell hook (PR #46): for spell-slot actions (any action
    declaring `spell_slot_level >= 1`), emit `spell_cast_initiated`
    BEFORE running the pipeline. Counterspell reactions hook this
    event and may set `state.cast_cancelled = True`. If cancelled,
    skip the pipeline but still consume the slot (RAW 2024: the
    original caster's slot is consumed even on successful counter).
    """
    if not chosen:
        return
    actor = chosen["actor"]
    action = chosen["action"]
    from engine.core.spell_slots import required_slot_level, consume_slot
    slot_level = required_slot_level(action)

    # Counterspell hook: spell-cast event before pipeline execution.
    # `cast_cancelled` is per-action — set to False before, reactions
    # may flip to True.
    state.cast_cancelled = False
    if slot_level > 0:
        from engine.core.reactions import resolve_reaction_triggers
        resolve_reaction_triggers("spell_cast_initiated", {
            "caster": actor,
            "action": action,
            "spell_slot_level": slot_level,
        }, state, event_bus)
    cast_was_cancelled = state.cast_cancelled
    state.cast_cancelled = False  # reset after

    if cast_was_cancelled:
        # Spell countered. Skip the pipeline, but still consume the
        # slot below (RAW 2024). Log the cancellation for visibility.
        state.event_log.append({
            "event": "spell_cancelled",
            "actor": actor.id,
            "action": action.get("id"),
            "slot_level": slot_level,
        })
    elif action.get("type") == "multiattack":
        _execute_multiattack(actor, action, state, event_bus, primitives)
    elif action.get("type") == "disengage":
        # Disengage: utility action; sets actor.disengaging = True for
        # the rest of the turn so movement skips OA triggers. No pipeline
        # to invoke (or, if a fixture declares one, run it for
        # extensibility).
        actor.disengaging = True
        state.event_log.append({
            "event": "disengage_taken",
            "actor": actor.id,
            "action": action.get("id"),
        })
        if action.get("pipeline"):
            _execute_single(chosen, state, event_bus, primitives)
    elif action.get("type") == "hide":
        # Hide action (PR #48): gate on heavy obscurement OR
        # three-quarters-or-total cover. Then roll DEX (Stealth)
        # check vs DC 15. On success, apply co_invisible with
        # source-tag "hide" (so we can scrub it later when the
        # actor attacks). RAW 2024 simplification: fixed DC 15;
        # passive Perception variant deferred.
        _execute_hide(actor, action, state, event_bus, primitives)
    elif action.get("type") == "search":
        # Search action (PR #55): roll d20 + Perception modifier
        # vs each Hide-source-hidden enemy's recorded stealth_total.
        # On success, scrub the Hide-source co_invisible. v1 reveal
        # is global (one mutation, all observers see); per-observer
        # `spotted_by:` tracking deferred.
        _execute_search(actor, action, state, event_bus, primitives)
    else:
        _execute_single(chosen, state, event_bus, primitives)

    # Mark the right slot used — read the action's `slot` field (default 'action').
    # Lets bonus_action / reaction tracking work without separate plumbing.
    slot = action.get("slot", "action")
    if slot in actor.actions_used_this_turn:
        actor.actions_used_this_turn[slot] = True
    else:
        actor.actions_used_this_turn[slot] = True   # safe to add

    # Concentration: if the action is flagged `concentration: true`,
    # the actor takes up (or replaces) their concentration slot.
    # Skipped if the spell was countered (PR #46) — RAW: the original
    # caster's concentration doesn't take hold when the spell fizzles.
    if action.get("concentration") and not cast_was_cancelled:
        from engine.core.concentration import apply_concentration
        apply_concentration(actor, action, state)

    # Spell slot consumption — only fires for actions with
    # `spell_slot_level >= 1`. Free actions and cantrips skip. Slot
    # is consumed EVEN IF the spell was countered (RAW 2024).
    level = slot_level
    if level > 0:
        consume_slot(actor, level, state, action_id=action.get("id"))

    # Feature-use consumption — only fires for actions with a
    # `feature_use` resource key (Second Wind, Lay on Hands, etc.).
    # Spell slots and feature uses are independent gates — an action
    # could in principle consume both, though no RAW spell does.
    from engine.core.feature_uses import (
        required_feature_use as _req_feat,
        consume_use as _consume_feat,
    )
    feature_key = _req_feat(action)
    if feature_key is not None:
        _consume_feat(actor, feature_key, state, action_id=action.get("id"))


def _execute_single(chosen: dict, state: CombatState, event_bus, primitives) -> None:
    """Execute one action's primitive pipeline."""
    actor = chosen["actor"]
    target = chosen.get("target")
    action = chosen["action"]
    # AoE actions: propagate origin (sphere/cone/line) and direction
    # (cone/line) into state so forced_save's area resolver can filter
    # creatures by geometry.
    origin = chosen.get("origin_point")
    direction = chosen.get("direction")

    state.current_attack = {
        "actor": actor,
        "target": target,
        "action": action,
        "state": None,
        "had_advantage": False,
        "had_disadvantage": False,
        "area_origin": tuple(origin) if origin is not None else None,
        "area_direction": tuple(direction) if direction is not None else None,
    }

    if origin is not None:
        log_entry = {
            "event": "aoe_origin_placed",
            "actor": actor.id,
            "action": action.get("id"),
            "origin": list(origin),
        }
        if direction is not None:
            log_entry["direction"] = list(direction)
        state.event_log.append(log_entry)

    for step in action.get("pipeline", []):
        primitive_name = step["primitive"]
        params = step.get("params", {})
        when = step.get("when")
        if when:
            cond = when.get("condition", "")
            if cond and not _evaluate_simple_condition(cond, state):
                continue
        primitives.invoke(primitive_name, params, state, event_bus)


def _execute_hide(actor, action: dict, state: CombatState,
                    event_bus, primitives) -> None:
    """Execute a Hide action (PR #48 + PR #51).

    Gates (RAW 2024): actor must be either Heavily Obscured (in a
    declared obscurement zone) OR behind three-quarters or total
    cover. If neither applies, the hide attempt is logged as failed
    with reason=no_cover_or_obscurement.

    On a passing gate, roll d20 + DEX_mod + PB(stealth) vs DC 15
    (PR #51: Stealth proficiency now adds PB to the roll via
    engine.core.skills.skill_modifier). On success, apply
    `co_invisible` condition with source.action_id="a_hide" so it
    can be scrubbed when the actor next attacks (see
    primitives._attack_roll). The rolled Stealth total is recorded
    on the condition under `stealth_total` — `vision.can_actor_see`
    consults this against an observer's passive Perception, so a
    high-Wis observer auto-spots a low-Stealth hider.

    The action's `pipeline` is run AFTER the gate / check (in case
    a fixture wants extra effects on hide). v1 fixtures don't use
    this; the apply_condition is hard-coded here.
    """
    from engine.core.vision import is_in_obscured_zone
    from engine.core.skills import skill_modifier

    # Gate
    heavily_obscured = is_in_obscured_zone(actor.position, state)
    has_cover_3_4_plus = actor.cover in ("three_quarters", "total")
    if not (heavily_obscured or has_cover_3_4_plus):
        state.event_log.append({
            "event": "hide_attempted",
            "actor": actor.id,
            "outcome": "failed",
            "reason": "no_cover_or_obscurement",
        })
        return

    # Stealth check — d20 + Stealth modifier (DEX + PB if proficient).
    # PR #51: skill_modifier handles both monster-listed bonuses and
    # PC-schema computed bonuses uniformly.
    import engine.primitives as primitives_module
    rng = primitives_module._rng    # use module-level rng (test-friendly)
    d20 = rng.randint(1, 20)
    stealth_mod = skill_modifier(actor, "stealth")
    total = d20 + stealth_mod
    DC = 15
    success = total >= DC

    state.event_log.append({
        "event": "hide_attempted",
        "actor": actor.id,
        "d20": d20,
        "stealth_mod": stealth_mod,
        "total": total,
        "dc": DC,
        "outcome": "success" if success else "failed",
        "gate": "heavy_obscurement" if heavily_obscured else "cover",
    })
    if not success:
        return

    # Apply co_invisible with source tagged as a_hide so attack
    # primitives can scrub it after the actor attacks. PR #51:
    # also record `stealth_total` so observer.passive_perception
    # comparisons in vision.can_actor_see have a number to beat.
    actor.applied_conditions.append({
        "condition_id": "co_invisible",
        "source_id": actor.id,
        "source_action_id": "a_hide",
        "applied_at_round": state.round,
        "stealth_total": total,
    })
    state.event_log.append({
        "event": "hidden",
        "actor": actor.id,
        "source": "a_hide",
        "stealth_total": total,
    })


def _execute_search(actor, action: dict, state: CombatState,
                       event_bus, primitives) -> None:
    """Execute a Search action (PR #55).

    For each living enemy with a Hide-source `co_invisible` condition
    in the encounter, roll d20 + actor's Perception modifier vs the
    enemy's recorded `stealth_total`. On success, scrub the Hide-
    source `co_invisible` from the enemy (v1: spotted means spotted
    for everyone).

    Spell-source Invisible (`source_action_id != "a_hide"`) is NOT
    affected — only Hide is RAW-bypassable by Perception. Spell
    Invisibility requires Truesight or specific anti-invisibility
    spells.

    No enemies-in-sight check beyond "is hidden via Hide" — v1 trusts
    the gated emission in `built_in_actions_for` to only fire Search
    when there's something to find. If a fixture forces Search via
    an explicit action declaration, it still runs through the loop
    and logs the no-op cleanly.

    Logs:
      - search_attempted: actor.id, no-targets case
      - search_check: per-target d20 / perception_mod / total / dc /
        outcome
      - creature_revealed: when scrub fires
    """
    import engine.primitives as primitives_module
    from engine.core.skills import skill_modifier
    rng = primitives_module._rng

    perception_mod = skill_modifier(actor, "perception")

    # Find candidate hidden enemies. Match the gate from
    # `_has_unspotted_hidden_enemy` in basic_actions.py.
    candidates: list[tuple] = []
    for enemy in state.encounter.actors:
        if enemy.id == actor.id or enemy.side == actor.side:
            continue
        if not enemy.is_alive():
            continue
        for cond in (enemy.applied_conditions or []):
            if cond.get("condition_id") != "co_invisible":
                continue
            if cond.get("source_action_id") != "a_hide":
                continue
            candidates.append((enemy, cond))

    if not candidates:
        state.event_log.append({
            "event": "search_attempted",
            "actor": actor.id,
            "outcome": "no_targets",
        })
        return

    for target, hide_cond in candidates:
        d20 = rng.randint(1, 20)
        check_total = d20 + perception_mod
        stealth_total = int(hide_cond.get("stealth_total", 0))
        success = check_total >= stealth_total

        state.event_log.append({
            "event": "search_check",
            "actor": actor.id,
            "target": target.id,
            "d20": d20,
            "perception_mod": perception_mod,
            "total": check_total,
            "dc": stealth_total,
            "outcome": "success" if success else "failed",
        })

        if not success:
            continue

        # Scrub the Hide-source co_invisible. Filter the target's
        # applied_conditions list to drop the matching entry. Match
        # on identity of the dict (same as cond) — safer than re-
        # checking source_action_id when multiple hides might exist
        # (rare; same actor doesn't double-Hide in v1, but defensive).
        target.applied_conditions = [
            c for c in target.applied_conditions
            if c is not hide_cond
        ]
        state.event_log.append({
            "event": "creature_revealed",
            "actor": actor.id,
            "target": target.id,
            "via": "search",
        })


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
