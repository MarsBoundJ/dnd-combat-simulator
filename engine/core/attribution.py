"""Shapley-value eHP attribution — credit flows to the CAUSE, not the executor.

The red-team consensus (docs/red_team_obstacle_course_prompt.md + addendum):
a naive ledger credits the Fighter with damage that the Wizard's Web (advantage)
and the Cleric's Bless (+2 to hit) created. Summing per-actor eHP then
double-counts, and the "closed financial system" property — per-actor credits
sum EXACTLY to realized damage — is lost. The fix all three reviewers converged
on is per-roll Shapley attribution:

  - The ATTACKER is credited with the attack's baseline expected value
    (no temporary modifiers — their own to-hit vs the target's own AC).
  - Each temporary modifier (advantage from a condition, an attack-bonus buff,
    an AC debuff) is a CONTRIBUTOR credited with its exact Shapley share of
    the surplus: its marginal lift averaged over every join order. Shapley is
    order-independent, gives equal effects equal credit (symmetry), gives
    no-op effects zero (dummy), and sums exactly to the full surplus
    (efficiency).
  - Realized damage is then split proportionally to those expected-value
    shares, so the credited amounts sum exactly to the damage that actually
    happened (a miss attributes nothing — the buff lifted a probability that
    didn't cash out).

Exactness is tractable because a 5e attack roll rarely carries more than
2-3 attributable effects (advantage + Bless + an AC debuff); contributors are
grouped per SOURCE CREATURE first, so n is bounded by party size in the worst
imaginable stack.

v1 scope (documented limits):
  - Attack rolls + save-gated damage (forced_save on_fail/on_success damage,
    including persistent-aura ticks, which route through forced_save).
    Bardic-Inspiration post-roll die spends, control-denial attribution
    (crediting a save-debuffer for the stun it enabled), and defensive
    attribution (Shield's negative surplus belongs to the defender's
    defensive ledger) are deferred.
  - The value function works in normalized units (attack: mean on-hit damage
    = 1.0 with a crit-extra ratio folded in; save: mean on-FAIL damage = 1.0
    with a success-ratio for save-for-half), so shares are computed once per
    damage step and scaled by the step's realized amount.
"""
from __future__ import annotations

import re
from itertools import combinations
from math import factorial

# Above this many distinct contributing creatures we refuse exact enumeration
# (2^n subsets) and fold the smallest contributors into the baseline. In real
# 5e play n is 1-3; this is a safety rail, not an expected path.
MAX_EXACT_CONTRIBUTORS = 8


# ============================================================================
# d20 probability math
# ============================================================================

def _p_single(needed: int) -> float:
    """P(one d20 >= needed), honoring nat-1 auto-miss / nat-20 auto-hit:
    the effective threshold is clamped to [2, 20]."""
    needed = max(2, min(20, needed))
    return (21 - needed) / 20.0


def hit_probability(needed: int, advantage: str = "normal") -> float:
    """P(attack hits) given the to-hit threshold (target AC - attack bonus)
    and the net advantage state ('normal' | 'advantage' | 'disadvantage')."""
    p = _p_single(needed)
    if advantage == "advantage":
        return 1.0 - (1.0 - p) ** 2
    if advantage == "disadvantage":
        return p * p
    return p


def crit_probability(crit_threshold: int = 20,
                     advantage: str = "normal") -> float:
    """P(natural roll >= crit threshold) under the advantage state."""
    p = _p_single(crit_threshold)
    if advantage == "advantage":
        return 1.0 - (1.0 - p) ** 2
    if advantage == "disadvantage":
        return p * p
    return p


def dice_mean(dice: str | None) -> float:
    """Mean of a dice expression like '2d6' / '1d10' / '4d6'. 0 for blank."""
    if not dice:
        return 0.0
    m = re.fullmatch(r"\s*(\d+)d(\d+)\s*", str(dice))
    if not m:
        return 0.0
    n, faces = int(m.group(1)), int(m.group(2))
    return n * (faces + 1) / 2.0


