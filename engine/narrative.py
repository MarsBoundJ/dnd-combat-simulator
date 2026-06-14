"""Narrative combat-log renderer (WS-F0).

A **pure formatter** over a run's typed event stream (`CombatState.event_log`
— the ordered list of `{"event": ..., ...}` dicts the engine appends as it
adjudicates a fight). It turns that stream into a human-readable, round-by-round
transcript so a user can audit *what the engine actually did* instead of
trusting a black box. Example line:

    Round 2 — Aria (Wizard): moves to (12,8); attacks Orc: hit (roll 18) for
    11 fire; Orc 23/34 HP (68%).

Design contract (per docs/stages-1-3-plan.md §3.6 / WS-F0):

  * **Pure + library-only.** No engine state is mutated, no CLI wiring, no
    imports from the engine core — the renderer reads plain dicts (and, when
    handed an optional roster, plain attribute access on actor-like objects).
    Deterministic: same events in → same lines out.
  * **Render real fields only.** Every clause below maps to a field the engine
    genuinely emits (verified against the live event_log taxonomy). We never
    invent fields.
  * **Faithful with or without a roster.** The event stream carries actor /
    target *ids* (e.g. "goblin_1") and a damaged creature's *remaining* HP, but
    NOT display names, class, or HP maximum. Pass `actors` (id → label string or
    an actor-like object) to pretty-print "Name (Class)" and a "cur/max (pct%)"
    HP fraction; omit it and the transcript shows ids and current-HP-only. Both
    are faithful — the roster is enrichment, not a new data source.

Known gap (escalated — see the PR description and docs/srd/NEEDS_ENGINE_WORK.md):
the common weapon-attack / single-target-cast path emits `attack_roll` +
`damage_dealt` with NO action/spell name, so those lines read "attacks X"
rather than "casts Fire Bolt at X". Action-id-bearing events (AoE casts,
recharge, legendary, free actions) ARE named. A small `action_declared` event
would close the gap; this renderer must not modify events.py to add it.

Public API:
    render_narrative(events, *, actors=None, show_unhandled=False) -> list[str]
    format_run(state_or_events, **kwargs) -> str   # convenience: joined text
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


# Events that mark an actor's turn (and carry the round number).
_TURN_START = "turn_start"
_TURN_END = "turn_end"


# ---------------------------------------------------------------------------
# Label / HP resolution (optional roster enrichment)
# ---------------------------------------------------------------------------

def _class_parenthetical(obj: Any) -> str | None:
    """Best-effort '(Wizard)'-style tag from an actor-like template, or None.

    Tries the PC-build provenance, then a level map, then a monster's
    creature_type — all defensive: any miss returns None and the caller falls
    back to the bare name. Never raises."""
    template = getattr(obj, "template", None)
    if not isinstance(template, Mapping):
        return None
    derived = template.get("derived_from_pc_schema")
    if isinstance(derived, Mapping) and derived.get("class"):
        return _titleize_class(str(derived["class"]))
    levels = template.get("levels")
    if isinstance(levels, Mapping) and levels:
        # Multiclass: list each class, e.g. "(Fighter/Wizard)".
        return "/".join(_titleize_class(c) for c in levels)
    ctype = template.get("creature_type")
    if ctype:
        return str(ctype).replace("_", " ").title()
    return None


def _titleize_class(class_id: str) -> str:
    """'c_wizard' -> 'Wizard'; 'wizard' -> 'Wizard'."""
    name = class_id[2:] if class_id.startswith("c_") else class_id
    return name.replace("_", " ").title()


def _resolve_actor(actors: Mapping | None, aid: str | None) -> tuple[str, int | None]:
    """Return (display_label, hp_max_or_None) for an actor id.

    `actors[aid]` may be a plain label string, or an actor-like object exposing
    `.name` / `.template` / `.hp_max`. Falls back to the raw id when the roster
    is absent or lacks the id — so the line is always renderable."""
    if aid is None:
        return ("?", None)
    if not actors or aid not in actors:
        return (str(aid), None)
    entry = actors[aid]
    if isinstance(entry, str):
        return (entry, None)
    # Actor-like object.
    name = getattr(entry, "name", None) or str(aid)
    cls = _class_parenthetical(entry)
    label = f"{name} ({cls})" if cls else str(name)
    hp_max = getattr(entry, "hp_max", None)
    return (label, hp_max if isinstance(hp_max, int) and hp_max > 0 else None)


def _hp_clause(actors: Mapping | None, target_id: str | None,
               hp_remaining: Any) -> str | None:
    """'Orc 23/34 HP (68%)' when the roster supplies hp_max, else
    'Orc 23 HP'. None when there's no remaining-HP figure to show."""
    if not isinstance(hp_remaining, int):
        return None
    label, hp_max = _resolve_actor(actors, target_id)
    if hp_max:
        pct = round(100 * hp_remaining / hp_max)
        return f"{label} {hp_remaining}/{hp_max} HP ({pct}%)"
    return f"{label} {hp_remaining} HP"


