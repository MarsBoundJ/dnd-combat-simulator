"""Regeneration — regain HP at the start of the creature's turn.

RAW (SRD 5.2.1) has two flavors:

  - Plain ("if it has at least 1 Hit Point"): the creature regains N HP at
    the start of each of its turns while still up. It does NOT revive from
    0 — 0 HP is ordinary death.  (e.g. the Stone Guardian.)

  - Troll rule ("dies only if it starts its turn with 0 HP and doesn't
    regenerate"): the creature regains N HP each turn; Acid or Fire damage
    switches the trait off for its NEXT turn. Crucially, 0 HP is NOT
    immediate death — a downed troll regenerates back UNLESS it took
    acid/fire, which is the whole "you must burn the troll" mechanic.

Stat-block shape (monster `regeneration`):

    regeneration:
      amount: 15
      suppressed_by: [acid, fire]   # switches off for the next turn
      revives_from_zero: true       # the Troll rule; default false

Modeling:
  - `note_damage` (called from primitives._damage) flips
    `actor.regen_suppressed` when a suppressing damage type lands.
  - At the creature's turn start the runner calls `resolve_turn_start`
    BEFORE the is_alive turn-skip gate, so a downed troll (0 HP, not yet
    dead) gets its revive-or-die resolution:
      * suppressed → no heal this turn; clear the flag (one-turn
        suppression). If at 0 HP and revives_from_zero → the creature
        dies now (started its turn at 0 and didn't regenerate).
      * not suppressed → heal `amount` (capped at hp_max). For the plain
        flavor only while hp >= 1; for the Troll flavor even from 0
        (revival).
  - primitives._damage leaves a revives_from_zero creature DOWNED (not
    is_dead) at 0 HP, so it survives to its turn-start resolution.

v1 scope / deferrals:
  - The Hydra's lose-a-head / multi-attack-scaling mechanic is separate
    (on-hit + dynamic action count) and is NOT modeled here — only the
    Regeneration 10 + fire-stops-regrowth piece maps to this trait.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


def configured(template: dict) -> dict | None:
    block = (template or {}).get("regeneration") or None
    if not block or not block.get("amount"):
        return None
    return block


def revives_from_zero(actor: Actor) -> bool:
    block = configured(actor.template) or {}
    return bool(block.get("revives_from_zero", False))


def is_pending(actor: Actor) -> bool:
    """True if `actor` is a Troll-rule regenerator that's downed at 0 HP
    but not yet dead — it will revive (or die) at its next turn start. Such
    a creature keeps its side in the fight, so the encounter must not end
    while one exists (handled in runner.check_termination)."""
    return (revives_from_zero(actor)
            and actor.hp_current <= 0
            and not actor.is_dead
            and not getattr(actor, "is_fled", False))


def note_damage(actor: Actor, damage_type: str | None) -> None:
    """If `damage_type` suppresses this creature's Regeneration, flag it so
    the trait doesn't function at the creature's next turn start."""
    block = configured(actor.template)
    if block is None or not damage_type:
        return
    if damage_type in (block.get("suppressed_by") or []):
        actor.regen_suppressed = True


def resolve_turn_start(actor: Actor, state: CombatState) -> None:
    """At the start of `actor`'s turn: heal (or, for the Troll rule, revive
    from 0), unless its Regeneration is suppressed this turn. Marks death
    when a revives_from_zero creature starts its turn at 0 while suppressed.
    No-op for creatures without Regeneration."""
    block = configured(actor.template)
    if block is None or actor.is_dead:
        return
    amount = int(block["amount"])
    from_zero = bool(block.get("revives_from_zero", False))
    suppressed = actor.regen_suppressed
    actor.regen_suppressed = False   # one-turn suppression — clear it now

    if suppressed:
        state.event_log.append({
            "event": "regeneration_suppressed",
            "actor": actor.id, "hp": actor.hp_current,
        })
        # Troll rule: starting its turn at 0 with regen off → it dies now.
        if from_zero and actor.hp_current == 0:
            actor.is_dead = True
            state.event_log.append({
                "event": "regeneration_death", "actor": actor.id,
            })
            if actor.concentration_on is not None:
                from engine.core.concentration import end_concentration
                end_concentration(actor, state, reason="regeneration_death")
        return

    # Not suppressed. Plain flavor only heals while still up (>= 1 HP); the
    # Troll flavor revives even from 0.
    if actor.hp_current <= 0 and not from_zero:
        return
    if actor.hp_current >= actor.hp_max:
        return
    healed_to = min(actor.hp_max, actor.hp_current + amount)
    gained = healed_to - actor.hp_current
    actor.hp_current = healed_to
    state.event_log.append({
        "event": "regenerated", "actor": actor.id,
        "amount": gained, "hp_current": actor.hp_current,
    })
