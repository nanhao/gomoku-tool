"""An MCP task cancelled the wait before a turn boundary."""

from gomoku_tool.errors.game_error import GameError


class WaitCancelledError(GameError):
    """The wait was stopped cooperatively.

    The game and the gomoku-ui window are untouched; ``wait_for_turn`` can
    resume the wait later.
    """
