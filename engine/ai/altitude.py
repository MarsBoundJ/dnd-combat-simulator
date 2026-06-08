"""Flier altitude + aerial kiting (altitude model, Stage 2).

Stage 1 gave every actor an `elevation` (ft) and made `distance_ft` Chebyshev-3D,
so an airborne creature is automatically out of grounded-melee reach in BOTH
directions (a hovering dragon can't be hit by a greatsword, and can't bite a
creature on the ground). This stage adds the DECISION: a flier picks an
elevation each turn.

A flier KITES — hovers just above the tallest grounded-enemy melee reach — when:
  1. it actually flies (`fly` speed),
  2. its side's optimization dial is at least `KITE_MIN_DIAL` (a naive,
     WoTC-baseline monster fights grounded; only an above-baseline one kites),
  3. there are grounded MELEE enemies to deny (hovering doesn't dodge archers),
  4. it has a usable attack THIS turn that still reaches an enemy from up there
     — breath (an area attack) or a genuinely ranged attack.

Condition 4 keys off the engine's OWN range semantics, so the decision matches
what the flier can actually do in combat:
  - a Dragon on a breath-available turn → kite (breath reaches the ground);
    on a breath-down turn its only options are melee → grounds → it SWOOPS;
  - a Wyvern (bite/sting only) → never any airborne offense → always grounds;
  - a Manticore → grounds too (its tail spike is engine-treated as 5-ft reach;
    the `range: [n,m]` attack format isn't parsed as ranged — a pre-existing
    bug, tracked separately — so it has no working airborne attack anyway).

The kited flier denies grounded melee (the Fighter) but is still hittable by
ranged PCs (the Wizard) — which is exactly the gap PC Fly (Stage 3) fills.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

# Below this optimization dial, fliers fight grounded (the WoTC-baseline,
# deliberately-under-optimized monster). At or above it, they kite. Mirrors the
# AoE-chase gate — kiting is an OPTIMIZATION, not a stat.
KITE_MIN_DIAL = 3

# Hover one square (5 ft) above the tallest grounded melee reach, so the
# Chebyshev-3D gap strictly exceeds that reach.
HOVER_MARGIN_FT = 5


def has_fly(actor: Actor) -> bool:
    return int((getattr(actor, "speed", None) or {}).get("fly", 0)) > 0


def safe_hover_elevation(actor: Actor, state: CombatState) -> int:
    """Lowest elevation (ft) that clears every GROUNDED enemy's melee reach, so
    grounded melee can't retaliate. 0 if there are no grounded melee enemies to
    deny (kiting would gain nothing)."""
    from engine.ai.positioning import _enemy_melee_reach_ft
    reaches = [_enemy_melee_reach_ft(e) for e in state.encounter.actors
               if e.is_alive() and e.side != actor.side and not has_fly(e)]
    if not reaches:
        return 0
    return max(reaches) + HOVER_MARGIN_FT


def best_airborne_offense_ehp(actor: Actor, elev: int,
                              state: CombatState) -> float:
    """Best offensive eHP `actor` could deliver from its current (x, y) at
    `elev`, this turn — using the engine's own reach/range + recharge rules, so
    it matches what the flier can actually execute. Melee actions fall away
    automatically: at `elev` the Chebyshev-3D distance to a grounded enemy
    exceeds a melee reach, so those candidates score nothing.

    Temporarily sets `actor.elevation` and restores it (pure aside from that)."""
    from engine.core import recharge
    from engine.core.geometry import distance_ft
    from engine.core.pipeline import _action_reach_ft, _multiattack_max_reach
    from engine.ai.positioning import max_aoe_coverage
    from engine.ai.ehp_scoring import (
        offensive_ehp_single_attack, offensive_ehp_multiattack,
        offensive_ehp_save_attack,
    )
    enemies = [e for e in state.encounter.actors
               if e.is_alive() and e.side != actor.side]
    if not enemies:
        return 0.0
    saved = actor.elevation
    actor.elevation = elev
    try:
        best = 0.0
        for action in (actor.template.get("actions") or []):
            if not recharge.is_available(actor, action):
                continue
            kind = action.get("type")
            if kind == "aoe_attack" or action.get("area"):
                cov = max_aoe_coverage(action, actor, state)
                if cov is not None:
                    best = max(best, cov["ehp"])
                continue
            if kind == "weapon_attack":
                reach = _action_reach_ft(action)
            elif kind == "multiattack":
                reach = _multiattack_max_reach(action, actor.template)
            elif kind == "save_attack":
                reach = int(action.get("range_ft", 60))
            else:
                continue
            for e in enemies:
                if distance_ft(actor, e) > reach:   # 3-D: airborne ⇒ no melee
                    continue
                if kind == "weapon_attack":
                    v = offensive_ehp_single_attack(actor, e, action, state)
                elif kind == "multiattack":
                    v = offensive_ehp_multiattack(actor, e, action, state)
                else:
                    v = offensive_ehp_save_attack(actor, e, action, state)
                best = max(best, v)
        return best
    finally:
        actor.elevation = saved


def choose_flier_elevation(actor: Actor, state: CombatState) -> int:
    """The elevation (ft) this flier should occupy this turn: a safe hover when
    kiting is warranted, else 0 (grounded). See the module docstring for the
    four gates. Returns the actor's CURRENT elevation when not a kiter so the
    caller can treat the return as the authoritative target."""
    from engine.core.optimization_dial import dial_for
    if not has_fly(actor):
        return 0
    if dial_for(actor, state) < KITE_MIN_DIAL:
        return 0
    hover = safe_hover_elevation(actor, state)
    if hover <= 0:
        return 0                       # no grounded melee to deny
    if best_airborne_offense_ehp(actor, hover, state) > 0:
        return hover                   # has working airborne offense → kite
    return 0                           # nothing to do up there → ground (swoop)
