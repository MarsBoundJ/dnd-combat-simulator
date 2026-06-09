"""Rest cycle hooks (PR #37).

The engine simulates single encounters; there's no in-runner rest
cycle today. This module exposes the entry points that future multi-
encounter sim work will call between encounters, AND lets tests
invoke rest-cycle behavior directly (Arcane Recovery, Second Wind
short-rest partial refresh, etc.) without spinning up a fake runner.

**v1 scope (PRs #37, #40):**
  - `apply_short_rest(actor, state)` (PR #37) — entry point.
    Dispatches to per-class handlers based on
    `actor.template.derived_from_pc_schema.class`.
  - Wizard handler: Arcane Recovery. Restores expended spell slots
    via `slot_recovery_partial` primitive (budget = ceil(level/2),
    cap = 5th level). Decrements
    `actor.resources["arcane_recovery_uses_remaining"]`.
  - Fighter handler: Second Wind short-rest partial refresh.
    Restores +1 use of Second Wind (up to the level-table maximum)
    per RAW. Doesn't refresh Action Surge (that's also 1/short
    rest per RAW but only counted as a uses_remaining → we restore
    Action Surge too with +1 cap at the level-table max).
  - `apply_long_rest(actor, state)` (PR #40) — entry point.
    Universal restorations (all actors): HP to hp_max, all spell
    slots to spell_slots_max, end concentration (RAW: sleep ends
    it), expire `until_long_rest` modifiers. Per-class refresh for
    PCs: Fighter (Action Surge + Second Wind both to full),
    Wizard (Arcane Recovery → 1).
  - Non-PC-derived actors → universal restorations only (HP, slots,
    concentration, modifier expiry). No per-class refresh.

**Deferred:**
  - Data-driven per-feature dispatch — currently hard-coded per
    class. When more classes land we'll walk
    `class_def.level_table` for `f_*` features whose YAML defs
    declare a `usage.rest_recovery.short_rest` or `long_rest` hook.
  - Runner integration (multi-encounter session simulation calling
    apply_short_rest / apply_long_rest between encounters).
  - Exhaustion (-1 level on long rest, per 2024 PHB)
  - HP dice spent recovery (we don't track HP dice)
"""
from __future__ import annotations

import math

from engine.core.state import Actor, CombatState

# Between-encounter / short-rest HP recovery target. PCs heal up to NEAR max
# (not to max) using Hit Dice — topping the last few HP would spend a whole die
# for a few points and waste the overspill, which players don't do (Phil, 2026-
# 06-05). ~85% is the "heal up after the fight" resting point.
RECOVERY_TARGET_FRAC = 0.85


def apply_short_rest(actor: Actor, state: CombatState) -> dict:
    """Run all short-rest effects for `actor`. Returns a dict
    summarizing what fired, for logging / test inspection.

    The dict shape:
      {
        "arcane_recovery": {"restored": [{"level": L, "count": N}, ...]}
          # absent if not applicable
        "second_wind_refresh": {"added": N, "new_total": M}
          # absent if not applicable
        "action_surge_refresh": {"added": N, "new_total": M}
          # absent if not applicable
      }

    Logs a `short_rest_applied` event with the summary.
    """
    derived = actor.template.get("derived_from_pc_schema") or {}
    cls = derived.get("class")
    level = int(derived.get("level", 1))
    summary: dict = {}
    if cls == "c_wizard":
        result = _apply_arcane_recovery(actor, level, state)
        if result is not None:
            summary["arcane_recovery"] = result
    if cls == "c_fighter":
        sw = _apply_second_wind_short_rest_refresh(actor, level, state)
        if sw is not None:
            summary["second_wind_refresh"] = sw
        # RAW (PHB 2024): Action Surge is also 1/short rest at L2-16,
        # 2/short rest at L17+. Short rest fully refreshes it.
        asg = _apply_action_surge_short_rest_refresh(actor, level, state)
        if asg is not None:
            summary["action_surge_refresh"] = asg
    # PR #101: Warlock Pact Magic — slots recover on a SHORT rest
    # (the Warlock's signature short-rest economy). Restore
    # spell_slots to spell_slots_max. Gated on c_warlock: every other
    # caster's slots are long-rest only, so we must NOT blanket-
    # restore spell_slots for non-Warlocks here.
    # NOTE: single-class assumption — a pure Warlock's slots are ALL
    # pact slots. A future Warlock multiclass would have a mix of
    # pact (short-rest) + standard (long-rest) slots that this
    # blanket restore would over-recover; documented for the
    # multiclass PR. The f_pact_magic feature presence is the
    # forward-looking gate if class-dispatch is ever insufficient.
    if cls == "c_warlock":
        pact = _apply_pact_magic_short_rest_refresh(actor, state)
        if pact is not None:
            summary["pact_magic_refresh"] = pact
    # Font of Inspiration (Bard L5+): Bardic Inspiration uses also refresh on
    # a SHORT rest (RAW: "regain all your expended uses... Short or Long
    # Rest"). Gated on the feature so a level 1-4 Bard only refreshes BI on a
    # Long Rest.
    if cls == "c_bard" and "f_font_of_inspiration" in (
            actor.template.get("features_known") or []):
        bi_result = _refresh_generic_uses_to_max(
            actor, "bardic_inspiration_uses_remaining",
            "bardic_inspiration_uses_max")
        if bi_result is not None:
            summary["bardic_inspiration_refresh"] = bi_result
    # A short rest also recovers a downed (dying/stable) PC — stabilize + wake
    # so it doesn't carry the death-save clock into the next fight.
    if _recover_downed(actor, state):
        summary["recovered_downed"] = True
    # Hit-Dice HP recovery: spend Hit Dice to heal up to ~85% of max (not to
    # max — don't waste dice topping the last few HP). No-op for monsters
    # (hit_dice_remaining == 0) and for actors already at/above the target.
    hd = _apply_hit_dice_heal(actor)
    if hd is not None:
        summary["hit_dice"] = hd
    state.event_log.append({
        "event": "short_rest_applied",
        "actor": actor.id,
        "summary": summary,
    })
    return summary


