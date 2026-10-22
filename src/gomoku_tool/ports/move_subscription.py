"""One live subscription to a game's move events."""

from gomoku_tool.models.move_event import MoveEvent


class MoveSubscription:
    """Blocking event source used by the turn waiter.

    Implementations run on the caller's worker thread; they must return within
    the given timeout so cancellation and deadlines stay responsive.
    """

    def get_event(self, timeout_seconds: float) -> MoveEvent | None:
        """Wait for the next move event.

        Args:
            timeout_seconds: Maximum time to block.

        Returns:
            The next event, or ``None`` when none arrived in time.

        Raises:
            EventStreamError: If the underlying transport failed.
        """
        ...

    def close(self) -> None:
        """Release the underlying connection; safe to call more than once."""
        ...
