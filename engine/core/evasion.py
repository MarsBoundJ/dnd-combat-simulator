"""Evasion — shared DEX-save-for-half damage substrate.

RAW (PHB 2024 Evasion, Rogue/Monk L7): "When you're subjected to an effect
that allows you to make a Dexterity saving throw to take only half damage,
you instead take no damage if you succeed on the save and only half damage
if you fail. You don't benefit from this feature if you have the
Incapacitated condition."

College of Dance Leading Evasion (Bard L14) is the same core mechanic PLUS:
"If any creatures within 5 feet of you are making the same Dexterity saving
throw, you can share this benefit with them for that save."

Modeling: a hook in primitives._forced_save at the on_fail/on_success branch.
A "save for half" effect is a forced_save whose on_fail deals full damage and
on_success deals half (multiplier 0.5). For a creature with Evasion making the
DEX save:
  - success → take NO damage (scale the on_success damage by 0.0)
  - fail    → take HALF damage (scale the on_fail damage by 0.5)
Non-damage sub-primitives (conditions) are preserved — Evasion only changes
the damage.

Wired features: f_evasion (Rogue/Monk L7), f_leading_evasion (Dance L14).
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

_EVASION_FEATURES = ("f_evasion", "f_leading_evasion")


def _is_dex(ability: str) -> bool:
    return ability in ("dexterity", "dex")


def _has_feature(actor: Actor, feature_id: str) -> bool:
    return feature_id in ((actor.template or {}).get("features_known") or [])


def _is_incapacitated(actor: Actor) -> bool:
    return any(c.get("condition_id") == "co_incapacitated"
               for c in actor.applied_conditions)


def has_evasion(actor: Actor, state: CombatState | None = None) -> bool:
    """True if `actor` benefits from Evasion on a DEX save: it has Evasion /
    Leading Evasion itself, OR (Leading Evasion sharing) an ally within 5 ft
    has Leading Evasion. Incapacitated creatures don't benefit (RAW)."""
    if _is_incapacitated(actor):
        return False
    if any(_has_feature(actor, f) for f in _EVASION_FEATURES):
        return True
    # Leading Evasion sharing: an ally within 5 ft extends the benefit.
    if state is not None:
        from engine.core.geometry import distance_ft
        for a in state.encounter.actors:
            if a.id == actor.id or a.side != actor.side or not a.is_alive():
                continue
            if _is_incapacitated(a):
                continue
            if (_has_feature(a, "f_leading_evasion")
                    and distance_ft(a.position, actor.position) <= 5):
                return True
    return False


def _list_has_damage(subs) -> bool:
    return any(s.get("primitive") == "damage" for s in (subs or []))


def _scale_damage(subs: list, factor: float) -> list:
    """Return a copy of `subs` with each damage sub-primitive's multiplier
    scaled by `factor` (non-damage subs pass through unchanged)."""
    out = []
    for s in (subs or []):
        if s.get("primitive") == "damage":
            s2 = dict(s)
            p = dict(s2.get("params") or {})
            p["multiplier"] = float(p.get("multiplier", 1.0)) * factor
            s2["params"] = p
            out.append(s2)
        else:
            out.append(dict(s))
    return out


def select_evasion_subs(target: Actor, ability: str, outcome: str,
                          params: dict, state: CombatState | None) -> list | None:
    """If Evasion applies to this forced-save outcome for `target`, return the
    (damage-scaled) sub-primitive list to invoke; otherwise None (caller uses
    the normal on_fail/on_success).

    Applies only to a DEX save vs a "save for half" effect — one whose on_fail
    AND on_success both deal damage. success → scale on_success damage to 0;
    fail → scale on_fail damage to half."""
    if not _is_dex(ability):
        return None
    if not has_evasion(target, state):
        return None
    return _half_save_subs(outcome, params)


def has_avoidance(actor: Actor) -> bool:
    """True if `actor` benefits from the Avoidance trait (Displacer Beast,
    MM 2024) — Evasion for ANY save ability. Suppressed while Incapacitated,
    mirroring base Evasion (RAW Avoidance has no incapacitation clause, but we
    apply the same suppression for consistency with the Evasion substrate)."""
    from engine.core.monster_traits import has_trait
    if _is_incapacitated(actor):
        return False
    return has_trait(actor, "t_avoidance")


def select_avoidance_subs(target: Actor, ability: str, outcome: str,
                            params: dict, state: CombatState | None) -> list | None:
    """Avoidance twin of select_evasion_subs. Same "save for half" → 0/half
    transform, but for ANY saving throw ability (not just DEX), gated on the
    t_avoidance trait. Returns the damage-scaled sub list or None."""
    if not has_avoidance(target):
        return None
    return _half_save_subs(outcome, params)


def _half_save_subs(outcome: str, params: dict) -> list | None:
    """Shared Evasion/Avoidance transform: only a "save for half" effect
    (on_fail AND on_success both deal damage) qualifies. success → 0 damage,
    fail → half damage. None when the effect isn't save-for-half."""
    on_success = params.get("on_success") or []
    on_fail = params.get("on_fail") or []
    if not (_list_has_damage(on_success) and _list_has_damage(on_fail)):
        return None   # not a "half damage" effect — doesn't apply
    if outcome == "success":
        return _scale_damage(on_success, 0.0)   # take no damage
    return _scale_damage(on_fail, 0.5)           # fail → take half