# ============================================================================
# The value function: expected attack damage (normalized) for a subset of
# contributing effects
# ============================================================================

def _net_advantage(base_adv: int, base_dis: int, effects: list[dict]) -> str:
    """5e: any advantage + any disadvantage cancel to normal."""
    adv = base_adv + sum(1 for e in effects if e["kind"] == "advantage")
    dis = base_dis + sum(1 for e in effects if e["kind"] == "disadvantage")
    if adv and dis:
        return "normal"
    if adv:
        return "advantage"
    if dis:
        return "disadvantage"
    return "normal"


def expected_attack_value(base_bonus: int, base_ac: int,
                          effects: list[dict],
                          crit_threshold: int = 20,
                          crit_extra_ratio: float = 0.0,
                          base_advantage: int = 0,
                          base_disadvantage: int = 0) -> float:
    """Expected damage of the attack in units of mean-on-hit damage, with the
    given temporary `effects` active. Effects are contribution dicts:
        {"kind": "advantage"|"disadvantage"|"attack_bonus"|"ac_modifier",
         "value": int}
    `crit_extra_ratio` = (mean extra crit damage) / (mean on-hit damage) —
    the crit's bonus dice as a fraction of a normal hit."""
    bonus = base_bonus + sum(e.get("value", 0) for e in effects
                             if e["kind"] == "attack_bonus")
    ac = base_ac + sum(e.get("value", 0) for e in effects
                       if e["kind"] == "ac_modifier")
    adv = _net_advantage(base_advantage, base_disadvantage, effects)
    p_hit = hit_probability(ac - bonus, adv)
    p_crit = min(crit_probability(crit_threshold, adv), p_hit)
    return p_hit + p_crit * crit_extra_ratio


# ============================================================================
# The save-side value function: expected save-gated damage (normalized)
# ============================================================================

def save_success_probability(needed: int, advantage: str = "normal") -> float:
    """P(save succeeds) given the threshold (DC - total save bonus) and the
    net advantage state. NO nat-1/nat-20 clamp — saves in 5e (and in
    _forced_save's execution) have no auto-fail/auto-succeed faces."""
    if needed <= 1:
        p = 1.0
    elif needed > 20:
        p = 0.0
    else:
        p = (21 - needed) / 20.0
    if advantage == "advantage":
        return 1.0 - (1.0 - p) ** 2
    if advantage == "disadvantage":
        return p * p
    return p


def _net_save_advantage(effects: list[dict]) -> str:
    adv = sum(1 for e in effects if e["kind"] == "save_advantage")
    dis = sum(1 for e in effects if e["kind"] == "save_disadvantage")
    if adv and dis:
        return "normal"
    if adv:
        return "advantage"
    if dis:
        return "disadvantage"
    return "normal"


def expected_save_value(dc: int, save_bonus: int, effects: list[dict],
                        success_ratio: float = 0.0) -> float:
    """Expected damage of a save-gated effect in units of mean ON-FAIL
    damage, with the given temporary `effects` active. Effect kinds:
        {"kind": "save_advantage"|"save_disadvantage"|"save_bonus"|
                 "save_auto_fail"|"save_auto_succeed", "value": int}
    `success_ratio` = (mean on-success damage) / (mean on-fail damage) —
    0.5 for save-for-half spells, 0.0 for full negates.

    Note the sign convention: effects that HELP the target's save (advantage,
    +save_bonus) LOWER this value — their Shapley shares come out negative,
    which the offense ledger ignores (defensive attribution is the v2 lane).
    """
    if any(e["kind"] == "save_auto_fail" for e in effects):
        # auto-fail trumps auto-succeed (mirrors net_outcome_override)
        p_success = 0.0
    elif any(e["kind"] == "save_auto_succeed" for e in effects):
        p_success = 1.0
    else:
        bonus = save_bonus + sum(e.get("value", 0) for e in effects
                                 if e["kind"] == "save_bonus")
        adv = _net_save_advantage(effects)
        p_success = save_success_probability(dc - bonus, adv)
    return (1.0 - p_success) + p_success * success_ratio


