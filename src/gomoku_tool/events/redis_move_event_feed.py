"""Factory of Redis-backed move-event subscriptions.

Opening a subscription is the moment the server may discover that Redis is
down. The feed confirms the connection with ``PING`` before handing the
handle to the business layer, so an unreachable Redis surfaces immediately as
an :class:`EventStreamError` (and the waiter polls the engine instead of
staring at a dead channel).
"""

from typing import ClassVar

import redis

from gomoku_tool.errors.event_stream_error import EventStreamError
from gomoku_tool.events.redis_move_subscription import RedisMoveSubscription
from gomoku_tool.ports.move_subscription import MoveSubscription


class RedisMoveEventFeed:
    """Implements :class:`MoveEventFeed` on one Redis instance.

    A single ``redis.Redis`` client is shared by every game; each game gets
    its own ``PubSub`` handle so channels never interfere.
    """

    # The engine uses the same channel template; see the README contract.
    CHANNEL_TEMPLATE: ClassVar[str] = "gomoku:games:{game_id}:events"

    # A local Redis either answers immediately or is not there; failing fast
    # keeps the tool call responsive when Redis is down.
    CONNECT_TIMEOUT_SECONDS: ClassVar[float] = 2.0

    def __init__(self, redis_url: str) -> None:
        """Create the client; no connection is opened until ``subscribe``.

        Args:
            redis_url: URL of the Redis instance the engine publishes to.
        """
        self._client: redis.Redis = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
        )

    def subscribe(self, game_id: str) -> MoveSubscription:
        """Open and confirm a subscription to one game's channel.

        Args:
            game_id: uuid of the game to observe.

        Returns:
            A subscription delivering events published from now on.

        Raises:
            EventStreamError: If Redis cannot be reached or the channel
                cannot be subscribed. The caller degrades to polling.
        """
        channel: str = self.CHANNEL_TEMPLATE.format(game_id=game_id)
        # ``ignore_subscribe_messages`` keeps confirmation frames out of the
        # event stream, so ``get_event`` only ever sees real move payloads.
        pubsub: redis.client.PubSub = self._client.pubsub(
            ignore_subscribe_messages=True
        )
        try:
            # redis-py connects lazily on the first command; PING is the
            # cheapest way to prove the instance is actually reachable.
            self._client.ping()
            pubsub.subscribe(channel)
        except (redis.RedisError, OSError) as exc:
            self._close_quietly(pubsub)
            raise EventStreamError(
                f"Cannot subscribe to {channel}: {exc}"
            ) from exc
        return RedisMoveSubscription(pubsub, game_id)

    def close(self) -> None:
        """Close the shared client and its connection pool (shutdown)."""
        self._client.close()

    @classmethod
    def _close_quietly(cls, pubsub: redis.client.PubSub) -> None:
        """Close a handle that never became a usable subscription.

        Args:
            pubsub: The half-open handle to release.
        """
        try:
            pubsub.close()
        except (redis.RedisError, OSError):
            # The handle is being discarded because Redis already failed;
            # a second failure while releasing it changes nothing.
            pass
