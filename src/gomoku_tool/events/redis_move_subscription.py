"""One game's live move-event subscription on Redis pub/sub.

The adapter owns the channel mechanics only: wait for one message, decode the
JSON the engine publishes and return the value object. It never reads the
game state; the snapshot remains authoritative.
"""

import json
import threading
from typing import Any, ClassVar

import redis

from gomoku_tool.errors.event_stream_error import EventStreamError
from gomoku_tool.models.move_event import MoveEvent


class RedisMoveSubscription:
    """A :class:`MoveSubscription` backed by an open ``PubSub`` handle.

    ``redis-py`` pub/sub handles are not safe for concurrent readers, so a
    lock serializes ``get_event`` calls: two tool calls for the same game must
    not steal each other's events.
    """

    # How the engine addresses a game's event stream (see README).
    CHANNEL_TEMPLATE: ClassVar[str] = "gomoku:games:{game_id}:events"

    def __init__(self, pubsub: redis.client.PubSub, game_id: str) -> None:
        """Create a subscription around an already-subscribed handle.

        Args:
            pubsub: Pub/sub handle subscribed to the game's channel.
            game_id: uuid of the observed game; used for the channel name and
                error messages.
        """
        self._pubsub: redis.client.PubSub = pubsub
        self._channel: str = self.CHANNEL_TEMPLATE.format(game_id=game_id)
        self._lock: threading.Lock = threading.Lock()

    def get_event(self, timeout_seconds: float) -> MoveEvent | None:
        """Wait up to ``timeout_seconds`` for the next move event.

        Args:
            timeout_seconds: Maximum blocking time; non-positive values only
                poll the already-buffered messages.

        Returns:
            The decoded move event, or ``None`` when none arrived in time.
            Non-move payloads (pings, other event names) are skipped as
            ``None`` because they are not turn boundaries.

        Raises:
            EventStreamError: If the connection fails or the payload cannot
                be decoded. The waiter answers this by polling the engine.
        """
        with self._lock:
            try:
                message: dict[str, Any] | None = self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=max(0.0, timeout_seconds),
                )
            except (redis.RedisError, OSError) as exc:
                raise EventStreamError(
                    f"Redis move events are unavailable on {self._channel}: "
                    f"{exc}"
                ) from exc
        if message is None:
            return None
        return self._decode(message)

    def close(self) -> None:
        """Release the pub/sub handle, ignoring an already-dead connection."""
        try:
            self._pubsub.close()
        except (redis.RedisError, OSError):
            # Closing a broken connection is not a failure worth reporting:
            # the game is untouched and polling still works.
            pass

    def _decode(self, message: dict[str, Any]) -> MoveEvent | None:
        """Decode one pub/sub message into a value object.

        Args:
            message: The raw message mapping returned by ``get_message``.

        Returns:
            The move event, or ``None`` for a non-move payload.

        Raises:
            EventStreamError: If the payload is not a JSON object or lacks
                the required move fields.
        """
        data: Any = message.get("data")
        try:
            payload: Any = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("payload is not a JSON object")
            return MoveEvent.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise EventStreamError(
                f"Undecodable move event on {self._channel}: {exc}"
            ) from exc