# ============================================================================
# Exact Shapley over grouped contributors
# ============================================================================

def shapley_shares(contributors: list[dict], value_fn) -> tuple[float, list[float]]:
    """Exact Shapley values. `contributors` is a list of composite
    contributors (each with an "effects" list); `value_fn(effects)` maps a
    flat effect list to the coalition's value. Returns
    (baseline, [phi_0, ..., phi_{n-1}]) with the efficiency property:
        baseline + sum(phi) == value_fn(all effects)   (exactly)
    """
    n = len(contributors)
    cache: dict[frozenset, float] = {}

    def v(s: frozenset) -> float:
        if s not in cache:
            effects = [eff for i in sorted(s)
                       for eff in contributors[i]["effects"]]
            cache[s] = value_fn(effects)
        return cache[s]

    baseline = v(frozenset())
    if n == 0:
        return baseline, []
    phis = []
    for i in range(n):
        others = [j for j in range(n) if j != i]
        phi = 0.0
        for r in range(n):
            w = factorial(r) * factorial(n - r - 1) / factorial(n)
            for combo in combinations(others, r):
                s = frozenset(combo)
                phi += w * (v(s | {i}) - v(s))
        phis.append(phi)
    return baseline, phis


# ============================================================================
# Contribution grouping — one composite contributor per source creature
# ============================================================================

def _source_creature_id(source: dict) -> str | None:
    """The creature a modifier's credit flows to. Condition-sourced modifiers
    carry source_creature_id (who applied the Web); action buffs carry
    caster_id (who cast the Bless)."""
    return source.get("source_creature_id") or source.get("caster_id")


def _source_label(source: dict) -> str:
    return (source.get("named_effect") or source.get("condition_id")
            or source.get("action_id") or source.get("type") or "unknown")


