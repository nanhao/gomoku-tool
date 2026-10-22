"""In-memory implementation of the move-event feed port."""

from gomoku_tool.errors.event_stream_error import EventStreamError
from tests.fakes.fake_move_subscription import FakeMoveSubscription


class FakeMoveEventFeed:
    """Hands out one stable fake subscription per game.

    Attributes:
        subscriptions: Subscriptions created so far, keyed by game id.
        subscribe_calls: Game ids passed to ``subscribe``, in order.
        fail_with: When set, ``subscribe`` raises this error, simulating an
            unreachable Redis instance.
    """

    def __init__(self, order: list[str] | None = None) -> None:
        """Create a feed with no subscriptions.

        Args:
            order: Optional shared log receiving one token per port call; it
                lets a test assert cross-port ordering (subscribe before read).
        """
        self.subscriptions: dict[str, FakeMoveSubscription] = {}
        self.subscribe_calls: list[str] = []
        self.fail_with: EventStreamError | None = None
        self._order: list[str] | None = order

    def subscribe(self, game_id: str) -> FakeMoveSubscription:
        """Return the game's subscription, creating it on first use.

        Args:
            game_id: Identifier of the game to observe.

        Returns:
            The stable fake subscription of that game.

        Raises:
            EventStreamError: The programmed ``fail_with`` error, when set.
        """
        self.subscribe_calls.append(game_id)
        if self._order is not None:
            self._order.append("subscribe")
        if self.fail_with is not None:
            raise self.fail_with
        if game_id not in self.subscriptions:
            self.subscriptions[game_id] = FakeMoveSubscription()
        return self.subscriptions[game_id]

    def subscription_for(self, game_id: str) -> FakeMoveSubscription:
        """Return the subscription of a game, creating it if necessary.

        Tests use this to queue events before the service subscribes.

        Args:
            game_id: Identifier of the game to observe.

        Returns:
            The game's stable fake subscription.
        """
        if game_id not in self.subscriptions:
            self.subscriptions[game_id] = FakeMoveSubscription()
        return self.subscriptions[game_id]
