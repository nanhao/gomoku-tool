"""The LLM tried to act outside its turn."""

from gomoku_tool.errors.game_error import GameError


class TurnViolationError(GameError):
    """A move was refused because the LLM does not own the turn or the game ended.

    The engine has no player identity, so this guard is the only thing that
    prevents the LLM from playing the human's side.
    """
