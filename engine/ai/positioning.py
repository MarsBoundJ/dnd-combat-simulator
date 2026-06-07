"""Positioning & AoE-targeting AI (see docs/positioning-model.md).

Phase 1a — the **AoE coverage routine**: the shared "where do I aim this
area effect to deliver the most eHP?" function used by

  - monster offense (pick the best breath / Fireball placement), and
  - the PC AoE-exposure positioning term (run the boss's routine
    adversarially to find the worst it can do to a formation).

It enumerates a small, target-relevant candidate set of placements and
ranks them with `offensive_ehp_aoe`, which is already eHP-denominated and
already nets friendly fire + wall occlusion — so ranking by it satisfies
"rank by eHP, not raw target count" for free.

Phase-1a scope (intentionally minimal, purely additive — nothing calls
this yet):
  - cone / line: apex = the attacker's current square; orientation = the 8
    grid directions (the exact candidate set on an 8-direction grid).
  - sphere / emanation: origin candidates = living enemies within cast
    range (anchor-on-target), plus self for emanations.

Deferred (documented in the model doc): movement apexes (moving before
placing), straddled lines (needs an `actors_in_line` extension), and free
(continuous) orientation. Those are §9/§11 follow-ups.
"""
from __future__ import annotations

from engine.core.geometry import is_within_ft
from engine.core.state import Actor, CombatState

# The 8 grid directions — the exact candidate orientation set for cone/line
# AoEs on an 8-direction grid (no continuous angles yet).
_EIGHT_DIRS: tuple[tuple[int, int], ...] = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)


def max_aoe_coverage(action: dict, attacker: Actor, state: CombatState,
                      *, apex: tuple[int, int] | None = None) -> dict | None:
    """Best placement of `action`'s area effect, maximizing delivered eHP.

    Returns ``{"origin": (x, y), "direction": (dx, dy) | None, "ehp": float}``
    for the best placement, or ``None`` if the action has no usable area or
    no placement delivers positive eHP (e.g. it would only catch allies).

    Scoring is delegated to `offensive_ehp_aoe` (eHP, friendly-fire- and
    wall-occlusion-aware), so the winner is the eHP-max, not the
    most-targets-hit.
    """
    from engine.ai.ehp_scoring import offensive_ehp_aoe

    area = action.get("area") or {}
    shape = (area.get("shape") or "sphere").lower()
    origin0 = tuple(apex) if apex is not None else tuple(attacker.position)

    candidates: list[tuple[tuple[int, int], tuple[int, int] | None]] = []
    if shape in ("cone", "line"):
        # Apex fixed at the attacker's square (movement deferred); try every
        # grid orientation.
        candidates = [(origin0, d) for d in _EIGHT_DIRS]
    elif shape in ("sphere", "emanation"):
        cast_range = int(area.get("range_ft", 60))
        living_enemies = [a for a in state.encounter.actors
                          if a.is_alive() and a.side != attacker.side]
        seen: set[tuple[int, int]] = set()
        for e in living_enemies:
            o = tuple(e.position)
            if o not in seen and is_within_ft(attacker, o, cast_range):
                seen.add(o)
                candidates.append((o, None))
        if shape == "emanation" and origin0 not in seen:
            candidates.append((origin0, None))
    else:
        return None

    best: dict | None = None
    for origin, direction in candidates:
        ehp = offensive_ehp_aoe(attacker, origin, action, state,
                                 direction=direction)
        if best is None or ehp > best["ehp"]:
            best = {"origin": origin, "direction": direction, "ehp": ehp}

    if best is None or best["ehp"] <= 0:
        return None
    return best


# ============================================================================
# PC positioning utility (Phase 1c) — AoE-exposure + enablement + best square
# ============================================================================
#
# Per docs/positioning-model.md §2/§5/§11. v1 scope: the AoE-exposure term
# (risk-adjusted, single-ply adversary-aware) under the action-enablement
# constraint. Melee-exposure, cover, ally-aura, and concentration terms are
# documented follow-ups (aura/concentration are blocked on unbuilt content /
# the control-eHP scorer). These are pure functions — wiring into the
# runner's movement is Phase 1c-ii.

_ACTING_TYPES = ("weapon_attack", "save_attack", "hard_control", "aoe_attack")


def _action_range_ft(action: dict) -> int:
    """Best-effort range (ft): top-level range_ft/reach_ft, else the
    attack_roll step's range, else 5 (melee)."""
    if "range_ft" in action:
        return int(action["range_ft"])
    if "reach_ft" in action:
        return int(action["reach_ft"])
    for step in action.get("pipeline", []) or []:
        if step.get("primitive") == "attack_roll":
            p = step.get("params", {}) or {}
            return int(p.get("range_ft", p.get("reach_ft", 5)))
    return 5


