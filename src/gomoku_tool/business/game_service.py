"""The game use cases: start, move, wait for the turn and read the state.

:class:`GameService` is the only business object the MCP adapter talks to. It
owns the sequence of engine reads and writes, keeps exactly one
:class:`GameSession` per game, and turns recoverable infrastructure failures
(Redis, gomoku-ui) into notes instead of errors. Game rules and board
bookkeeping stay in the engine: this layer only decides *when* to ask.
"""

import threading
from collections.abc import Callable

from gomoku_tool.business.game_session import GameSession
from gomoku_tool.business.service_messages import ServiceMessages
from gomoku_tool.business.session_registry import SessionRegistry
from gomoku_tool.business.turn_waiter import TurnWaiter
from gomoku_tool.errors.engine_error import EngineError
from gomoku_tool.errors.event_stream_error import EventStreamError
from gomoku_tool.errors.game_error import GameError
from gomoku_tool.errors.turn_violation_error import TurnViolationError
from gomoku_tool.errors.wait_cancelled_error import WaitCancelledError
from gomoku_tool.models.game_result import GameResult
from gomoku_tool.models.game_snapshot import GameSnapshot
from gomoku_tool.models.launch_result import LaunchResult
from gomoku_tool.models.side import Side
from gomoku_tool.models.wait_outcome import WaitOutcome
from gomoku_tool.ports.game_gateway import GameGateway
from gomoku_tool.ports.move_event_feed import MoveEventFeed
from gomoku_tool.ports.move_subscription import MoveSubscription
from gomoku_tool.ports.window_launcher import WindowLauncher