def group_contributions(contributions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split raw per-modifier contributions into:
      - contributors: one composite per source CREATURE (its credit unit) —
        all of one creature's effects rise and fall together, so a creature's
        share covers everything it contributed to the roll;
      - ambient: effects with no attributable creature (terrain-ish) — they
        stay in the baseline environment (always active, credited to no one).
    """
    by_creature: dict[str, dict] = {}
    ambient: list[dict] = []
    for c in contributions:
        src = c.get("source") or {}
        cid = _source_creature_id(src)
        if not cid:
            ambient.append(c)
            continue
        comp = by_creature.setdefault(
            cid, {"source_id": cid, "labels": [], "effects": []})
        comp["effects"].append(c)
        label = _source_label(src)
        if label not in comp["labels"]:
            comp["labels"].append(label)
    return list(by_creature.values()), ambient


# ============================================================================
# Attack-roll context + realized-damage attribution (engine integration API)
# ============================================================================

def build_attack_context(contributions: list[dict], *, base_bonus: int,
                         base_ac: int, crit_threshold: int,
                         attacker_id: str) -> dict | None:
    """Snapshot everything the damage step needs to attribute its realized
    amount. Called by _attack_roll once modifiers are final. Returns None when
    no creature-attributable contribution touched the roll (the common case —
    a plain attack costs nothing)."""
    contributors, ambient = group_contributions(contributions or [])
    if not contributors:
        return None
    # Safety rail: beyond exact-enumeration size, fold the extra contributors
    # (rarest case imaginable) into the ambient baseline rather than exploding.
    if len(contributors) > MAX_EXACT_CONTRIBUTORS:
        for extra in contributors[MAX_EXACT_CONTRIBUTORS:]:
            ambient.extend(extra["effects"])
        contributors = contributors[:MAX_EXACT_CONTRIBUTORS]
    return {
        "attacker_id": attacker_id,
        "contributors": contributors,
        "ambient": ambient,
        "base_bonus": int(base_bonus),
        "base_ac": int(base_ac),
        "crit_threshold": int(crit_threshold),
    }


def _attribute_realized(ctx: dict, amount: float, value_fn,
                        model: str) -> dict | None:
    """Shared core: run Shapley over the ctx's contributors with `value_fn`,
    then scale the (baseline, shares) decomposition so it sums exactly to the
    realized `amount`."""
    baseline, phis = shapley_shares(ctx["contributors"], value_fn)
    total = baseline + sum(phis)
    if total <= 0:
        # Degenerate (can't-land-without-help edge): everything that landed is
        # surplus; split it across contributors by their (all-positive) phis,
        # or attribute nothing if even the full coalition is valueless.
        pos = sum(p for p in phis if p > 0)
        if pos <= 0:
            return None
        shares = [{"source_id": c["source_id"], "labels": c["labels"],
                   "amount": amount * max(p, 0.0) / pos}
                  for c, p in zip(ctx["contributors"], phis)]
        return {"model": model, "baseline": 0.0,
                "shares": [s for s in shares if s["amount"] > 0]}

    scale = amount / total
    shares = []
    for c, p in zip(ctx["contributors"], phis):
        shares.append({"source_id": c["source_id"], "labels": c["labels"],
                       "amount": p * scale})
    return {"model": model, "baseline": baseline * scale,
            "shares": shares}


def attribute_damage_event(ctx: dict, amount: float,
                           crit_extra_ratio: float = 0.0) -> dict | None:
    """Split one damage step's realized `amount` into the attacker's baseline
    share + per-contributor Shapley shares, scaled so they sum exactly to
    `amount`. Returns the attribution payload for the damage_dealt event:

        {"model": "shapley_v1",
         "baseline": <attacker's share>,
         "shares": [{"source_id", "labels", "amount"}, ...]}
    """
    if amount <= 0 or not ctx:
        return None
    ambient = ctx["ambient"]

    def value_fn(effects: list[dict]) -> float:
        return expected_attack_value(
            ctx["base_bonus"], ctx["base_ac"], ambient + effects,
            crit_threshold=ctx["crit_threshold"],
            crit_extra_ratio=crit_extra_ratio)

    return _attribute_realized(ctx, amount, value_fn, "shapley_v1")


# ============================================================================
# Save context + realized save-damage attribution (engine integration API)
# ============================================================================

def build_save_attribution_context(contributions: list[dict], *, dc: int,
                                   save_bonus: int, success_ratio: float,
                                   caster_id: str | None) -> dict | None:
    """Snapshot everything a save-gated damage step needs to attribute its
    realized amount. Called by _forced_save per target once save modifiers
    are final. `save_bonus` is the target's OWN bonus (ability save + cover);
    temporary save modifiers travel as contributions. Returns None when no
    creature-attributable contribution touched the save (the common case)."""
    contributors, ambient = group_contributions(contributions or [])
    if not contributors:
        return None
    if len(contributors) > MAX_EXACT_CONTRIBUTORS:
        for extra in contributors[MAX_EXACT_CONTRIBUTORS:]:
            ambient.extend(extra["effects"])
        contributors = contributors[:MAX_EXACT_CONTRIBUTORS]
    return {
        "caster_id": caster_id,
        "contributors": contributors,
        "ambient": ambient,
        "dc": int(dc),
        "save_bonus": int(save_bonus),
        "success_ratio": float(success_ratio),
    }


def attribute_save_damage_event(ctx: dict, amount: float) -> dict | None:
    """Split one save-gated damage step's realized `amount` into the caster's
    baseline share + per-contributor Shapley shares (e.g., the ally whose
    Restrained imposed disadvantage on the DEX save), scaled so they sum
    exactly to `amount`. Payload shape matches attribute_damage_event with
    model "shapley_save_v1"."""
    if amount <= 0 or not ctx:
        return None
    ambient = ctx["ambient"]

    def value_fn(effects: list[dict]) -> float:
        return expected_save_value(
            ctx["dc"], ctx["save_bonus"], ambient + effects,
            success_ratio=ctx["success_ratio"])

    return _attribute_realized(ctx, amount, value_fn, "shapley_save_v1")
