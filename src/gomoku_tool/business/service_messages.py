"""The exact user-facing text emitted by the game use cases.

Every note appears under the rendered board and every error message becomes a
``ToolError``, so both are part of the interface the LLM reads. Keeping them
in one class makes the vocabulary reviewable and keeps ``GameService``
focused on orchestration.
"""

from typing import ClassVar


class ServiceMessages:
    """Templates for recoverable notes and expected domain errors."""

    # One note per recoverable condition. They are phrased as actionable
    # advice because the LLM decides what to do next from this text alone.
    NOTE_UI_OPENED: ClassVar[str] = "opened gomoku-ui for the human as {side}"
    NOTE_UI_FAILED: ClassVar[str] = (
        "gomoku-ui did not open ({error}); start it manually with: {command}"
    )
    NOTE_EVENT_STREAM_FAILED: ClassVar[str] = (
        "live move events unavailable ({error}); waiting will poll the engine"
    )
    NOTE_START_TIMEOUT: ClassVar[str] = (
        "still waiting for the human's first move; "
        "call wait_for_turn to continue waiting."
    )
    NOTE_TURN_TIMEOUT: ClassVar[str] = (
        "still waiting for the human's move; "
        "call wait_for_turn to continue waiting."
    )

    # Domain error messages. The adapter forwards them verbatim as ToolError.
    MESSAGE_NEGATIVE_TIMEOUT: ClassVar[str] = (
        "timeout_seconds must be zero or positive, got {value}."
    )
    MESSAGE_MISSING_SIDE: ClassVar[str] = (
        "No session is tracked for game {game_id}; pass llm_side (black or "
        "white) to attach to it."
    )
    MESSAGE_GAME_OVER: ClassVar[str] = (
        "The game is over ({winner}); no move was sent."
    )
    MESSAGE_FOREIGN_TURN: ClassVar[str] = (
        "It is not your turn: the engine reports {current} to move; "
        "no move was sent."
    )
    MESSAGE_CANCELLED: ClassVar[str] = (
        "The wait was cancelled; the game and the gomoku-ui window are "
        "untouched. Call wait_for_turn to resume."
    )
