"""Tests for the game use-case orchestration."""

import threading
from collections import deque

import pytest

from gomoku_tool.business.game_service import GameService
from gomoku_tool.errors.engine_error import EngineError
from gomoku_tool.errors.event_stream_error import EventStreamError
from gomoku_tool.errors.game_error import GameError
from gomoku_tool.errors.turn_violation_error import TurnViolationError
from gomoku_tool.errors.wait_cancelled_error import WaitCancelledError
from gomoku_tool.models.launch_result import LaunchResult
from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner
from tests.fakes.fake_game_gateway import FakeGameGateway
from tests.fakes.fake_move_event_feed import FakeMoveEventFeed
from tests.fakes.fake_move_subscription import FakeMoveSubscription
from tests.fakes.fake_window_launcher import FakeWindowLauncher
from tests.fakes.snapshot_factory import SnapshotFactory


class TestGameService:
    """The service must own side ownership, waiting and session bookkeeping."""

    def _build(
        self,
        current=None,
        launcher: FakeWindowLauncher | None = None,
        order: list[str] | None = None,
    ) -> tuple[
        GameService, FakeGameGateway, FakeMoveEventFeed, FakeWindowLauncher
    ]:
        """Wire the service against in-memory ports."""
        gateway = FakeGameGateway(current=current, order=order)
        feed = FakeMoveEventFeed(order=order)
        window_launcher = launcher or FakeWindowLauncher()
        service = GameService(gateway, feed, window_launcher)
        return service, gateway, feed, window_launcher

    def test_start_game_returns_immediately_when_llm_is_black(self) -> None:
        """Black moves first, so the first tool call already ends at a turn."""
        order: list[str] = []
        empty = SnapshotFactory.empty(current_player=Side.BLACK)
        service, gateway, feed, launcher = self._build(
            current=empty, order=order
        )
        gateway.create_result = empty

        result = service.start_game(5, "black", timeout_seconds=60.0)

        assert result.snapshot is empty
        assert result.llm_side is Side.BLACK
        assert not result.timed_out
        assert gateway.created_sizes == [5]
        assert feed.subscribe_calls == ["g1"]
        assert launcher.launches == [("g1", Side.WHITE)]
        assert order.index("subscribe") < order.index("read")
        assert any("opened gomoku-ui" in note for note in result.notes)

    def test_start_game_waits_for_the_first_human_move_when_llm_is_white(
        self,
    ) -> None:
        """White waits until the human's opening move makes it white's turn."""
        initial = SnapshotFactory.empty(current_player=Side.BLACK)
        after = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)], current_player=Side.WHITE
        )
        service, gateway, feed, _ = self._build(current=initial)
        gateway.create_result = initial
        gateway.read_results = deque([initial, after])
        feed.subscription_for("g1").push(
            SnapshotFactory.event(
                1, 1, 1, player=Side.BLACK, next_player=Side.WHITE
            )
        )
        statuses: list[str] = []

        result = service.start_game(
            5, "white", timeout_seconds=5.0, status_sink=statuses.append
        )

        assert result.snapshot is after
        assert not result.timed_out
        assert result.snapshot.move_count == 1
        assert any("waiting for the human's move" in text for text in statuses)

    def test_ui_launch_failure_becomes_a_note_not_an_error(self) -> None:
        """A missing UI checkout must not invalidate the started game."""
        empty = SnapshotFactory.empty()
        launcher = FakeWindowLauncher(
            LaunchResult(
                started=False,
                command=("python", "play_game.py", "g1", "--side", "white"),
                error="python.exe not found",
            )
        )
        service, gateway, _, _ = self._build(current=empty, launcher=launcher)
        gateway.create_result = empty

        result = service.start_game(5, "black", timeout_seconds=0.0)

        joined = " ".join(result.notes)
        assert "did not open" in joined
        assert "python.exe not found" in joined
        assert "play_game.py" in joined

    def test_redis_failure_becomes_a_polling_note(self) -> None:
        """An unreachable Redis degrades to polling instead of failing."""
        empty = SnapshotFactory.empty()
        service, gateway, feed, _ = self._build(current=empty)
        gateway.create_result = empty
        feed.fail_with = EventStreamError("connection refused")

        result = service.start_game(5, "black", timeout_seconds=0.0)

        assert any("poll the engine" in note for note in result.notes)

    def test_make_move_rejects_foreign_turn_without_submitting(self) -> None:
        """The engine has no identity; the turn guard must protect the human."""
        current = SnapshotFactory.empty(current_player=Side.WHITE)
        service, gateway, _, _ = self._build(current=current)

        with pytest.raises(TurnViolationError, match="not your turn"):
            service.make_move("g1", 1, 1, "black", timeout_seconds=0.0)

        assert gateway.submitted == []

    def test_make_move_submits_then_waits_for_the_reply(self) -> None:
        """A move returns only once the human has answered."""
        before = SnapshotFactory.empty(current_player=Side.BLACK)
        submitted = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)], current_player=Side.WHITE
        )
        answered = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK), (2, 2, Side.WHITE)], current_player=Side.BLACK
        )
        service, gateway, feed, _ = self._build(current=before)
        gateway.read_results = deque([before, answered])
        gateway.submit_result = submitted
        feed.subscription_for("g1").push(
            SnapshotFactory.event(
                2, 2, 2, player=Side.WHITE, next_player=Side.BLACK
            )
        )

        result = service.make_move("g1", 1, 1, "black", timeout_seconds=5.0)

        assert gateway.submitted == [("g1", 1, 1)]
        assert result.snapshot is answered
        assert result.snapshot.move_count == 2
        assert not result.timed_out

    def test_make_move_returns_at_once_when_it_ends_the_game(self) -> None:
        """No wait is needed after a decisive move."""
        before = SnapshotFactory.empty(current_player=Side.BLACK)
        final = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)],
            current_player=Side.BLACK,
            winner=Winner.BLACK,
        )
        service, gateway, feed, _ = self._build(current=before)
        gateway.read_results = deque([before])
        gateway.submit_result = final

        result = service.make_move("g1", 1, 1, "black", timeout_seconds=5.0)

        assert result.snapshot is final
        assert result.snapshot.is_over
        assert feed.subscription_for("g1").wait_timeouts == []

    def test_make_move_surfaces_engine_rejections(self) -> None:
        """An illegal move is an EngineError from the adapter, unchanged."""
        before = SnapshotFactory.empty(current_player=Side.BLACK)
        service, gateway, _, _ = self._build(current=before)
        gateway.read_results = deque([before])
        gateway.submit_error = EngineError("illegal move", status_code=400)

        with pytest.raises(EngineError, match="illegal move"):
            service.make_move("g1", 1, 1, "black", timeout_seconds=0.0)

    def test_make_move_without_session_or_side_explains_how_to_attach(
        self,
    ) -> None:
        """After a restart the caller must say which side it plays."""
        service, gateway, _, _ = self._build(
            current=SnapshotFactory.empty()
        )

        with pytest.raises(GameError, match="llm_side"):
            service.make_move("g1", 1, 1, None, timeout_seconds=0.0)

        assert gateway.reads == []

    def test_make_move_reattaches_subscribe_before_read(self) -> None:
        """A fresh session must not miss a move between read and subscribe."""
        order: list[str] = []
        current = SnapshotFactory.empty(current_player=Side.WHITE)
        final = SnapshotFactory.with_moves(
            [(1, 1, Side.WHITE)],
            current_player=Side.WHITE,
            winner=Winner.WHITE,
        )
        service, gateway, feed, launcher = self._build(
            current=current, order=order
        )
        gateway.read_results = deque([current])
        gateway.submit_result = final

        result = service.make_move("g1", 1, 1, "white", timeout_seconds=0.0)

        assert result.snapshot.is_over
        assert gateway.submitted == [("g1", 1, 1)]
        assert order.index("subscribe") < order.index("read")
        assert launcher.launches == []

    def test_make_move_without_side_uses_the_session(self) -> None:
        """After start_game the side is remembered in-process."""
        empty = SnapshotFactory.empty(current_player=Side.BLACK)
        final = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)],
            current_player=Side.BLACK,
            winner=Winner.BLACK,
        )
        service, gateway, _, _ = self._build(current=empty)
        gateway.create_result = empty
        service.start_game(5, "black", timeout_seconds=0.0)
        gateway.read_results = deque([empty])
        gateway.submit_result = final

        result = service.make_move("g1", 1, 1, None, timeout_seconds=0.0)

        assert result.llm_side is Side.BLACK
        assert result.snapshot.is_over

    def test_the_subscription_is_reused_across_calls(self) -> None:
        """One Redis subscription per game, not one per tool call."""
        empty = SnapshotFactory.empty(current_player=Side.BLACK)
        final = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)],
            current_player=Side.BLACK,
            winner=Winner.BLACK,
        )
        service, gateway, feed, _ = self._build(current=empty)
        gateway.create_result = empty
        service.start_game(5, "black", timeout_seconds=0.0)
        gateway.read_results = deque([empty])
        gateway.submit_result = final

        service.make_move("g1", 1, 1, None, timeout_seconds=0.0)

        assert feed.subscribe_calls == ["g1"]

    def test_timeout_returns_a_note_instead_of_an_error(self) -> None:
        """A quiet human is a normal outcome; the LLM resumes with wait_for_turn."""
        before = SnapshotFactory.empty(current_player=Side.BLACK)
        after = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)], current_player=Side.WHITE
        )
        service, gateway, _, _ = self._build(current=before)
        gateway.read_results = deque([before])
        gateway.submit_result = after

        result = service.make_move("g1", 1, 1, "black", timeout_seconds=0.0)

        assert result.timed_out
        assert any("wait_for_turn" in note for note in result.notes)

    def test_wait_for_turn_returns_immediately_on_the_llm_turn(self) -> None:
        """Resuming when it is already the LLM's turn must not block."""
        empty = SnapshotFactory.empty(current_player=Side.BLACK)
        service, gateway, _, _ = self._build(current=empty)
        gateway.create_result = empty
        service.start_game(5, "black", timeout_seconds=0.0)

        result = service.wait_for_turn("g1", None, timeout_seconds=0.0)

        assert not result.timed_out
        assert result.llm_side is Side.BLACK
        assert result.snapshot.current_player is Side.BLACK

    def test_wait_for_turn_times_out_while_the_human_thinks(self) -> None:
        """Timeout is reported, never raised."""
        human_turn = SnapshotFactory.empty(current_player=Side.WHITE)
        service, gateway, _, _ = self._build(current=human_turn)

        result = service.wait_for_turn("g1", "black", timeout_seconds=0.0)

        assert result.timed_out
        assert result.snapshot.current_player is Side.WHITE
        assert any("wait_for_turn" in note for note in result.notes)

    def test_wait_for_turn_raises_when_the_task_is_cancelled(self) -> None:
        """Cancellation unwinds the worker so the task can end cancelled."""
        human_turn = SnapshotFactory.empty(current_player=Side.WHITE)
        service, gateway, _, _ = self._build(current=human_turn)
        stop_event = threading.Event()
        stop_event.set()

        with pytest.raises(WaitCancelledError):
            service.wait_for_turn(
                "g1", "black", timeout_seconds=10.0, stop_event=stop_event
            )

    def test_get_game_state_without_a_session_has_no_side(self) -> None:
        """Read-only state works after a restart, with an unknown side."""
        empty = SnapshotFactory.empty()
        service, gateway, _, _ = self._build(current=empty)

        result = service.get_game_state("g1")

        assert result.llm_side is None
        assert result.snapshot is empty
        assert not result.timed_out

    def test_get_game_state_uses_the_session_side(self) -> None:
        """A tracked game renders the LLM's side in the footer."""
        empty = SnapshotFactory.empty()
        service, gateway, _, _ = self._build(current=empty)
        gateway.create_result = empty
        service.start_game(5, "black", timeout_seconds=0.0)
        gateway.current = empty

        result = service.get_game_state("g1")

        assert result.llm_side is Side.BLACK

    def test_negative_timeout_is_rejected(self) -> None:
        """A negative budget is a caller error."""
        service, _, _, _ = self._build(current=SnapshotFactory.empty())

        with pytest.raises(GameError, match="timeout"):
            service.wait_for_turn("g1", "black", timeout_seconds=-5.0)
