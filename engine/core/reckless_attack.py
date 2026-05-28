"""Reckless Attack — Barbarian L2 feature (PR #85).

RAW (PHB 2024 p.50):

  *Reckless Attack. You can throw aside all concern for defense to
  attack with increased ferocity. When you make your first attack roll
  on your turn, you can decide to attack recklessly. Doing so gives
  you advantage on Strength-based melee weapon attack rolls during
  this turn, but attack rolls against you have advantage until the
  start of your next turn.*

**Engine model.** Two boolean flags on the Actor, no
`active_modifiers` registration (like Rage):

  - `reckless_active` — drives advantage on the actor's STR-melee
    weapon attack rolls. Read each time `query_attack_modifiers`
    fires for an outgoing STR-melee attack.
  - `reckless_grants_advantage_until_next_turn` — drives advantage
    on every attack roll targeting the actor. Read each time
    `query_attack_modifiers` fires for an incoming attack.

Both clear in `Actor.reset_turn` at the start of the actor's next
turn (matching RAW's "until the start of your next turn" window).

**Activation timing.** RAW says the decision happens at the first
attack roll. The engine collapses this to a **pre-action runner
hook** (`EncounterRunner._maybe_activate_reckless_attack`) that fires
once per turn just before the main slot. This is functionally
equivalent in v1 — by deciding before the first swing we commit the
same way, and the AI's decision sees the same state the player would
(target HP, our HP, enemy count, expected DPR).

**AI heuristic.** Net eHP trade:
  - **Gain:** advantage on a STR-melee swing roughly increases hit
    chance by ~25% (varies with target AC; we use a uniform
    `RECKLESS_HIT_UPLIFT` proxy). Per-attack DPR uplift = hit_uplift
    × avg_damage. Multiply by expected number of attacks this turn
    (1 normally; multiattack count when Extra Attack hits).
  - **Cost:** every incoming melee/ranged attack against us until
    our next turn rolls with advantage. Same uplift × avg incoming
    damage × expected enemy attacks against us until our next turn.

Archetypes shortcut the math:
  - `berserker_fanatic`, `mindless_aggressor` → always activate
    (they don't weigh defense; fanatic/mindless commits).
  - `cowardly_skirmisher` → never (defensive priority).
  - Everyone else → cost-benefit check via `score_activation`.

**Deferred (each its own follow-on):**
  - Versatile-grip detection: a Barbarian with a Greatsword always
    gets the bonus; one with a Longsword used two-handed should also
    qualify. Engine's versatile-grip toggle is PR #N deferred.
  - Per-enemy threat weighting (which enemies have melee reach,
    which will move to attack us): v1 averages.
  - Reckless + Sneak Attack interplay (Rogue/Barbarian multiclass:
    advantage enables SA): orthogonal — the SA module already
    reads attack-roll advantage state at fire time.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# ============================================================================
# RAW eligibility
# ============================================================================

def is_eligible(actor: Actor) -> bool:
    """True iff `actor` has the Reckless Attack feature available.

    Requires `f_reckless_attack` in `template.features_known` (set by
    pc_schema from c_barbarian.yaml's L2 level_table entry). Returns
    False for non-Barbarians and for Barbarians below L2.
    """
    features = (actor.template or {}).get("features_known") or []
    return "f_reckless_attack" in features


def has_str_melee_weapon(actor: Actor) -> bool:
    """True iff the actor has at least one weapon_attack action that
    fires as a STR-based melee swing. Walks `template.actions` for
    pipeline `attack_roll` steps with `kind == 'melee'` and
    `ability == 'str'` (or unspecified — melee weapon attacks default
    to STR per RAW).

    Used by `_maybe_activate_reckless_attack` as a sanity gate so a
    Barbarian wielding only a Shortbow doesn't activate Reckless (it
    only benefits STR-melee).
    """
    for action in (actor.template.get("actions") or []):
        if action.get("type") != "weapon_attack":
            continue
        for step in (action.get("pipeline") or []):
            if step.get("primitive") != "attack_roll":
                continue
            params = step.get("params") or {}
            kind = params.get("kind", "melee")
            ability = params.get("ability", "str")
            if kind == "melee" and ability == "str":
                return True
    return False


# ============================================================================
# State transitions
# ============================================================================

def activate(actor: Actor, state: CombatState) -> None:
    """Flip both Reckless flags on. Logs `reckless_attack_activated`
    with the actor id + round. Idempotent: re-activating during the
    same turn is a no-op.
    """
    if actor.reckless_active:
        return
    actor.reckless_active = True
    actor.reckless_grants_advantage_until_next_turn = True
    state.event_log.append({
        "event": "reckless_attack_activated",
        "actor": actor.id,
        "round": state.round,
    })


# ============================================================================
# Modifier-query gates (called from query_attack_modifiers)
# ============================================================================

def applies_self_advantage(attacker: Actor,
                            attack_params: dict | None) -> bool:
    """RAW gate for advantage on the BARBARIAN's outgoing attack:

      - `attacker.reckless_active` is True
      - Attack is a melee weapon attack (params.kind == 'melee')
      - Attack uses Strength as its ability (params.ability == 'str'
        or unspecified — melee weapon attacks default to STR per RAW)

    Returns False when the actor isn't reckless or the swing isn't
    STR-melee. The DEX-finesse swing on a Reckless Barbarian
    intentionally gets nothing — RAW pins the bonus to STR.
    """
    if not attacker.reckless_active:
        return False
    params = attack_params or {}
    kind = params.get("kind", "melee")
    if kind != "melee":
        return False
    ability = params.get("ability", "str")
    return ability == "str"


def applies_attacker_advantage_against(target: Actor) -> bool:
    """RAW gate for advantage on any attack TARGETING a reckless
    Barbarian (the defensive cost of Reckless Attack). True for the
    full window from activation to the start of the Barbarian's next
    turn — set by `activate`, cleared by `Actor.reset_turn`."""
    return bool(target.reckless_grants_advantage_until_next_turn)


# ============================================================================
# AI scoring
# ============================================================================

# Empirical hit-rate uplift from rolling with advantage. Exact value
# depends on the base hit chance (advantage is most valuable around
# 50% hit chance, worth ~+25%; less valuable at the extremes). We use
# 0.25 as a uniform proxy — same simplification used elsewhere in
# the engine's eHP estimators (Hide, Sap, Steady Aim).
RECKLESS_HIT_UPLIFT: float = 0.25

# Average number of enemy attacks that will land on the Barbarian
# between the activation and the start of their next turn. Three
# enemies × one attack each is a typical fight-shape; we cap at 3 to
# avoid overweighting late-game scenarios where 6+ enemies still
# stand. The cost calc multiplies this by the per-enemy expected
# damage.
DEFAULT_INCOMING_ATTACK_COUNT_CAP: int = 3


def _expected_attack_count(actor: Actor) -> int:
    """How many STR-melee attack rolls will the actor make this turn?

    Walks template.actions for multiattack count if present, else 1.
    Used by the gain side of the cost-benefit check.
    """
    for action in (actor.template.get("actions") or []):
        if action.get("type") == "multiattack":
            return max(1, int(action.get("count", 1)))
    return 1


def _avg_outgoing_damage(actor: Actor) -> float:
    """Estimate per-swing average damage from the actor's primary
    STR-melee weapon. Sums dice average + STR mod + rage bonus (if
    applicable). Used by gain side of cost-benefit check."""
    from engine.core.state import ability_modifier
    str_mod = ability_modifier(actor.abilities.get("str", {}).get("score", 10))
    rage_bonus = int(getattr(actor, "rage_damage_bonus", 0) or 0)
    for action in (actor.template.get("actions") or []):
        if action.get("type") != "weapon_attack":
            continue
        for step in (action.get("pipeline") or []):
            if step.get("primitive") == "damage":
                params = step.get("params") or {}
                dice = params.get("dice", "")
                dice_avg = _dice_average(dice)
                return dice_avg + str_mod + rage_bonus
    return 0.0


def _avg_incoming_damage(actor: Actor, state: CombatState) -> float:
    """Estimate per-attack average damage from a typical enemy. Picks
    the median enemy and reads their primary attack's avg damage.
    Conservative when enemies have no scannable attack."""
    enemies = [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    if not enemies:
        return 0.0
    damages = []
    for enemy in enemies:
        for action in (enemy.template.get("actions") or []):
            if action.get("type") != "weapon_attack":
                continue
            for step in (action.get("pipeline") or []):
                if step.get("primitive") == "damage":
                    params = step.get("params") or {}
                    dmg = _dice_average(params.get("dice", "")) + \
                          int(params.get("modifier", 0))
                    damages.append(max(0.0, dmg))
                    break
            break
    if not damages:
        return 0.0
    damages.sort()
    return damages[len(damages) // 2]


def _dice_average(dice_expr: str) -> float:
    """Average value of a dice expression like '2d6' or '1d12'. Returns
    0 for empty / malformed strings. Skeleton-grade: handles 'NdM' and
    'NdM+K' shapes only."""
    if not dice_expr:
        return 0.0
    expr = dice_expr.strip().lower().replace(" ", "")
    flat = 0
    if "+" in expr:
        expr, _, tail = expr.partition("+")
        try:
            flat = int(tail)
        except ValueError:
            flat = 0
    if "d" not in expr:
        try:
            return float(expr)
        except ValueError:
            return 0.0
    n_str, _, m_str = expr.partition("d")
    try:
        n = int(n_str) if n_str else 1
        m = int(m_str)
    except ValueError:
        return 0.0
    return n * (m + 1) / 2.0 + flat


def score_activation(actor: Actor, state: CombatState) -> tuple[float, float]:
    """Return (gain_eHP, cost_eHP) of activating Reckless Attack.

    Gain = expected DPR uplift from advantage on STR-melee swings
    this turn:
        attack_count × RECKLESS_HIT_UPLIFT × avg_swing_damage

    Cost = expected extra incoming damage from enemies attacking with
    advantage until our next turn:
        min(num_enemies, cap) × RECKLESS_HIT_UPLIFT × avg_enemy_damage

    Both are eHP-comparable (same unit). The runner activates iff
    gain > cost.
    """
    attacks = _expected_attack_count(actor)
    avg_out = _avg_outgoing_damage(actor)
    gain = attacks * RECKLESS_HIT_UPLIFT * avg_out

    enemies_alive = sum(1 for a in state.encounter.actors
                          if a.side != actor.side and a.is_alive())
    incoming_count = min(enemies_alive, DEFAULT_INCOMING_ATTACK_COUNT_CAP)
    avg_in = _avg_incoming_damage(actor, state)
    cost = incoming_count * RECKLESS_HIT_UPLIFT * avg_in

    return gain, cost


# Archetypes that always activate without checking the cost (RP-driven
# behavior overrides — mindless / fanatic don't weigh defense). Read
# by the runner hook BEFORE the cost-benefit calculation.
_ALWAYS_RECKLESS_ARCHETYPES: frozenset[str] = frozenset({
    "berserker_fanatic",
    "mindless_aggressor",
})

# Archetypes that never activate Reckless regardless of math.
# Cowardly skirmishers preserve defense over aggression.
_NEVER_RECKLESS_ARCHETYPES: frozenset[str] = frozenset({
    "cowardly_skirmisher",
})


def should_activate(actor: Actor, state: CombatState) -> tuple[bool, str]:
    """Top-level AI decision. Returns (activate, reason) so the runner
    can log why activation did or didn't fire.

    Reasons:
      - 'already_active' — flag already set this turn (no-op)
      - 'no_feature' — actor lacks f_reckless_attack
      - 'no_str_melee' — actor has no STR-melee weapon to benefit
      - 'no_enemies' — no living enemies (nothing to attack)
      - 'archetype_always' — archetype overrides cost check
      - 'archetype_never' — archetype refuses activation
      - 'gain_exceeds_cost' / 'cost_exceeds_gain' — heuristic result
    """
    if actor.reckless_active:
        return False, "already_active"
    if not is_eligible(actor):
        return False, "no_feature"
    if not has_str_melee_weapon(actor):
        return False, "no_str_melee"
    enemies_alive = any(a.side != actor.side and a.is_alive()
                          for a in state.encounter.actors)
    if not enemies_alive:
        return False, "no_enemies"

    # Archetype overrides — bypass the math when RP dictates.
    from engine.ai.behavior_profile import resolve_archetype
    archetype = resolve_archetype(actor)
    if archetype in _ALWAYS_RECKLESS_ARCHETYPES:
        return True, "archetype_always"
    if archetype in _NEVER_RECKLESS_ARCHETYPES:
        return False, "archetype_never"

    gain, cost = score_activation(actor, state)
    if gain > cost:
        return True, "gain_exceeds_cost"
    return False, "cost_exceeds_gain"
