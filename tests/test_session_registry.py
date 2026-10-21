"""Tests for the in-process game session registry."""

from gomoku_tool.business.game_session import GameSession
from gomoku_tool.business.session_registry import SessionRegistry
from gomoku_tool.models.side import Side
from tests.fakes.fake_move_subscription import FakeMoveSubscription


class TestSessionRegistry:
    """Sessions are looked up by game id and never leak subscriptions."""

    def test_register_and_get(self) -> None:
        """A registered session is returned for its game id."""
        registry = SessionRegistry()
        session = GameSession(game_id="g1", llm_side=Side.BLACK)

        assert registry.register(session) is session
        assert registry.get("g1") is session

    def test_unknown_game_returns_none(self) -> None:
        """An unknown game has no session, which drives the re-attach flow."""
        assert SessionRegistry().get("missing") is None

    def test_replacing_a_session_closes_the_old_subscription(self) -> None:
        """A second registration must release the previous Redis handle."""
        registry = SessionRegistry()
        old_subscription = FakeMoveSubscription()
        new_subscription = FakeMoveSubscription()
        registry.register(
            GameSession("g1", Side.BLACK, subscription=old_subscription)
        )

        replacement = registry.register(
            GameSession("g1", Side.BLACK, subscription=new_subscription)
        )

        assert old_subscription.closed
        assert registry.get("g1") is replacement

    def test_remove_closes_the_subscription(self) -> None:
        """Removing a game releases its subscription."""
        registry = SessionRegistry()
        subscription = FakeMoveSubscription()
        registry.register(GameSession("g1", Side.WHITE, subscription=subscription))

        registry.remove("g1")

        assert subscription.closed
        assert registry.get("g1") is None

    def test_close_all_closes_every_subscription(self) -> None:
        """Server shutdown releases all Redis handles."""
        registry = SessionRegistry()
        first = FakeMoveSubscription()
        second = FakeMoveSubscription()
        registry.register(GameSession("g1", Side.BLACK, subscription=first))
        registry.register(GameSession("g2", Side.WHITE, subscription=second))

        registry.close_all()

        assert first.closed
        assert second.closed
        assert registry.get("g1") is None