def _hit_die_size(actor: Actor) -> int:
    """The class hit-die size (e.g. 6 for d6). Parsed from the template's
    combat.hit_points.dice ('NdX'), with a core_traits.hit_die fallback."""
    dice = ((actor.template.get("combat") or {}).get("hit_points") or {}).get("dice", "")
    if "d" in str(dice):
        try:
            return int(str(dice).split("d")[1])
        except (ValueError, IndexError):
            pass
    hd = (actor.template.get("core_traits") or {}).get("hit_die", "d8")
    try:
        return int(str(hd).lstrip("d"))
    except ValueError:
        return 8


def _con_modifier(actor: Actor) -> int:
    score = int((actor.abilities.get("con") or {}).get("score", 10))
    return (score - 10) // 2


def _apply_hit_dice_heal(actor: Actor) -> dict | None:
    """Spend Hit Dice to heal `actor` up to NEAR max (RECOVERY_TARGET_FRAC of
    hp_max), not all the way to max. Each die restores avg(die) + CON mod (5e
    average-HP rounding: d6→4, d8→5, d10→6, d12→7). Spends dice until current
    HP reaches the ~85% target (the crossing die may overspill a little, capped
    at max), so PCs heal up after the fight without burning whole dice for the
    last few HP to max. Capped by the pool. Returns a {spent, healed,
    remaining} summary, or None if nothing to do."""
    if actor.is_dead:
        return None   # the dead don't heal (Raise Dead etc. not modeled)
    hd = int(getattr(actor, "hit_dice_remaining", 0))
    target = int(actor.hp_max * RECOVERY_TARGET_FRAC)
    if hd <= 0 or actor.hp_current >= target:
        return None
    heal_per = max(1, _hit_die_size(actor) // 2 + 1 + _con_modifier(actor))
    healed = 0
    spent = 0
    while spent < hd and actor.hp_current < target:
        gain = min(heal_per, actor.hp_max - actor.hp_current)   # never past max
        if gain <= 0:
            break
        actor.hp_current += gain
        healed += gain
        spent += 1
    actor.hit_dice_remaining = hd - spent
    if spent == 0:
        return None
    return {"spent": spent, "healed": healed,
            "remaining": actor.hit_dice_remaining}


def _recover_downed(actor: Actor, state: CombatState) -> bool:
    """Between-encounter: a DYING / STABLE (not-dead) PC stabilizes and comes
    round once combat is over — the death-save clock is cleared so it does NOT
    carry into the next fight and die on its first death save. The actor stays
    at 0 HP here; the Hit-Dice heal that follows climbs it back up (no Hit Dice
    left → it stays down at 0, a real consequence). No-op for conscious or
    truly-dead actors. Returns True if it recovered a downed actor."""
    if actor.is_dead:
        return False
    if not (getattr(actor, "is_dying", False)
            or getattr(actor, "is_stable", False)):
        return False
    actor.is_dying = False
    actor.is_stable = False
    actor.death_save_successes = 0
    actor.death_save_failures = 0
    state.event_log.append({"event": "recovered_downed", "actor": actor.id})
    return True


def apply_between_encounter_recovery(actor: Actor, state: CombatState) -> dict:
    """Post-combat recovery applied after EVERY encounter (RAW play behavior:
    PCs heal up near max between fights whether or not they take a formal short
    rest — Phil, 2026-06-05). Two parts:
      1. stabilize + wake a downed (dying/stable) PC (clears the death-save
         clock so it doesn't carry into the next fight),
      2. spend Hit Dice to heal up to ~85% of max (downed PCs climb off 0).
    No short-rest RESOURCE recharge here (Second Wind / Action Surge / Arcane
    Recovery / Pact Magic) — that only happens on a designated short rest. No-op
    for truly-dead or monster actors. Logs `between_encounter_recovery`.

    Deferred: out-of-combat healing via SPELLS / Lay on Hands / potions (which
    real parties also use to top up); v1 uses Hit Dice — the canonical
    short-rest heal — which captures the core "heal up between fights" effect.
    """
    summary: dict = {}
    if _recover_downed(actor, state):
        summary["recovered_downed"] = True
    hd = _apply_hit_dice_heal(actor)
    if hd is not None:
        summary["hit_dice"] = hd
    if summary:
        state.event_log.append({
            "event": "between_encounter_recovery",
            "actor": actor.id,
            "summary": summary,
        })
    return summary


# ============================================================================
# Long rest — universal restorations + per-class refresh
# ============================================================================

def apply_long_rest(actor: Actor, state: CombatState) -> dict:
    """Run all long-rest effects for `actor`. Returns a summary dict
    of what fired. Logs a `long_rest_applied` event.

    Universal effects (all actors, PC or not):
      - HP restored to hp_max
      - All spell slots restored to spell_slots_max
      - Concentration ended (RAW: 8 hours of sleep ends concentration)
      - Modifiers with lifetime `until_long_rest` expire
    Per-class refresh (PCs only, dispatch on derived_from_pc_schema.class):
      - Fighter: Second Wind to level-table max, Action Surge to
        L2/L17 max
      - Wizard: Arcane Recovery → 1

    Long rest is broader than short rest by design — they're separate
    code paths rather than one calling the other, because the per-
    feature recovery cadence differs (Second Wind: +1 on short, full
    on long; Action Surge: full on either; Arcane Recovery: only
    refreshes on long rest).

    Summary shape:
      {
        "hp_restored": int (delta from current to max),
        "slots_restored": {level: count, ...},
        "concentration_ended": bool,
        "modifiers_expired": int,
        "action_surge_refresh": {"new_total": N}  # PC fighter only
        "second_wind_refresh": {"new_total": N}    # PC fighter only
        "arcane_recovery_refresh": {"new_total": 1}  # PC wizard only
      }
    """
    from engine.core.concentration import end_concentration
    from engine.core import modifiers
    summary: dict = {}

    # ---- Universal: max-HP bonuses expire (PR #97) ----
    # Aid-style hp_max raises end at long rest (RAW: they have a
    # duration of 8 hours / until the spell ends; a long rest is the
    # cleanup point in the sim's session model). Done BEFORE the HP
    # restore so hp_max is back to its base before we set current =
    # max. Without this ordering, the Aid bonus would silently become
    # permanent (current=boosted-max persists, ledger never cleared).
    if actor.hp_max_bonuses:
        total_bonus = sum(int(e.get("amount", 0))
                            for e in actor.hp_max_bonuses)
        actor.hp_max_bonuses = []
        if total_bonus > 0:
            actor.hp_max = max(1, actor.hp_max - total_bonus)
            summary["hp_max_bonus_cleared"] = total_bonus
        # hp_current is reset to hp_max in the next block, so no
        # explicit cap needed here.

    # ---- Universal: HP restore ----
    hp_before = int(actor.hp_current)
    actor.hp_current = int(actor.hp_max)
    if actor.hp_current > hp_before:
        summary["hp_restored"] = actor.hp_current - hp_before

    # ---- Universal: Hit Dice regain (RAW: half your total, min 1) ----
    if actor.hit_dice_max > 0 and actor.hit_dice_remaining < actor.hit_dice_max:
        regain = max(1, actor.hit_dice_max // 2)
        before = actor.hit_dice_remaining
        actor.hit_dice_remaining = min(actor.hit_dice_max, before + regain)
        if actor.hit_dice_remaining > before:
            summary["hit_dice_regained"] = actor.hit_dice_remaining - before

    # ---- Universal: temp HP cleared (PR #94) ----
    # RAW PHB 2024 p.244: "Any temporary Hit Points you have are
    # also lost when you take a Long Rest."
    if actor.temp_hp > 0:
        summary["temp_hp_cleared"] = actor.temp_hp
        actor.temp_hp = 0

    # ---- Universal: spell slots restore ----
    slots_restored: dict = {}
    for lvl, max_at in actor.spell_slots_max.items():
        cur = int(actor.spell_slots.get(lvl, 0))
        max_int = int(max_at)
        if cur < max_int:
            slots_restored[int(lvl)] = max_int - cur
            actor.spell_slots[lvl] = max_int
    if slots_restored:
        summary["slots_restored"] = slots_restored

    # ---- Universal: concentration ends (RAW: sleep breaks it) ----
    if actor.concentration_on is not None:
        end_concentration(actor, state, reason="long_rest")
        summary["concentration_ended"] = True

    # ---- Universal: until_long_rest modifiers expire ----
    expired = modifiers.expire_modifiers(actor, {"long_rest_end"})
    if expired > 0:
        summary["modifiers_expired"] = expired

    # ---- Per-class refresh ----
    derived = actor.template.get("derived_from_pc_schema") or {}
    cls = derived.get("class")
    level = int(derived.get("level", 1))
    if cls == "c_fighter":
        as_result = _refresh_action_surge_to_max(actor, level)
        if as_result is not None:
            summary["action_surge_refresh"] = as_result
        sw_result = _refresh_second_wind_to_max(actor, level)
        if sw_result is not None:
            summary["second_wind_refresh"] = sw_result
    if cls == "c_wizard":
        ar_result = _refresh_arcane_recovery(actor)
        if ar_result is not None:
            summary["arcane_recovery_refresh"] = ar_result
    if cls == "c_barbarian":
        # PR #71: Rage uses fully refresh on long rest. The level-
        # table max is stamped onto resources as `rage_uses_max` by
        # derive_pc_resources, so we don't need to re-walk the class
        # def here.
        rage_result = _refresh_rage_uses_to_max(actor)
        if rage_result is not None:
            summary["rage_uses_refresh"] = rage_result
        # Warrior of the Gods (Zealot L3): the d12 self-heal pool fully
        # refreshes on a Long Rest to the level-based max stamped by
        # derive_pc_resources. No-op for non-Zealot Barbarians.
        wotg_result = _refresh_warrior_of_the_gods_pool_to_max(actor)
        if wotg_result is not None:
            summary["warrior_of_the_gods_pool_refresh"] = wotg_result
        # Zealous Presence (Zealot L10): 1/long rest.
        zp_result = _refresh_generic_uses_to_max(
            actor, "zealous_presence_uses_remaining",
            "zealous_presence_uses_max")
        if zp_result is not None:
            summary["zealous_presence_refresh"] = zp_result
        # Rage of the Gods (Zealot L14): 1/long rest.
        rotg_result = _refresh_generic_uses_to_max(
            actor, "rage_of_the_gods_uses_remaining",
            "rage_of_the_gods_uses_max")
        if rotg_result is not None:
            summary["rage_of_the_gods_refresh"] = rotg_result
    if cls == "c_paladin":
        # PR #83: Lay on Hands pool fully refreshes on long rest.
        # The max is stamped onto resources as
        # `lay_on_hands_pool_max` by derive_pc_resources.
        loh_result = _refresh_lay_on_hands_pool_to_max(actor)
        if loh_result is not None:
            summary["lay_on_hands_pool_refresh"] = loh_result
    if cls == "c_bard":
        # Bardic Inspiration uses fully refresh on a Long Rest (RAW L1+).
        bi_result = _refresh_generic_uses_to_max(
            actor, "bardic_inspiration_uses_remaining",
            "bardic_inspiration_uses_max")
        if bi_result is not None:
            summary["bardic_inspiration_refresh"] = bi_result

    state.event_log.append({
        "event": "long_rest_applied",
        "actor": actor.id,
        "summary": summary,
    })
    return summary


def _refresh_action_surge_to_max(actor: Actor,
                                    level: int) -> dict | None:
    """Long rest fully refreshes Action Surge. 1 use at L2-16, 2 at L17+."""
    if level < 2:
        return None
    max_uses = 2 if level >= 17 else 1
    cur = int(actor.resources.get("action_surge_uses_remaining", 0))
    if cur >= max_uses:
        return None
    actor.resources["action_surge_uses_remaining"] = max_uses
    return {"new_total": max_uses}


def _refresh_second_wind_to_max(actor: Actor,
                                   level: int) -> dict | None:
    """Long rest fully refreshes Second Wind to the level-table max."""
    max_uses = _fighter_second_wind_max_at_level(level)
    if max_uses == 0:
        return None
    cur = int(actor.resources.get("second_wind_uses_remaining", 0))
    if cur >= max_uses:
        return None
    actor.resources["second_wind_uses_remaining"] = max_uses
    return {"new_total": max_uses}


def _refresh_lay_on_hands_pool_to_max(actor: Actor) -> dict | None:
    """Long rest fully restores the Paladin's Lay on Hands pool to
    the level-table max stamped on
    `actor.resources["lay_on_hands_pool_max"]` by
    pc_schema.derive_pc_resources (PR #83). Returns None when the
    actor has no pool_max declared (non-Paladin or fixture without
    the resource pair)."""
    max_pool = int(actor.resources.get("lay_on_hands_pool_max", 0))
    if max_pool <= 0:
        return None
    cur = int(actor.resources.get("lay_on_hands_pool_remaining", 0))
    if cur >= max_pool:
        return None
    actor.resources["lay_on_hands_pool_remaining"] = max_pool
    return {"new_total": max_pool}


def _refresh_generic_uses_to_max(actor: Actor, remaining_key: str,
                                    max_key: str) -> dict | None:
    """Generic long-rest refresh for any feature whose uses are tracked as
    `remaining_key` / `max_key` in `actor.resources`. Returns a result dict
    on refresh (for the summary), or None when not applicable / already full."""
    max_uses = int(actor.resources.get(max_key, 0))
    if max_uses <= 0:
        return None
    cur = int(actor.resources.get(remaining_key, 0))
    if cur >= max_uses:
        return None
    actor.resources[remaining_key] = max_uses
    return {"new_total": max_uses}


def _refresh_warrior_of_the_gods_pool_to_max(actor: Actor) -> dict | None:
    """Long rest fully restores the Zealot's Warrior of the Gods d12
    pool to the level-based max stamped on
    `actor.resources["warrior_of_the_gods_dice_max"]` by
    pc_schema.derive_pc_resources. Returns None when the actor has no
    pool declared (non-Zealot Barbarian or fixture without the pair)."""
    max_dice = int(actor.resources.get("warrior_of_the_gods_dice_max", 0))
    if max_dice <= 0:
        return None
    cur = int(actor.resources.get("warrior_of_the_gods_dice_remaining", 0))
    if cur >= max_dice:
        return None
    actor.resources["warrior_of_the_gods_dice_remaining"] = max_dice
    return {"new_total": max_dice}


def _refresh_rage_uses_to_max(actor: Actor) -> dict | None:
    """Long rest fully refreshes Barbarian Rage uses to the level-
    table max stamped on `actor.resources["rage_uses_max"]` by
    pc_schema.derive_pc_resources. Skipped (returns None) when the
    actor has no rage_uses_max declared — non-Barbarians or fixture
    actors without the resource pair."""
    max_uses = int(actor.resources.get("rage_uses_max", 0))
    if max_uses <= 0:
        return None
    cur = int(actor.resources.get("rage_uses_remaining", 0))
    if cur >= max_uses:
        return None
    actor.resources["rage_uses_remaining"] = max_uses
    return {"new_total": max_uses}


def _refresh_arcane_recovery(actor: Actor) -> dict | None:
    """Long rest refreshes Arcane Recovery to 1 use."""
    cur = int(actor.resources.get("arcane_recovery_uses_remaining", 0))
    if cur >= 1:
        return None
    actor.resources["arcane_recovery_uses_remaining"] = 1
    return {"new_total": 1}


# ============================================================================
# Wizard: Arcane Recovery
# ============================================================================

def _apply_arcane_recovery(actor: Actor, level: int,
                              state: CombatState) -> dict | None:
    """Once per long rest, on completing a short rest, the wizard
    recovers expended slots up to ceil(level/2) combined levels.
    Slots restored must be ≤ 5th level."""
    uses = int(actor.resources.get("arcane_recovery_uses_remaining", 0))
    if uses <= 0:
        return None
    # Pre-decrement the use even if no slots are actually expended —
    # RAW: the activation consumes the use either way (player chooses
    # to use AR; if they don't, they don't have to invoke it). For
    # our purposes, only call this helper when the wizard would use
    # it, which we infer from "uses available AND at least one slot
    # is expended."
    if not _has_expended_slots(actor):
        return None
    actor.resources["arcane_recovery_uses_remaining"] = uses - 1
    state.event_log.append({
        "event": "feature_use_consumed",
        "actor": actor.id,
        "resource": "arcane_recovery_uses_remaining",
        "remaining": actor.resources["arcane_recovery_uses_remaining"],
        "action": "arcane_recovery",
    })
    # Fire the slot_recovery_partial primitive directly. Setting
    # current_attack.actor lets the primitive resolve the target.
    from engine.primitives import _slot_recovery_partial
    saved_attack = state.current_attack
    state.current_attack = {"actor": actor}
    try:
        result = _slot_recovery_partial({
            "max_combined_level": math.ceil(level / 2),
            "max_slot_level": 5,
        }, state, None)
    finally:
        state.current_attack = saved_attack
    return result


def _has_expended_slots(actor: Actor) -> bool:
    """True if the actor has any spell slot level where the current
    count is below the max."""
    for lvl, max_at in actor.spell_slots_max.items():
        if int(actor.spell_slots.get(lvl, 0)) < int(max_at):
            return True
    return False


# ============================================================================
# Fighter: Second Wind + Action Surge short-rest refresh
# ============================================================================

def _apply_second_wind_short_rest_refresh(actor: Actor, level: int,
                                              state: CombatState) -> dict | None:
    """Per RAW: Second Wind restores +1 use on a short rest, up to
    the level-table maximum. The max scales with fighter level
    (2/3/4 across L1/L4/L10 per c_fighter level_table).
    """
    cur = int(actor.resources.get("second_wind_uses_remaining", 0))
    max_uses = _fighter_second_wind_max_at_level(level)
    if max_uses == 0:
        return None
    if cur >= max_uses:
        return None
    actor.resources["second_wind_uses_remaining"] = cur + 1
    return {"added": 1,
             "new_total": actor.resources["second_wind_uses_remaining"]}


def _apply_pact_magic_short_rest_refresh(
        actor: Actor, state: CombatState) -> dict | None:
    """Per RAW (PR #101): Warlock Pact Magic slots recover on a SHORT
    rest. Restore `actor.spell_slots` to `actor.spell_slots_max`.

    Returns a `{level: restored_count, ...}` summary of what was
    refilled, or None if nothing was expended (all slots already at
    max) or the actor has no pact slot ceiling recorded.

    Single-class assumption: a pure Warlock's slots are ALL pact
    slots, so a blanket restore-to-max is correct. The caller gates
    this on `cls == "c_warlock"`; a Warlock multiclass (not modeled)
    would need to separate pact slots from standard slots before this
    blanket restore is safe.
    """
    if not actor.spell_slots_max:
        return None
    restored: dict = {}
    for lvl, max_at in actor.spell_slots_max.items():
        cur = int(actor.spell_slots.get(lvl, 0))
        max_int = int(max_at)
        if cur < max_int:
            restored[lvl] = max_int - cur
            actor.spell_slots[lvl] = max_int
    if not restored:
        return None
    state.event_log.append({
        "event": "pact_magic_slots_restored",
        "actor": actor.id,
        "restored": restored,
    })
    return restored


def _apply_action_surge_short_rest_refresh(actor: Actor, level: int,
                                                state: CombatState) -> dict | None:
    """Per RAW: Action Surge refreshes fully on a short rest. The max
    is 1 at L2-16, 2 at L17+."""
    if level < 2:
        return None
    max_uses = 2 if level >= 17 else 1
    cur = int(actor.resources.get("action_surge_uses_remaining", 0))
    if cur >= max_uses:
        return None
    actor.resources["action_surge_uses_remaining"] = max_uses
    return {"added": max_uses - cur,
             "new_total": max_uses}


def _fighter_second_wind_max_at_level(level: int) -> int:
    """Per c_fighter.level_table: second_wind_uses scales 2/3/4 across
    L1/L4/L10. Mirrors the data here for the rest cycle so we don't
    need to load the class def. If the schema changes, update here too.
    """
    if level >= 10:
        return 4
    if level >= 4:
        return 3
    if level >= 1:
        return 2
    return 0
