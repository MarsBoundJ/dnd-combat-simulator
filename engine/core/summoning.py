"""Summoning — spawn new combatants into a live encounter (dynamic
encounter membership).

RAW (SRD 5.2.1, Wraith): "Create Specter. The wraith targets a Humanoid
corpse within 10 feet ... The target's spirit rises as a Specter ... under
the wraith's control. The wraith can have no more than seven specters
under its control at a time." Also conjure-type spells and other "calls N
creatures" effects.

This is the load-bearing engine piece: a creature spawned mid-fight must
become a full combatant immediately — built from a stat block, placed on
the summoner's side, inserted into the turn order, and live to the
candidate generator / targeting from that moment.

`summon` builds each creature via cli._build_actor (a `template_ref` spec,
so the summon gets the same resources/senses/derived stats any actor
does), tags it with `summoned_by`, appends it to `encounter.actors`, and
inserts it into `turn_order` immediately after the summoner — so it acts
later this round. A `max_total` cap (Wraith: 7) limits how many a single
summoner can have out at once.

v1 scope / deferrals:
  - The Create Specter CORPSE precondition (a Humanoid that died within
    1 minute, within 10 ft) is NOT modeled — battlefield-corpse tracking
    is a follow-up. v1 summons the creature unconditionally (the AI/gate
    layer can add the precondition later).
  - Summons act on their own inserted turn (after the summoner) rather
    than rolling fresh initiative — a deliberate simplification.
"""
from __future__ import annotations

import copy

from engine.core.state import Actor, CombatState


# ============================================================================
# Caster-aware summon parameters (Animate Objects / Bigby's Hand)
# ============================================================================
#
# Some summon spells scale with the CASTER, not a fixed stat block:
#   - Animate Objects: the number of objects = your spellcasting ability
#     modifier; each object's Slam attack uses your SPELL ATTACK modifier.
#   - Bigby's Hand: the hand's attacks use your spell attack modifier.
# A static `count` / static stat-block attack bonus can't express that, so the
# `_summon` primitive (and the AI summon scorer) resolve these from the
# summoner at cast/score time via the helpers below.


def caster_spellcasting_modifier(summoner: Actor) -> int:
    """The summoner's spellcasting ability modifier (Animate Objects count
    basis). Reads template.spellcasting_ability (CHA fallback), mirroring
    primitives._caster_spell_save_dc."""
    template = summoner.template or {}
    ability = template.get("spellcasting_ability") or "charisma"
    abbr = str(ability)[:3]
    score = (summoner.abilities.get(abbr) or {}).get("score", 10)
    return (score - 10) // 2


def caster_spell_attack_bonus(summoner: Actor) -> int:
    """The summoner's spell attack modifier = proficiency bonus +
    spellcasting ability modifier (the Slam / Clenched Fist to-hit per RAW)."""
    pb = int(((summoner.template or {}).get("cr") or {}).get(
        "proficiency_bonus", 2))
    return pb + caster_spellcasting_modifier(summoner)


def resolve_summon_count(params: dict, summoner: Actor) -> int:
    """Resolve a summon's creature count. `count_from: spellcasting_modifier`
    → the caster's spellcasting ability modifier (min 1); otherwise the static
    `count` (default 1)."""
    if params.get("count_from") == "spellcasting_modifier":
        return max(1, caster_spellcasting_modifier(summoner))
    return int(params.get("count", 1))


def resolve_summon_max_total(params: dict, summoner: Actor):
    """Resolve a summon's max_total cap. `spellcasting_modifier` → the caster's
    modifier (min 1); otherwise the literal value (int or None)."""
    mt = params.get("max_total")
    if mt == "spellcasting_modifier":
        return max(1, caster_spellcasting_modifier(summoner))
    return mt


def apply_caster_attack_bonus(new_actors: list, summoner: Actor) -> None:
    """Set each summoned creature's attack-roll bonus to the summoner's spell
    attack modifier (Animate Objects / Bigby's Hand RAW). The registry stat
    block carries only a static fallback bonus; this overrides it with the
    actual caster value.

    The summoned actors share ONE registry template reference (cli._build_actor
    returns the shared dict), so we deep-copy it ONCE for this batch and point
    every batch member at the copy — never mutating the registry template that
    future summons / encounters reuse."""
    if not new_actors:
        return
    bonus = caster_spell_attack_bonus(summoner)
    tmpl = copy.deepcopy(new_actors[0].template)
    for act in (tmpl.get("actions") or []):
        for step in (act.get("pipeline") or []):
            if step.get("primitive") == "attack_roll":
                step.setdefault("params", {})["bonus"] = bonus
    for a in new_actors:
        a.template = tmpl


def count_summons(summoner: Actor, state: CombatState) -> int:
    """How many living creatures this summoner currently has summoned."""
    return sum(1 for a in state.encounter.actors
               if a.summoned_by == summoner.id and a.is_alive())


def summon(summoner: Actor, monster_id: str, state: CombatState, *,
           count: int = 1, registry=None, max_total: int | None = None) -> list:
    """Summon `count` creatures of `monster_id` onto the summoner's side.

    Returns the list of new Actors (possibly fewer than `count` if a
    `max_total` cap is hit). Raises ValueError if no content registry is
    available to resolve the monster template."""
    registry = registry or state.content_registry
    if registry is None:
        raise ValueError("summon requires a content registry")
    from engine.cli import _build_actor

    new_actors: list = []
    existing = count_summons(summoner, state)
    for i in range(max(1, count)):
        if max_total is not None and existing + len(new_actors) >= max_total:
            break
        instance_id = f"{monster_id}__sum_{summoner.id}_{existing + i}"
        spec = {"template_ref": {"entity_type": "monster", "id": monster_id},
                "instance_id": instance_id,
                "position": list(summoner.position)}
        actor = _build_actor(spec, registry)
        actor.id = instance_id
        actor.side = summoner.side
        actor.summoned_by = summoner.id
        actor.position = tuple(summoner.position)
        new_actors.append(actor)

    if not new_actors:
        state.event_log.append({
            "event": "summon_capacity_reached", "summoner": summoner.id,
            "monster": monster_id, "max_total": max_total,
        })
        return []

    # Add to the encounter and insert into the turn order right after the
    # summoner, so the summons act later this round.
    state.encounter.actors.extend(new_actors)
    ids = [a.id for a in new_actors]
    try:
        idx = state.turn_order.index(summoner.id)
        state.turn_order[idx + 1:idx + 1] = ids
    except ValueError:
        state.turn_order.extend(ids)   # summoner not in order (defensive)

    state.event_log.append({
        "event": "summoned", "summoner": summoner.id,
        "monster": monster_id, "count": len(new_actors),
        "instances": ids,
    })
    return new_actors
