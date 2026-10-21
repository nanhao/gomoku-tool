"""Tests for the turn-waiting algorithm."""

import threading
import time
from collections import deque

import pytest

from gomoku_tool.business.turn_waiter import TurnWaiter
from gomoku_tool.errors.event_stream_error import EventStreamError
from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner
from tests.fakes.fake_game_gateway import FakeGameGateway
from tests.fakes.fake_move_subscription import FakeMoveSubscription
from tests.fakes.snapshot_factory import SnapshotFactory


class TestTurnWaiter:
    """Waiting must end exactly at a turn boundary, never earlier."""

    def _waiter(
        self,
        gateway: FakeGameGateway,
        event_poll_seconds: float = 0.01,
        snapshot_poll_seconds: float = 10.0,
    ) -> TurnWaiter:
        """Build a waiter with tiny polls so tests stay fast."""
        return TurnWaiter(
            gateway,
            event_poll_seconds=event_poll_seconds,
            snapshot_poll_seconds=snapshot_poll_seconds,
        )

    def test_returns_immediately_when_it_is_already_the_llm_turn(self) -> None:
        """No event is consumed when the snapshot already says 'your turn'."""
        gateway = FakeGameGateway()
        subscription = FakeMoveSubscription()
        snapshot = SnapshotFactory.empty(current_player=Side.BLACK)

        outcome = self._waiter(gateway).wait(
            subscription, Side.BLACK, snapshot, timeout_seconds=5.0
        )

        assert outcome.snapshot is snapshot
        assert not outcome.timed_out
        assert not outcome.cancelled
        assert subscription.wait_timeouts == []

    def test_returns_immediately_when_the_game_is_over(self) -> None:
        """A finished game never waits for a next move."""
        gateway = FakeGameGateway()
        snapshot = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)],
            current_player=Side.BLACK,
            winner=Winner.BLACK,
        )

        outcome = self._waiter(gateway).wait(
            FakeMoveSubscription(), Side.WHITE, snapshot, timeout_seconds=5.0
        )

        assert outcome.snapshot is snapshot
        assert not outcome.timed_out

    def test_a_qualifying_event_wakes_the_waiter_and_refreshes(self) -> None:
        """The event only wakes the waiter; the snapshot stays authoritative."""
        gateway = FakeGameGateway()
        initial = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)], current_player=Side.WHITE
        )
        refreshed = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK), (3, 3, Side.WHITE)], current_player=Side.BLACK
        )
        gateway.read_results = deque([refreshed])
        subscription = FakeMoveSubscription()
        subscription.push(
            SnapshotFactory.event(
                2, 3, 3, player=Side.WHITE, next_player=Side.BLACK
            )
        )
        statuses: list[str] = []

        outcome = self._waiter(gateway).wait(
            subscription,
            Side.BLACK,
            initial,
            timeout_seconds=2.0,
            status_sink=statuses.append,
        )

        assert outcome.snapshot is refreshed
        assert not outcome.timed_out
        assert gateway.reads == ["g1"]
        assert any("waiting for the human's move" in message for message in statuses)
        assert any("human played W(3,3)" in message for message in statuses)

    def test_a_game_over_event_also_wakes_the_waiter(self) -> None:
        """The human's winning move ends the wait and returns the final board."""
        gateway = FakeGameGateway()
        initial = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)], current_player=Side.WHITE
        )
        final = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK), (3, 3, Side.WHITE)],
            current_player=Side.WHITE,
            winner=Winner.WHITE,
        )
        gateway.read_results = deque([final])
        subscription = FakeMoveSubscription()
        subscription.push(
            SnapshotFactory.event(
                2,
                3,
                3,
                player=Side.WHITE,
                next_player=Side.WHITE,
                winner=Winner.WHITE,
            )
        )

        outcome = self._waiter(gateway).wait(
            subscription, Side.BLACK, initial, timeout_seconds=2.0
        )

        assert outcome.snapshot is final
        assert not outcome.timed_out

    def test_unrelated_events_are_ignored(self) -> None:
        """A stale event that does not hand the turn over must not end the wait."""
        gateway = FakeGameGateway()
        initial = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)], current_player=Side.WHITE
        )
        refreshed = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK), (2, 2, Side.WHITE)], current_player=Side.BLACK
        )
        gateway.read_results = deque([refreshed])
        subscription = FakeMoveSubscription()
        # Echo of the LLM's own move: next player is still the human.
        subscription.push(
            SnapshotFactory.event(
                1, 1, 1, player=Side.BLACK, next_player=Side.WHITE
            )
        )
        subscription.push(
            SnapshotFactory.event(
                2, 2, 2, player=Side.WHITE, next_player=Side.BLACK
            )
        )

        outcome = self._waiter(gateway).wait(
            subscription, Side.BLACK, initial, timeout_seconds=2.0
        )

        assert outcome.snapshot is refreshed
        assert gateway.reads == ["g1"]

    def test_times_out_without_an_event(self) -> None:
        """A quiet channel must not hold the caller past its deadline."""
        gateway = FakeGameGateway()
        initial = SnapshotFactory.empty(current_player=Side.WHITE)
        started = time.monotonic()

        outcome = self._waiter(gateway).wait(
            FakeMoveSubscription(), Side.BLACK, initial, timeout_seconds=0.05
        )

        assert outcome.timed_out
        assert not outcome.cancelled
        assert time.monotonic() - started < 1.0

    def test_polling_detects_a_move_when_events_are_lost(self) -> None:
        """The snapshot is the guarantee when Redis delivers nothing."""
        gateway = FakeGameGateway()
        initial = SnapshotFactory.empty(current_player=Side.WHITE)
        refreshed = SnapshotFactory.with_moves(
            [(2, 2, Side.WHITE)], current_player=Side.BLACK
        )
        gateway.read_results = deque([refreshed])

        outcome = self._waiter(
            gateway, snapshot_poll_seconds=0.01
        ).wait(
            FakeMoveSubscription(),
            Side.BLACK,
            initial,
            timeout_seconds=1.0,
        )

        assert outcome.snapshot is refreshed
        assert not outcome.timed_out
        assert gateway.reads == ["g1"]

    def test_stream_failure_falls_back_to_polling(self) -> None:
        """A dead Redis subscription is not fatal: polling takes over."""
        gateway = FakeGameGateway()
        initial = SnapshotFactory.empty(current_player=Side.WHITE)
        refreshed = SnapshotFactory.with_moves(
            [(2, 2, Side.WHITE)], current_player=Side.BLACK
        )
        gateway.read_results = deque([refreshed])
        subscription = FakeMoveSubscription()
        subscription.error = EventStreamError("redis down")
        statuses: list[str] = []

        outcome = self._waiter(
            gateway, snapshot_poll_seconds=0.01
        ).wait(
            subscription,
            Side.BLACK,
            initial,
            timeout_seconds=1.0,
            status_sink=statuses.append,
        )

        assert outcome.snapshot is refreshed
        assert not outcome.timed_out
        assert any("polling" in message for message in statuses)

    def test_cancellation_stops_the_wait(self) -> None:
        """A cancelled MCP task stops waiting without touching the game."""
        gateway = FakeGameGateway()
        initial = SnapshotFactory.empty(current_player=Side.WHITE)
        stop_event = threading.Event()
        stop_event.set()

        outcome = self._waiter(gateway).wait(
            FakeMoveSubscription(),
            Side.BLACK,
            initial,
            timeout_seconds=10.0,
            stop_event=stop_event,
        )

        assert outcome.cancelled
        assert not outcome.timed_out
        assert gateway.reads == []

    def test_negative_timeout_is_rejected(self) -> None:
        """A negative wait budget is a programming error, not a timeout."""
        with pytest.raises(ValueError):
            self._waiter(FakeGameGateway()).wait(
                FakeMoveSubscription(),
                Side.BLACK,
                SnapshotFactory.empty(current_player=Side.WHITE),
                timeout_seconds=-1.0,
            )
