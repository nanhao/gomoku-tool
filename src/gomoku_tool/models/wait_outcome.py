"""Result of one turn-sized wait."""

from dataclasses import dataclass

from gomoku_tool.models.game_snapshot import GameSnapshot


@dataclass(frozen=True)
class WaitOutcome:
    """How a wait ended, together with the authoritative snapshot.

    Attributes:
        snapshot: The latest snapshot read from the engine.
        timed_out: Whether the deadline expired before the wait condition.
        cancelled: Whether the MCP task asked the wait to stop.
    """

    snapshot: GameSnapshot
    timed_out: bool = False
    cancelled: bool = False
