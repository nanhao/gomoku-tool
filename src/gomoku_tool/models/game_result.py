"""Everything one tool call reports back to the LLM."""

from dataclasses import dataclass

from gomoku_tool.models.game_snapshot import GameSnapshot
from gomoku_tool.models.side import Side


@dataclass(frozen=True)
class GameResult:
    """The snapshot of a tool call plus its human-readable context.

    Attributes:
        snapshot: Authoritative game state read from the engine.
        llm_side: Side the LLM plays, or ``None`` when no session is known.
        timed_out: Whether a wait ended at its deadline instead of a turn.
        notes: Additional facts (UI status, Redis fallback, timeout) rendered
            below the board.
    """

    snapshot: GameSnapshot
    llm_side: Side | None = None
    timed_out: bool = False
    notes: tuple[str, ...] = ()
