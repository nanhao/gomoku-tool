"""Redis move-event delivery failed; polling can take over."""

from gomoku_tool.errors.game_error import GameError


class EventStreamError(GameError):
    """The move-event stream is unavailable or broke mid-wait.

    This is never fatal for a game: the snapshot remains authoritative, so the
    turn waiter falls back to polling the engine.
    """
