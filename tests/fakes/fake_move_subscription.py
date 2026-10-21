"""In-memory move-event subscription used by the turn-waiter tests."""

import queue

from gomoku_tool.errors.event_stream_error import EventStreamError
from gomoku_tool.models.move_event import MoveEvent


class FakeMoveSubscription:
    """Queue-backed subscription with injectable transport failures.

    Attributes:
        closed: Whether ``close`` has been called.
        error: When set, every ``get_event`` raises this error instead of
            waiting, simulating a Redis outage.
        wait_timeouts: Timeout argument of every ``get_event`` call.
    """

    def __init__(self) -> None:
        """Create an empty, open subscription."""
        self._events: queue.Queue[MoveEvent] = queue.Queue()
        self.closed: bool = False
        self.error: EventStreamError | None = None
        self.wait_timeouts: list[float] = []

    def push(self, event: MoveEvent) -> None:
        """Queue one event as if the engine had just published it.

        Args:
            event: The decoded move event to deliver.
        """
        self._events.put(event)

    def get_event(self, timeout_seconds: float) -> MoveEvent | None:
        """Return the next queued event, waiting up to the timeout.

        Args:
            timeout_seconds: Maximum time to block; non-positive values only
                poll the queue.

        Returns:
            The next event, or ``None`` when none arrived in time.

        Raises:
            EventStreamError: The programmed transport failure, when set.
        """
        self.wait_timeouts.append(timeout_seconds)
        if self.error is not None:
            raise self.error
        try:
            return self._events.get(timeout=max(0.0, timeout_seconds))
        except queue.Empty:
            return None

    def close(self) -> None:
        """Mark the subscription as closed."""
        self.closed = True