class GameService:
    """Orchestrates the tool-facing use cases of one MCP server process.

    The service is synchronous on purpose: the adapter runs each call in a
    worker thread, so the business layer never depends on an event loop. All
    port implementations are injected, which is what keeps this file free of
    HTTP, Redis and process-management imports.
    """

    def __init__(
        self,
        gateway: GameGateway,
        event_feed: MoveEventFeed,
        launcher: WindowLauncher,
        registry: SessionRegistry | None = None,
        waiter: TurnWaiter | None = None,
    ) -> None:
        """Wire the use cases to their secondary ports.

        Args:
            gateway: Authoritative engine client.
            event_feed: Factory of live move-event subscriptions.
            launcher: Starter of the human's gomoku-ui window.
            registry: Session store; a fresh one is created when omitted.
            waiter: Turn-wait strategy; one bound to ``gateway`` is created
                when omitted.
        """
        self._gateway: GameGateway = gateway
        self._event_feed: MoveEventFeed = event_feed
        self._launcher: WindowLauncher = launcher
        self._registry: SessionRegistry = registry or SessionRegistry()
        self._waiter: TurnWaiter = waiter or TurnWaiter(gateway)

    def start_game(
        self,
        board_size: int,
        llm_side: str | Side,
        timeout_seconds: float,
        status_sink: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> GameResult:
        """Create a game, open the human's window and wait for the first turn.

        The subscription is opened *before* the first snapshot is read, so a
        move published in between is never lost. Launching gomoku-ui is best
        effort: a missing checkout becomes a note, because the game itself is
        already alive in the engine.

        Args:
            board_size: Edge length of the square board.
            llm_side: Side the LLM plays; the human takes the other one.
            timeout_seconds: How long to wait for the first turn boundary.
            status_sink: Optional receiver of progress messages.
            stop_event: Optional flag set when the MCP task is cancelled.

        Returns:
            The state at the first turn boundary, with UI and fallback notes.

        Raises:
            GameError: If the side or the timeout argument is invalid.
            EngineError: If the engine cannot create or read the game.
            WaitCancelledError: If ``stop_event`` was set while waiting.
        """
        self._require_budget(timeout_seconds)
        side: Side = self._parse_side(llm_side)
        created: GameSnapshot = self._gateway.create_game(board_size)

        notes: list[str] = []
        session = GameSession(game_id=created.game_id, llm_side=side)
        session.subscription = self._open_subscription(created.game_id, notes)
        human_side: Side = side.other()
        launch: LaunchResult = self._launcher.launch(
            created.game_id, human_side
        )
        notes.append(self._launch_note(launch, human_side))

        session.last_snapshot = self._read_snapshot(session)
        self._registry.register(session)
        outcome: WaitOutcome = self._waiter.wait(
            session.subscription,
            side,
            session.last_snapshot,
            timeout_seconds,
            status_sink,
            stop_event,
        )
        return self._build_result(
            session, outcome, ServiceMessages.NOTE_START_TIMEOUT, notes
        )

    def make_move(
        self,
        game_id: str,
        row: int,
        col: int,
        llm_side: str | Side | None,
        timeout_seconds: float,
        status_sink: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> GameResult:
        """Submit the LLM's move, then wait for the human's reply.

        The turn is re-read and guarded immediately before the write: the
        engine has no player identity, so this guard is the only thing that
        stops the LLM from playing the human's stones. A decisive move returns
        without waiting; otherwise the call blocks until the next turn
        boundary, the game ends or the budget expires.

        Args:
            game_id: uuid of the game.
            row: 1-based row of the stone.
            col: 1-based column of the stone.
            llm_side: Side the LLM plays; ``None`` uses the tracked session.
            timeout_seconds: How long to wait for the human's reply.
            status_sink: Optional receiver of progress messages.
            stop_event: Optional flag set when the MCP task is cancelled.

        Returns:
            The state at the next turn boundary, with a note on timeout.

        Raises:
            GameError: If the side, the timeout or the turn is invalid.
            TurnViolationError: If the game is over or it is not the LLM's
                turn; no move is sent in that case.
            EngineError: If the engine rejects the move or cannot be reached.
            WaitCancelledError: If ``stop_event`` was set while waiting.
        """
        self._require_budget(timeout_seconds)
        notes: list[str] = []
        session, snapshot = self._ensure_session(game_id, llm_side, notes)
        with session.move_lock:
            self._guard_turn(session, snapshot)
            submitted: GameSnapshot = self._gateway.submit_move(
                game_id, row, col
            )
            session.last_snapshot = submitted
            outcome: WaitOutcome = (
                WaitOutcome(submitted)
                if submitted.is_over
                else self._waiter.wait(
                    session.subscription,
                    session.llm_side,
                    submitted,
                    timeout_seconds,
                    status_sink,
                    stop_event,
                )
            )
            return self._build_result(
                session, outcome, ServiceMessages.NOTE_TURN_TIMEOUT, notes
            )

    def wait_for_turn(
        self,
        game_id: str,
        llm_side: str | Side | None,
        timeout_seconds: float,
        status_sink: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> GameResult:
        """Wait until the LLM may move, or report that it still cannot.

        This is the resume tool: it is used after a timeout, after a cancelled
        MCP task, by clients without task support, and to re-attach to a game
        after a server restart (pass ``llm_side`` in that case).

        Args:
            game_id: uuid of the game.
            llm_side: Side the LLM plays; ``None`` uses the tracked session.
            timeout_seconds: Maximum time to wait; ``0`` only checks.
            status_sink: Optional receiver of progress messages.
            stop_event: Optional flag set when the MCP task is cancelled.

        Returns:
            The state at the next turn boundary, with a note on timeout.

        Raises:
            GameError: If the side or the timeout argument is invalid.
            TurnViolationError: Never raised here; the state is returned.
            EngineError: If reading the snapshot fails.
            WaitCancelledError: If ``stop_event`` was set while waiting.
        """
        self._require_budget(timeout_seconds)
        notes: list[str] = []
        session, snapshot = self._ensure_session(game_id, llm_side, notes)
        outcome: WaitOutcome = self._waiter.wait(
            session.subscription,
            session.llm_side,
            snapshot,
            timeout_seconds,
            status_sink,
            stop_event,
        )
        return self._build_result(session, outcome, ServiceMessages.NOTE_TURN_TIMEOUT, notes)

    def get_game_state(self, game_id: str) -> GameResult:
        """Read and render a game without writing or waiting.

        Used by clients that prefer polling the state themselves. With no
        tracked session the LLM side stays unknown, which is exactly the
        information a restarting client needs.

        Args:
            game_id: uuid of the game.

        Returns:
            The current snapshot, with the tracked side when there is one.

        Raises:
            EngineError: If reading the snapshot fails.
        """
        session: GameSession | None = self._registry.get(game_id)
        snapshot: GameSnapshot = self._gateway.get_game(game_id)
        if session is None:
            return GameResult(snapshot=snapshot)
        session.last_snapshot = snapshot
        if snapshot.is_over:
            # The game is finished: release the Redis handle but keep the
            # session so the footer still shows whose game it is.
            self._registry.release_subscription(session)
        return GameResult(snapshot=snapshot, llm_side=session.llm_side)

    def close(self) -> None:
        """Release every live subscription; called on server shutdown."""
        self._registry.close_all()

    def _ensure_session(
        self,
        game_id: str,
        llm_side: str | Side | None,
        notes: list[str],
    ) -> tuple[GameSession, GameSnapshot]:
        """Return the game's session with a fresh authoritative snapshot.

        A missing session is created (re-attach after a restart); an existing
        one keeps its subscription and only changes side when the caller says
        so. The subscription is opened before the read on purpose: between the
        read and a later subscribe a move could otherwise be published unseen.

        Args:
            game_id: uuid of the game.
            llm_side: Side the LLM plays, or ``None`` for the tracked side.
            notes: Sink for recoverable notes (Redis fallback).

        Returns:
            The session and the snapshot read after subscribing.

        Raises:
            GameError: If no session exists and no side was supplied.
            EngineError: If reading the snapshot fails.
        """
        side: Side = self._resolve_side(game_id, llm_side)
        session: GameSession | None = self._registry.get(game_id)
        if session is None:
            session = GameSession(game_id=game_id, llm_side=side)
        else:
            # An explicit side wins: it is how a restarted server re-attaches
            # to a game whose in-process session was lost.
            session.llm_side = side
        if session.subscription is None:
            # Either the first call of this session or a retry after Redis
            # was down; a failed attempt stays ``None`` and polling covers it.
            session.subscription = self._open_subscription(game_id, notes)
        snapshot: GameSnapshot = self._read_snapshot(session)
        session.last_snapshot = snapshot
        self._registry.register(session)
        return session, snapshot

    def _read_snapshot(self, session: GameSession) -> GameSnapshot:
        """Read a snapshot and keep the session's resources consistent.

        A stream opened just before a failed read must not stay alive: the
        call is about to fail, so its subscription is released and the next
        call re-opens it (or falls back to polling).

        Args:
            session: The session the snapshot belongs to; used for its id.

        Returns:
            The authoritative snapshot.

        Raises:
            EngineError: If the engine cannot be reached or rejects the read.
        """
        try:
            return self._gateway.get_game(session.game_id)
        except EngineError:
            self._registry.release_subscription(session)
            raise

    def _guard_turn(
        self, session: GameSession, snapshot: GameSnapshot
    ) -> None:
        """Refuse a move that the engine would attribute to the human.

        Args:
            session: The session submitting the move.
            snapshot: Authoritative state read just before the write.

        Raises:
            TurnViolationError: If the game is over or ``snapshot`` reports
                the human's turn.
        """
        if snapshot.is_over:
            self._registry.release_subscription(session)
            raise TurnViolationError(
                ServiceMessages.MESSAGE_GAME_OVER.format(
                    winner=snapshot.winner.label
                )
            )
        if not snapshot.is_turn_of(session.llm_side):
            raise TurnViolationError(
                ServiceMessages.MESSAGE_FOREIGN_TURN.format(
                    current=snapshot.current_player.label
                )
            )

    def _build_result(
        self,
        session: GameSession,
        outcome: WaitOutcome,
        timeout_note: str,
        notes: list[str],
    ) -> GameResult:
        """Turn a wait outcome into the rendered tool result.

        Args:
            session: The session the call operated on.
            outcome: How the wait ended and its snapshot.
            timeout_note: The note appended when the budget expired.
            notes: Notes collected by the caller (UI, Redis fallback).

        Returns:
            The result handed to the renderer.

        Raises:
            WaitCancelledError: If the MCP task cancelled the wait.
        """
        if outcome.cancelled:
            raise WaitCancelledError(ServiceMessages.MESSAGE_CANCELLED)
        snapshot: GameSnapshot = outcome.snapshot
        session.last_snapshot = snapshot
        if snapshot.is_over:
            # No further moves can arrive; release the Redis handle but keep
            # the session for the final snapshot and the side footer.
            self._registry.release_subscription(session)
        collected: list[str] = list(notes)
        if outcome.timed_out:
            collected.append(timeout_note)
        return GameResult(
            snapshot=snapshot,
            llm_side=session.llm_side,
            timed_out=outcome.timed_out,
            notes=tuple(collected),
        )

    def _resolve_side(
        self, game_id: str, llm_side: str | Side | None
    ) -> Side:
        """Pick the LLM side from the argument, falling back to the session.

        Args:
            game_id: uuid of the game.
            llm_side: Side supplied by the caller, if any.

        Returns:
            The side the LLM plays.

        Raises:
            GameError: If the side is invalid or unknown and untracked.
        """
        if llm_side is not None:
            return self._parse_side(llm_side)
        session: GameSession | None = self._registry.get(game_id)
        if session is None:
            raise GameError(
                ServiceMessages.MESSAGE_MISSING_SIDE.format(game_id=game_id)
            )
        return session.llm_side

    @staticmethod
    def _parse_side(llm_side: str | Side) -> Side:
        """Parse a tool-side argument into a :class:`Side`.

        Args:
            llm_side: A side value or one of its accepted spellings.

        Returns:
            The parsed side.

        Raises:
            GameError: If the value is not a known side.
        """
        try:
            return Side.from_value(llm_side)
        except ValueError as exc:
            raise GameError(str(exc)) from exc

    @staticmethod
    def _require_budget(timeout_seconds: float) -> None:
        """Reject a negative wait budget before any I/O happens.

        Args:
            timeout_seconds: Budget supplied by the caller.

        Raises:
            GameError: If the budget is negative.
        """
        if timeout_seconds < 0:
            raise GameError(
                ServiceMessages.MESSAGE_NEGATIVE_TIMEOUT.format(
                    value=timeout_seconds
                )
            )

    def _open_subscription(
        self, game_id: str, notes: list[str]
    ) -> MoveSubscription | None:
        """Open the game's event stream, degrading to polling on failure.

        Args:
            game_id: uuid of the game to observe.
            notes: Sink receiving the fallback note.

        Returns:
            The subscription, or ``None`` when Redis is unavailable.
        """
        try:
            return self._event_feed.subscribe(game_id)
        except EventStreamError as exc:
            notes.append(
                ServiceMessages.NOTE_EVENT_STREAM_FAILED.format(error=exc)
            )
            return None

    @staticmethod
    def _launch_note(launch: LaunchResult, human_side: Side) -> str:
        """Describe the outcome of a gomoku-ui launch attempt.

        Args:
            launch: Result returned by the launcher port.
            human_side: Side the human plays in the opened window.

        Returns:
            The note shown to the LLM below the board.
        """
        if launch.started:
            return ServiceMessages.NOTE_UI_OPENED.format(side=human_side.label)
        return ServiceMessages.NOTE_UI_FAILED.format(
            error=launch.error or "unknown error",
            command=launch.command_text,
        )