def actor_act_range_ft(actor: Actor) -> int:
    """Max range across the actor's offensive/control actions (ft); 5 if
    purely melee."""
    ranges = [_action_range_ft(a)
              for a in (actor.template.get("actions") or [])
              if a.get("type") in _ACTING_TYPES]
    return max(ranges) if ranges else 5


def largest_enemy_aoe_radius(actor: Actor, state: CombatState) -> int:
    """A representative AoE 'danger radius' (ft) across living enemies' area
    actions — used only to GATE positioning (is there an AoE threat at all?).
    0 if no living enemy has an area attack."""
    best = 0
    for enemy in state.encounter.actors:
        if enemy.side == actor.side or not enemy.is_alive():
            continue
        for act in (enemy.template.get("actions") or []):
            area = act.get("area") or {}
            shape = (area.get("shape") or "").lower()
            r = 0
            if shape == "sphere":
                r = area.get("radius_ft") or ((area.get("size_ft") or 0) // 2)
            elif shape in ("cone", "line"):
                r = (area.get("length_ft") or 0) // 2
            elif shape in ("cube", "emanation"):
                r = (area.get("size_ft") or 0) // 2
            best = max(best, int(r))
    return best


def _ehp_to_actor(enemy: Actor, action: dict, origin, direction,
                   actor: Actor, base_state: CombatState) -> float:
    """eHP a single AoE placement deals to `actor` specifically. Scored in a
    throwaway two-actor state ([enemy, actor]) so offensive_ehp_aoe's sum is
    exactly the actor's contribution (no other allies/enemies, no friendly
    fire). Reuses the real scorer for per-actor eHP."""
    from engine.ai.ehp_scoring import offensive_ehp_aoe
    from engine.core.state import Encounter, CombatState as _CS
    solo = _CS(encounter=Encounter(id="_expo", actors=[enemy, actor]))
    solo.content_registry = getattr(base_state, "content_registry", None)
    return max(0.0, offensive_ehp_aoe(enemy, origin, action, solo,
                                       direction=direction))


def aoe_exposure_ehp(actor: Actor, dest: tuple[int, int], state: CombatState,
                      *, drop_penalty: float = 1.5) -> float:
    """Expected eHP `actor` loses to enemy area attacks if it stands at
    `dest` — single-ply adversary-aware: each AoE-capable enemy aims its
    BEST placement (max_aoe_coverage, computed with the actor at `dest`, so
    the enemy's optimum accounts for the whole formation), and we sum the
    eHP that lands on the actor.

    Risk-adjusted: an exposure that could plausibly drop the actor (≥ 80% of
    current HP) is scaled by `drop_penalty` (the threshold nonlinearity —
    being dropped is superlinearly bad). λ-style risk tolerance is the
    `drop_penalty` knob; the dial sets it per actor (Phase 1c-ii).

    Temporarily moves the actor to `dest` and restores it (pure aside from
    that)."""
    saved = actor.position
    actor.position = tuple(dest)
    try:
        total = 0.0
        enemies = [a for a in state.encounter.actors
                   if a.is_alive() and a.side != actor.side]
        for enemy in enemies:
            for action in (enemy.template.get("actions") or []):
                if not (action.get("area")):
                    continue
                best = max_aoe_coverage(action, enemy, state)
                if best is None:
                    continue
                total += _ehp_to_actor(enemy, action, best["origin"],
                                        best["direction"], actor, state)
        if total >= max(1, actor.hp_current) * 0.8:
            total *= drop_penalty
        return total
    finally:
        actor.position = saved


def can_act_from(actor: Actor, dest: tuple[int, int],
                  state: CombatState) -> bool:
    """Enablement constraint (v1, offensive): True if ≥1 of the actor's
    offensive/control actions has a living enemy in range AND with clear
    line of effect from `dest`. (Support/heal enablement — a Cleric reaching
    a downed ally — is a documented follow-up; needs the heal/buff action
    taxonomy.)"""
    from engine.core.geometry import line_of_effect_blocked
    walls = getattr(state, "walls", None)
    enemies = [a for a in state.encounter.actors
               if a.is_alive() and a.side != actor.side]
    if not enemies:
        return True   # nothing to enable against; don't trap the actor
    for action in (actor.template.get("actions") or []):
        if action.get("type") not in _ACTING_TYPES:
            continue
        rng = _action_range_ft(action)
        for e in enemies:
            if (is_within_ft(dest, e.position, rng)
                    and not (walls and line_of_effect_blocked(
                        dest, e.position, walls))):
                return True
    return False


def reachable_squares(actor: Actor,
                       state: CombatState) -> list[tuple[int, int]]:
    """Squares the actor can reach this turn (best of walk/fly speed,
    Chebyshev, straight-line wall-aware), excluding squares occupied by other
    living actors. Includes the current square (staying put is an option).

    Uses the actor's best open-field movement speed — `max(walk, fly)` — so a
    flier relocates its full fly speed: an Adult Dragon (walk 40, fly 80)
    reaches 16 squares, not 8, which the breath chase needs to flank a spread
    formation. Swim/climb are terrain-gated and excluded from the open-field
    budget. (No current PC flies, so PC de-cluster behavior is unchanged.)"""
    from engine.core.geometry import SQUARE_SIZE_FT, segment_blocked
    speeds = actor.speed or {}
    speed = max(int(speeds.get("walk", 30)), int(speeds.get("fly", 0)))
    budget = speed // SQUARE_SIZE_FT
    walls = getattr(state, "walls", None)
    occupied = {tuple(a.position) for a in state.encounter.actors
                if a.is_alive() and a.id != actor.id}
    cx, cy = actor.position
    out: list[tuple[int, int]] = []
    for dx in range(-budget, budget + 1):
        for dy in range(-budget, budget + 1):
            if max(abs(dx), abs(dy)) > budget:
                continue
            cand = (cx + dx, cy + dy)
            if cand in occupied:
                continue
            if (dx or dy) and walls and segment_blocked((cx, cy), cand,
                                                         walls, "move"):
                continue
            out.append(cand)
    return out


def offensive_reach_ehp(actor: Actor, dest: tuple[int, int],
                         state: CombatState) -> float:
    """Best offensive eHP `actor` can DELIVER standing at `dest` — the
    positive (offense) counterpart to `aoe_exposure_ehp`'s cost term.

    Max over the actor's offensive/control actions of the best eHP achievable
    from `dest`, accounting for range + line of effect:
      - AoE actions (`area`): `max_aoe_coverage` with the actor at `dest`, so
        the cone apex / sphere anchoring move WITH the actor — this is the
        term that rewards stepping to a square whose cone catches more
        enemies. Skipped when ≤1 living enemy (an AoE on a lone target is just
        single-target value, and the 8-direction scan is the expensive part —
        bounding it here keeps the boss sim fast).
      - weapon_attack / multiattack / save_attack: best in-range, LoE-clear
        living-enemy target via the matching offensive eHP scorer.

    The single-target damage scorers are position-INVARIANT (they read hit
    probability + expected damage, not distance), so this term is CONSTANT
    across squares for a pure single-target attacker — which is exactly why
    adding it leaves the de-cluster (exposure-minimizing) behavior unchanged
    and only differentiates squares for AoE shapes / multi-enemy reach.

    Temporarily moves the actor to `dest` (positions drive the AoE apex and
    range/LoE) and restores it — pure aside from that.
    """
    from engine.ai.ehp_scoring import (
        offensive_ehp_single_attack, offensive_ehp_multiattack,
        offensive_ehp_save_attack,
    )
    from engine.core.geometry import line_of_effect_blocked

    saved = actor.position
    actor.position = tuple(dest)
    try:
        walls = getattr(state, "walls", None)
        enemies = [a for a in state.encounter.actors
                   if a.is_alive() and a.side != actor.side]
        if not enemies:
            return 0.0
        best = 0.0
        multi_enemy = len(enemies) >= 2
        for action in (actor.template.get("actions") or []):
            if action.get("area"):
                # AoE coverage only differentiates squares with 2+ targets;
                # on a lone enemy it reduces to single-target value (and the
                # 8-dir scan is costly), so skip the scan in 1-enemy fights.
                if not multi_enemy:
                    continue
                cov = max_aoe_coverage(action, actor, state)
                if cov is not None:
                    best = max(best, cov["ehp"])
                continue
            kind = action.get("type")
            if kind not in ("weapon_attack", "multiattack", "save_attack"):
                continue
            rng = _action_range_ft(action)
            for e in enemies:
                if not is_within_ft(dest, e.position, rng):
                    continue
                if walls and line_of_effect_blocked(dest, e.position, walls):
                    continue
                if kind == "weapon_attack":
                    v = offensive_ehp_single_attack(actor, e, action, state)
                elif kind == "multiattack":
                    v = offensive_ehp_multiattack(actor, e, action, state)
                else:   # save_attack
                    v = offensive_ehp_save_attack(actor, e, action, state)
                best = max(best, v)
        return best
    finally:
        actor.position = saved


# Weight on incoming melee-threat DPR when concentrating — roughly the eHP you
# forfeit by risking the held concentration (P(fail the CON save) × the spell's
# ongoing value). A blunt constant for v1, tuned so a caster backs out of enemy
# melee reach to keep its spell up (Lever C).
CONCENTRATION_RISK_WEIGHT = 1.0


def _enemy_melee_reach_ft(enemy: Actor) -> int:
    """Max MELEE reach (ft) across an enemy's attacks (reach_ft, not ranged
    range_ft); default 5. Reads weapon_attack actions + multiattack sub-actions.
    Used to size the melee threat radius for concentration protection."""
    template = enemy.template or {}
    by_id = {a.get("id"): a for a in (template.get("actions") or [])}
    best = 5

    def _scan(action):
        nonlocal best
        for step in action.get("pipeline") or []:
            if step.get("primitive") == "attack_roll":
                p = step.get("params") or {}
                if "reach_ft" in p and "range_ft" not in p:
                    best = max(best, int(p["reach_ft"]))

    for a in (template.get("actions") or []):
        if a.get("type") == "weapon_attack":
            _scan(a)
        elif a.get("type") == "multiattack":
            for sid in (a.get("sub_actions") or []):
                if sid in by_id:
                    _scan(by_id[sid])
    return best


def concentration_break_risk_ehp(actor: Actor, dest: tuple[int, int],
                                  state: CombatState) -> float:
    """eHP risk of LOSING a held concentration by standing at `dest` (Lever C):
    the incoming MELEE threat there — every living enemy that could move-and-
    reach `dest` this turn (distance ≤ its walk speed + melee reach) contributes
    its estimated DPR — weighted by CONCENTRATION_RISK_WEIGHT. 0 if the actor
    isn't concentrating.

    This makes a concentrating caster back out of enemy melee reach to protect
    its spell — the dominant, AVOIDABLE concentration-breaker for a back-line
    caster (a hit forces a CON save that can drop the whole effect). Ranged
    threat isn't distance-avoidable (only cover) and is a documented follow-up."""
    if not getattr(actor, "concentration_on", None):
        return 0.0
    from engine.ai.defensive_ehp import estimate_dpr
    from engine.core.geometry import distance_ft
    risk = 0.0
    for e in state.encounter.actors:
        if not e.is_alive() or e.side == actor.side:
            continue
        reach = _enemy_melee_reach_ft(e)
        speed = int((e.speed or {}).get("walk", 30))
        if distance_ft(e.position, dest) <= speed + reach:
            risk += estimate_dpr(e)
    return risk * CONCENTRATION_RISK_WEIGHT


def position_utility(actor: Actor, dest: tuple[int, int],
                      state: CombatState) -> float:
    """eHP utility of standing at `dest` (per docs/positioning-model.md §2):
    delivered offense − AoE exposure − concentration-break risk. Higher is
    better. (Ally-aura, cover are still follow-ups.)"""
    return (offensive_reach_ehp(actor, dest, state)
            - aoe_exposure_ehp(actor, dest, state)
            - concentration_break_risk_ehp(actor, dest, state))


def best_position(actor: Actor, state: CombatState) -> tuple[int, int] | None:
    """The reachable, still-able-to-act square MAXIMIZING position utility
    (delivered offense − AoE exposure).

    Previously this minimized AoE exposure alone (defense-only), so it could
    flee to a safe square that gutted the actor's own offense. The offensive
    term (`offensive_reach_ehp`) makes the trade explicit: a square is better
    if it both dodges the breath AND lands a fatter cone — and the actor
    won't retreat to a corner where it can only plink. For a pure
    single-target attacker the offense term is position-invariant, so this
    still reduces to exposure-minimization (de-cluster behavior preserved).

    Gated to the party-coupled finding: only repositions when a living enemy
    has an area attack AND the actor has allies to de-cluster from. Returns
    the chosen square, or None if staying put is already best / gating fails
    (the caller then keeps its normal move logic).

    Clown-Car note: allies move on their own turns and positions update live
    in `state`, so a later-moving ally already sees an earlier one's new
    square — no explicit ally-claim needed for turn-by-turn play (only batch
    planning, i.e. the future superagent, would).
    """
    # A CONCENTRATING actor always considers repositioning — to back out of
    # enemy melee reach and protect its spell (Lever C), regardless of AoE
    # threat / allies. Otherwise keep the party-coupled de-cluster gate: only
    # reposition when an enemy has an area attack AND there are allies to
    # spread from.
    concentrating = bool(getattr(actor, "concentration_on", None))
    if not concentrating:
        if largest_enemy_aoe_radius(actor, state) <= 0:
            return None
        allies = [a for a in state.encounter.actors
                  if a.is_alive() and a.side == actor.side and a.id != actor.id]
        if not allies:
            return None

    cur = tuple(actor.position)
    # Only reposition when the actor can ALREADY act from where it stands —
    # otherwise defer to the greedy move-to-engage (which closes into range).
    # Keeps best_position a "find a better in-range square" behavior, not a
    # "move into range" one (a far melee PC still just charges in).
    if not can_act_from(actor, cur, state):
        return None
    best_sq = cur
    best_util = position_utility(actor, cur, state)
    from engine.core.geometry import distance_ft
    for cand in reachable_squares(actor, state):
        if cand == cur or not can_act_from(actor, cand, state):
            continue
        util = position_utility(actor, cand, state)
        if (util > best_util + 1e-9
                or (abs(util - best_util) <= 1e-9
                    and distance_ft(cand, cur) < distance_ft(best_sq, cur))):
            best_util, best_sq = util, cand
    return best_sq if best_sq != cur else None


def _available_aoe_actions(actor: Actor, state: CombatState) -> list[dict]:
    """The actor's area actions usable THIS turn — i.e. an `area` block AND
    recharge-available (a spent breath weapon is excluded). The recharge roll
    happens at turn start before this runs, so availability is accurate."""
    from engine.core import recharge
    return [a for a in (actor.template.get("actions") or [])
            if a.get("area") and recharge.is_available(actor, a)]


def best_aoe_attack_position(actor: Actor,
                              state: CombatState) -> tuple[int, int] | None:
    """The reachable square that maximizes this actor's delivered OFFENSE by
    relocating its area-attack apex to catch more enemies — the monster-side
    counterpart to `best_position`'s PC de-cluster.

    Gated to: the actor has an area action AVAILABLE this turn (recharge), and
    there are ≥2 living enemies (an AoE on a lone enemy is just single-target
    value — there's no apex worth optimizing, and single-target damage is
    position-invariant). Scored by `position_utility` (offense − exposure −
    conc-risk): since the single-target damage terms are position-invariant,
    the ONLY thing that differentiates squares is the AoE coverage gained vs
    the area-exposure taken — so this relocates to widen the cone WITHOUT
    walking into the party's own AoE, and won't move when a square merely
    trades coverage for exposure. Returns the chosen square, or None if staying
    put is already best / the gate fails (caller keeps normal move logic).

    v1 scope: candidate squares use WALK speed (a flier's larger reach is a
    follow-up); OA cost of the move isn't netted into the utility (a tanky boss
    eats OAs — also a follow-up); and `position_utility`'s offense term values
    every area action regardless of recharge, so a monster with TWO area
    actions (one spent) could still be valued on the spent one — fine for the
    single-breath bosses this targets, noted for multi-AoE casters."""
    aoe_actions = _available_aoe_actions(actor, state)
    if not aoe_actions:
        return None
    enemies = [a for a in state.encounter.actors
               if a.is_alive() and a.side != actor.side]
    if len(enemies) < 2:
        return None
    # Max AoE reach (cone/line length, sphere/emanation range) among the
    # available area actions. A candidate apex farther than this from EVERY
    # enemy can't catch anyone — pruning those keeps the (large, for a fly-80
    # flier) reachable scan tractable AND keeps this an OFFENSIVE reposition: a
    # far square has zero AoE offense, so without the prune a high-exposure
    # boss could "chase" by fleeing to a safe-but-useless corner.
    aoe_reach = 0
    for a in aoe_actions:
        area = a.get("area") or {}
        aoe_reach = max(aoe_reach, int(area.get("length_ft") or 0),
                        int(area.get("range_ft") or 0),
                        int(area.get("size_ft") or 0))
    cur = tuple(actor.position)
    best_sq = cur
    best_util = position_utility(actor, cur, state)
    from engine.core.geometry import distance_ft
    for cand in reachable_squares(actor, state):
        if cand == cur:
            continue
        if aoe_reach and all(distance_ft(cand, e.position) > aoe_reach
                             for e in enemies):
            continue
        util = position_utility(actor, cand, state)
        if (util > best_util + 1e-9
                or (abs(util - best_util) <= 1e-9
                    and distance_ft(cand, cur) < distance_ft(best_sq, cur))):
            best_util, best_sq = util, cand
    return best_sq if best_sq != cur else None

