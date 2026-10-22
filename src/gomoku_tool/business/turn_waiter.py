"""Waiting for the human, without ever blocking past a turn boundary.

The waiter is the heart of the server's turn loop. It is deliberately ignorant
of Redis: it consumes a :class:`MoveSubscription` port, treats events as
wake-up signals only, and treats the engine snapshot as the truth. When the
stream is silent or broken it polls instead, so a Redis outage can delay a
turn but never lose it.
"""

import threading
import time
from collections.abc import Callable
from typing import Final

from gomoku_tool.errors.event_stream_error import EventStreamError
from gomoku_tool.models.game_snapshot import GameSnapshot
from gomoku_tool.models.side import Side
from gomoku_tool.models.wait_outcome import WaitOutcome
from gomoku_tool.ports.game_gateway import GameGateway
from gomoku_tool.ports.move_subscription import MoveSubscription


class TurnWaiter:
    """Blocks until the LLM may move, the game ends, the deadline or a cancel."""

    # One event poll slice. It bounds cancellation latency and lets the loop
    # check its deadline even while the Redis channel is quiet.
    EVENT_POLL_SECONDS: Final[float] = 0.5

    # How often the authoritative snapshot is re-read while waiting. This is
    # the fallback when Redis is down and the repair path when events are lost.
    SNAPSHOT_POLL_SECONDS: Final[float] = 2.0

    def __init__(
        self,
        gateway: GameGateway,
        event_poll_seconds: float = EVENT_POLL_SECONDS,
        snapshot_poll_seconds: float = SNAPSHOT_POLL_SECONDS,
    ) -> None:
        """Create a waiter bound to one engine gateway.

        Args:
            gateway: Authoritative source of snapshots.
            event_poll_seconds: Longest single event wait; must be positive.
            snapshot_poll_seconds: Interval of snapshot polling; must be
                positive.

        Raises:
            ValueError: If a poll interval is not positive.
        """
        if event_poll_seconds <= 0 or snapshot_poll_seconds <= 0:
            raise ValueError("Poll intervals must be positive.")
        self._gateway: GameGateway = gateway
        self._event_poll_seconds: float = event_poll_seconds
        self._snapshot_poll_seconds: float = snapshot_poll_seconds

    def wait(
        self,
        subscription: MoveSubscription | None,
        llm_side: Side,
        snapshot: GameSnapshot,
        timeout_seconds: float,
        status_sink: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> WaitOutcome:
        """Wait until it is ``llm_side``'s turn or the game is over.

        Args:
            subscription: Live event source, or ``None`` to poll only.
            llm_side: The LLM's side; the wait ends when it may move.
            snapshot: Most recent authoritative snapshot.
            timeout_seconds: Maximum time to wait; ``0`` only checks the
                current state.
            status_sink: Optional receiver of progress messages (task status).
            stop_event: Optional flag set by the MCP adapter on cancellation.

        Returns:
            How the wait ended and the latest snapshot.

        Raises:
            ValueError: If ``timeout_seconds`` is negative.
            EngineError: If polling the snapshot fails.
        """
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be zero or positive.")
        deadline: float = time.monotonic() + timeout_seconds
        current: GameSnapshot = snapshot
        last_poll: float = time.monotonic()
        last_move_count: int = -1
        stream_alive: bool = subscription is not None

        while True:
            # Cancellation is checked before anything else so a cancelled task
            # stops at the next slice boundary even on a quiet channel.
            if stop_event is not None and stop_event.is_set():
                return WaitOutcome(current, timed_out=False, cancelled=True)
            if self._is_terminal(current, llm_side):
                return WaitOutcome(current)
            remaining: float = deadline - time.monotonic()
            if remaining <= 0:
                return WaitOutcome(current, timed_out=True)
            if current.move_count != last_move_count:
                # The message names the move the human is answering, which is
                # what a polling client shows while the task is "working".
                self._emit(
                    status_sink,
                    f"waiting for the human's move, move {current.move_count}",
                )
                last_move_count = current.move_count

            event = None
            if stream_alive and subscription is not None:
                try:
                    event = subscription.get_event(
                        min(remaining, self._event_poll_seconds)
                    )
                except EventStreamError as exc:
                    stream_alive = False
                    self._emit(
                        status_sink,
                        f"live move events unavailable ({exc}); "
                        "falling back to snapshot polling",
                    )

            now: float = time.monotonic()
            if event is not None and event.player is not llm_side:
                self._emit(
                    status_sink,
                    f"human played {event.player.move_label}"
                    f"({event.row},{event.col})",
                )
            if event is not None and event.ends_wait_for(llm_side):
                # The event says the boundary was reached; the snapshot must
                # confirm it, and is also the board the tool returns.
                current = self._gateway.get_game(current.game_id)
                last_poll = now
                continue

            # Poll when the stream is gone, or periodically to repair gaps
            # caused by best-effort publishing and reconnects.
            if not stream_alive or now - last_poll >= self._snapshot_poll_seconds:
                current = self._gateway.get_game(current.game_id)
                last_poll = now

    @classmethod
    def _is_terminal(cls, snapshot: GameSnapshot, llm_side: Side) -> bool:
        """Whether waiting is unnecessary for this snapshot.

        Args:
            snapshot: The snapshot to inspect.
            llm_side: The LLM's side.

        Returns:
            ``True`` when the game is over or the LLM moves next.
        """
        return snapshot.is_over or snapshot.is_turn_of(llm_side)

    @classmethod
    def _emit(
        cls, status_sink: Callable[[str], None] | None, message: str
    ) -> None:
        """Send one status message when a sink is configured.

        Args:
            status_sink: Optional receiver; ``None`` disables reporting.
            message: The message to report.
        """
        if status_sink is not None:
            status_sink(message)
