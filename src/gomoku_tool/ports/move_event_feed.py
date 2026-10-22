"""Factory that opens move-event subscriptions."""

from gomoku_tool.ports.move_subscription import MoveSubscription


class MoveEventFeed:
    """Opens subscriptions, possibly on a shared Redis connection."""

    def subscribe(self, game_id: str) -> MoveSubscription:
        """Open a subscription to one game's move events.

        Args:
            game_id: uuid of the game to observe.

        Returns:
            A subscription that delivers events published from now on.

        Raises:
            EventStreamError: If the stream cannot be opened at all.
        """
        ...
