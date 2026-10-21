"""The gomoku-engine request could not be completed."""

from gomoku_tool.errors.game_error import GameError


class EngineError(GameError):
    """A REST call to the engine failed.

    Attributes:
        status_code: HTTP status of the rejection, or ``None`` for transport
            failures (timeout, connection refused, malformed payload).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Create the error.

        Args:
            message: Human-readable reason, suitable for the LLM.
            status_code: HTTP status when the engine answered with an error.
        """
        super().__init__(message)
        self.status_code: int | None = status_code