# ---------------------------------------------------------------------------
# Per-clause rendering
# ---------------------------------------------------------------------------

def _coords(point: Any) -> str:
    """[12, 8] / (12, 8) -> '(12,8)'."""
    try:
        x, y = point[0], point[1]
        return f"({x},{y})"
    except (TypeError, IndexError, KeyError):
        return "(?)"


def _action_name(action_id: Any) -> str:
    """'a_fire_bolt' / 'f_fireball' -> 'Fire Bolt' / 'Fireball'."""
    s = str(action_id)
    for prefix in ("a_", "f_", "ba_", "la_", "t_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.replace("_", " ").title()


def _condition_name(cond_id: Any) -> str:
    """'co_frightened' -> 'frightened'."""
    s = str(cond_id)
    return (s[3:] if s.startswith("co_") else s).replace("_", " ")


def _ability_name(ability: Any) -> str:
    """'dexterity' -> 'DEX' (3-letter), else titlecase fallback."""
    full = {"strength": "STR", "dexterity": "DEX", "constitution": "CON",
            "intelligence": "INT", "wisdom": "WIS", "charisma": "CHA"}
    return full.get(str(ability).lower(), str(ability).title())


def _attack_clause(ev: dict, actors: Mapping | None,
                   merged_damage: dict | None) -> str:
    """Render an attack_roll (+ optionally the damage that immediately
    followed it, merged into one clause).

    The action/weapon name is NOT on this event (see module docstring), so the
    clause leads with the result verb: "hits Orc (roll 18) for 11 fire"."""
    tgt_label, _ = _resolve_actor(actors, ev.get("target"))
    result = ev.get("result")
    d20 = ev.get("d20")
    roll = f" (roll {d20})" if isinstance(d20, int) else ""
    if result == "crit":
        clause = f"crits {tgt_label}{roll}"
    elif result == "hit":
        clause = f"hits {tgt_label}{roll}"
    else:  # miss (rolled, or auto-miss with a reason)
        reason = ev.get("reason")
        if reason and not isinstance(d20, int):
            clause = f"misses {tgt_label} ({str(reason).replace('_', ' ')})"
        else:
            clause = f"misses {tgt_label}{roll}"
    if merged_damage is not None:
        amt = merged_damage.get("amount")
        dtype = merged_damage.get("type", "")
        if isinstance(amt, int):
            clause += f" for {amt} {dtype}".rstrip()
    return clause


def _damage_clause(ev: dict, actors: Mapping | None) -> str:
    tgt_label, _ = _resolve_actor(actors, ev.get("target"))
    amt = ev.get("amount")
    dtype = ev.get("type", "")
    return f"{tgt_label} takes {amt} {dtype}".rstrip()


def _save_clause(ev: dict, actors: Mapping | None) -> str:
    tgt_label, _ = _resolve_actor(actors, ev.get("target"))
    ability = _ability_name(ev.get("ability"))
    dc = ev.get("dc")
    outcome = "succeeds" if ev.get("outcome") == "success" else "fails"
    total = ev.get("total")
    roll = f" (roll {total})" if isinstance(total, int) else ""
    extra = ""
    if ev.get("save_immune"):
        extra = " [immune]"
    return f"{tgt_label} {ability} save vs DC {dc}: {outcome}{roll}{extra}"


# ---------------------------------------------------------------------------
# Turn buffering — collect a turn's events into one transcript line
# ---------------------------------------------------------------------------

class _TurnBuffer:
    """Accumulates clauses for one actor-turn, then renders a single line."""

    def __init__(self, actor_id: str | None, round_no: Any,
                 actors: Mapping | None):
        self.actor_id = actor_id
        self.round_no = round_no
        self.actors = actors
        self.clauses: list[str] = []

    def add(self, text: str) -> None:
        if text:
            self.clauses.append(text)

    def render(self) -> str | None:
        if not self.clauses:
            return None
        label, _ = _resolve_actor(self.actors, self.actor_id)
        round_part = (f"Round {self.round_no} — "
                      if self.round_no is not None else "")
        return f"{round_part}{label}: " + "; ".join(self.clauses) + "."


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def render_narrative(events: Iterable[dict], *, actors: Mapping | None = None,
                     show_unhandled: bool = False) -> list[str]:
    """Render the typed event stream into a list of transcript lines.

    Args:
        events: the run's event stream — `CombatState.event_log` (an ordered
            iterable of `{"event": <name>, ...}` dicts).
        actors: optional roster mapping actor id -> a display-label string OR an
            actor-like object (with `.name`, `.template`, `.hp_max`). Enables
            "Name (Class)" labels and "cur/max (pct%)" HP fractions. Omitted →
            ids and current-HP-only (still faithful).
        show_unhandled: when True, any event with no dedicated renderer is
            emitted as a raw "(event_name)" clause so nothing is silently
            dropped — useful for deep auditing. Default False keeps the
            transcript clean (internal bookkeeping events are skipped).

    Returns:
        A list of strings, one per actor-turn (plus a leading setup line when
        initiative is in the stream). Each turn line is round-prefixed, e.g.
        "Round 2 — Aria (Wizard): moves to (12,8); attacks Orc: hit (roll 18)
        for 11 fire; Orc 23/34 HP (68%)."
    """
    events = list(events)
    lines: list[str] = []
    current_round: Any = None
    buf: _TurnBuffer | None = None
    # Pre-turn (setup) events accumulate here until the first turn_start.
    setup_clauses: list[str] = []

    def flush() -> None:
        nonlocal buf
        if buf is not None:
            line = buf.render()
            if line:
                lines.append(line)
        buf = None

    def emit_clause(text: str) -> None:
        if not text:
            return
        if buf is not None:
            buf.add(text)
        else:
            setup_clauses.append(text)

    for i, ev in enumerate(events):
        name = ev.get("event")

        # --- Turn / round structure -------------------------------------
        if name == _TURN_START:
            flush()
            current_round = ev.get("round", current_round)
            buf = _TurnBuffer(ev.get("actor"), current_round, actors)
            continue
        if name == _TURN_END:
            flush()
            continue

        # --- Attack (+ merge the damage that immediately follows it) ----
        if name == "attack_roll":
            merged = None
            nxt = events[i + 1] if i + 1 < len(events) else None
            if (nxt is not None and nxt.get("event") == "damage_dealt"
                    and nxt.get("target") == ev.get("target")
                    and nxt.get("actor") == ev.get("actor")):
                merged = nxt
                # mark consumed so the standalone damage branch skips it
                ev["_merged_damage_idx"] = i + 1
            emit_clause(_attack_clause(ev, actors, merged))
            if merged is not None:
                hp = _hp_clause(actors, merged.get("target"),
                                merged.get("target_hp_remaining"))
                if hp:
                    emit_clause(hp)
            continue

        if name == "damage_dealt":
            # Skip if it was merged into the preceding attack clause.
            prev = events[i - 1] if i > 0 else None
            if (prev is not None
                    and prev.get("_merged_damage_idx") == i):
                continue
            emit_clause(_damage_clause(ev, actors))
            hp = _hp_clause(actors, ev.get("target"),
                            ev.get("target_hp_remaining"))
            if hp:
                emit_clause(hp)
            continue

        # --- Movement ----------------------------------------------------
        if name == "moved":
            emit_clause(f"moves to {_coords(ev.get('to'))}")
            continue

        # --- Saves -------------------------------------------------------
        if name == "forced_save":
            emit_clause(_save_clause(ev, actors))
            continue

        # --- Named actions (the events that DO carry an action id) ------
        if name == "aoe_origin_placed":
            where = _coords(ev.get("origin"))
            emit_clause(f"casts {_action_name(ev.get('action'))} at {where}")
            continue
        if name in ("free_action_fired", "granted_action"):
            tgt = ev.get("target")
            tgt_label, _ = _resolve_actor(actors, tgt) if tgt else ("", None)
            at = f" at {tgt_label}" if tgt else ""
            emit_clause(f"uses {_action_name(ev.get('action'))}{at}")
            continue
        if name == "recharge_spent":
            emit_clause(f"uses {_action_name(ev.get('action'))} (recharge)")
            continue
        if name == "legendary_action_used":
            emit_clause(
                f"legendary action: {_action_name(ev.get('option'))}")
            continue
        if name == "spell_cancelled":
            emit_clause(f"{_action_name(ev.get('action'))} is countered")
            continue

        # --- Effects / outcomes -----------------------------------------
        if name == "condition_applied":
            tgt_label, _ = _resolve_actor(actors, ev.get("target"))
            emit_clause(f"{tgt_label} is {_condition_name(ev.get('condition'))}")
            continue
        if name == "condition_immune":
            tgt_label, _ = _resolve_actor(actors, ev.get("target"))
            emit_clause(f"{tgt_label} is immune to "
                        f"{_condition_name(ev.get('condition'))}")
            continue
        if name == "healed":
            tgt_label, _ = _resolve_actor(actors, ev.get("target"))
            amt = ev.get("amount")
            now = ev.get("hp_current")
            tail = f" (now {now} HP)" if isinstance(now, int) else ""
            emit_clause(f"{tgt_label} heals {amt}{tail}")
            continue
        if name == "hp_threshold_drop":
            tgt_label, _ = _resolve_actor(actors, ev.get("target"))
            emit_clause(f"{tgt_label} drops to 0 HP")
            continue
        if name == "creature_dropped":
            tgt_label, _ = _resolve_actor(actors, ev.get("creature"))
            emit_clause(f"{tgt_label} drops!")
            continue
        if name == "creature_bloodied":
            tgt_label, _ = _resolve_actor(actors, ev.get("creature"))
            emit_clause(f"{tgt_label} is bloodied")
            continue
        if name == "initiative_rolled":
            # Setup-phase event; render compactly before the first turn.
            aid = ev.get("actor")
            if aid is not None:
                lbl, _ = _resolve_actor(actors, aid)
                roll = ev.get("initiative", ev.get("roll"))
                emit_clause(f"{lbl} initiative {roll}"
                            if roll is not None else f"{lbl} rolls initiative")
            continue

        # --- Anything else ----------------------------------------------
        if show_unhandled:
            emit_clause(f"({name})")

    flush()

    # Prepend a setup line if anything accumulated before the first turn.
    if setup_clauses:
        lines.insert(0, "Setup — " + "; ".join(setup_clauses) + ".")
    return lines


def format_run(state_or_events: Any, *, actors: Mapping | None = None,
               show_unhandled: bool = False) -> str:
    """Convenience: render a whole run as one newline-joined transcript.

    Accepts either a `CombatState` (anything exposing `.event_log`) or a raw
    event iterable. If `actors` is omitted and a CombatState carrying an
    `encounter.actors` roster is passed, that roster is used automatically so
    names/HP fractions render without the caller wiring it up."""
    events = getattr(state_or_events, "event_log", state_or_events)
    if actors is None:
        actors = _roster_from_state(state_or_events)
    return "\n".join(render_narrative(events, actors=actors,
                                      show_unhandled=show_unhandled))


def _roster_from_state(state: Any) -> Mapping | None:
    """Pull an {id: Actor} roster off a CombatState-like object, if present.
    Returns None for a bare event list."""
    enc = getattr(state, "encounter", None)
    actors = getattr(enc, "actors", None)
    if not actors:
        return None
    try:
        return {a.id: a for a in actors}
    except (AttributeError, TypeError):
        return None
