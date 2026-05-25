"""Encounter outcome reports — structured JSON output.

For Stage 1 internal grading, the report is the deliverable. Trusight
pipelines consume the JSON; the CLI prints a human-readable summary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from engine.core.state import CombatState, Actor


@dataclass
class EncounterReport:
    """Structured outcome of one encounter run."""
    encounter_id: str
    winning_side: str | None
    termination_reason: str
    rounds_elapsed: int
    actors: list[dict]
    event_log: list[dict]

    @classmethod
    def from_state(cls, state: CombatState) -> "EncounterReport":
        winning_side = None
        if state.termination_reason.startswith("side_") and \
                state.termination_reason.endswith("_victory"):
            winning_side = state.termination_reason[len("side_"):-len("_victory")]
        actor_summaries = [
            {
                "id": a.id,
                "name": a.name,
                "side": a.side,
                "hp_max": a.hp_max,
                "hp_remaining": a.hp_current,
                "alive": a.is_alive(),
                "fled": a.is_fled,
                "dead": a.is_dead,
            }
            for a in state.encounter.actors
        ]
        return cls(
            encounter_id=state.encounter.id,
            winning_side=winning_side,
            termination_reason=state.termination_reason,
            rounds_elapsed=state.round,
            actors=actor_summaries,
            event_log=state.event_log,
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.__dict__, indent=indent, default=str)

    def to_summary(self) -> str:
        lines = [
            f"Encounter: {self.encounter_id}",
            f"Outcome:   {self.termination_reason}",
            f"Winner:    {self.winning_side or '(none)'}",
            f"Rounds:    {self.rounds_elapsed}",
            "Actors:",
        ]
        for a in self.actors:
            status = "alive" if a["alive"] else ("fled" if a["fled"] else "dead")
            lines.append(
                f"  - {a['name']:30} [{a['side']:5}] HP {a['hp_remaining']:3}/{a['hp_max']:3} ({status})"
            )
        lines.append(f"Events:    {len(self.event_log)} entries")
        return "\n".join(lines)
