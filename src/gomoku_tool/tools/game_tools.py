"""MCP adapter: registers the gomoku tools and translates their arguments.

This is the only module that knows FastMCP. Each tool is a thin shell around
one :class:`GameService` call:

* the synchronous business call runs in ``asyncio.to_thread`` so a long wait
  never blocks the server's event loop;
* wait status is forwarded to the MCP task through :class:`ProgressBridge`;
* cancellation of the MCP task sets a ``threading.Event`` the waiter polls,
  so the worker unwinds instead of running until its timeout;
* expected failures become ``ToolError`` text for the LLM; unexpected ones
  propagate and surface as a broken tool.

The three waiting tools are declared with an optional ``TaskConfig``: clients
that support ``io.modelcontextprotocol/tasks`` get a background task, legacy
clients run them inline with a short wait budget.
"""

import asyncio
import functools
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import ClassVar

from fastmcp import Context, FastMCP
from fastmcp.dependencies import Progress
from fastmcp.exceptions import ToolError
from fastmcp.utilities.tasks import TaskConfig

from gomoku_tool.business.board_renderer import BoardRenderer
from gomoku_tool.business.game_service import GameService
from gomoku_tool.errors.game_error import GameError
from gomoku_tool.errors.wait_cancelled_error import WaitCancelledError
from gomoku_tool.models.game_result import GameResult
from gomoku_tool.tools.progress_bridge import ProgressBridge


class GameTools:
    """Registers the four gomoku tools on a FastMCP server."""

    # Tool defaults, matching the README surface.
    DEFAULT_BOARD_SIZE: ClassVar[int] = 15
    DEFAULT_LLM_SIDE: ClassVar[str] = "black"
    DEFAULT_TIMEOUT_SECONDS: ClassVar[float] = 600.0

    # Suggested client polling interval for task-augmented calls.
    TASK_POLL_SECONDS: ClassVar[float] = 2.0

    # Inline (non-task) call budgets. A legacy client has no way to observe a
    # background wait, so the call must answer quickly and let the LLM poll.
    IMMEDIATE_WAIT_SECONDS: ClassVar[float] = 0.0
    INLINE_WAIT_SECONDS: ClassVar[float] = 10.0

    def __init__(
        self, service: GameService, renderer: BoardRenderer
    ) -> None:
        """Create the adapter.

        Args:
            service: Business use cases to call.
            renderer: Renderer that turns a result into the board text.
        """
        self._service: GameService = service
        self._renderer: BoardRenderer = renderer

    def register(self, mcp: FastMCP) -> None:
        """Register every tool on the given server.

        Args:
            mcp: Server instance that will expose the tools.
        """
        mcp.tool(
            self.start_game,
            name="start_game",
            task=self._task_config(),
        )
        mcp.tool(
            self.make_move,
            name="make_move",
            task=self._task_config(),
        )
        mcp.tool(
            self.wait_for_turn,
            name="wait_for_turn",
            task=self._task_config(),
        )
        mcp.tool(self.get_game_state, name="get_game_state")

    async def start_game(
        self,
        ctx: Context,
        board_size: int = DEFAULT_BOARD_SIZE,
        llm_side: str = DEFAULT_LLM_SIDE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        progress: Progress = Progress(),
    ) -> str:
        """Create a game and open a gomoku-ui window for the human opponent.

        The server creates the game in gomoku-engine, opens the window for the
        opposite side, and returns at the first turn boundary: immediately
        when you play black (black moves first), otherwise as soon as the
        human's opening move makes it your turn.

        If the human does not move before ``timeout_seconds``, the tool still
        returns normally, with a note asking you to call ``wait_for_turn``.
        The game stays alive; nothing is lost.

        Args:
            board_size: Edge length of the square board (default 15).
            llm_side: Side you play: ``black`` (default) or ``white``.
            timeout_seconds: Maximum time to wait for the first turn.

        Returns:
            The rendered board, the game id, whose turn it is and any note
            about the UI window or a degraded event stream.
        """
        operation: Callable[
            [float, Callable[[str], None], threading.Event], GameResult
        ] = functools.partial(
            self._service.start_game, board_size, llm_side
        )
        return await self._execute(
            operation, timeout_seconds, ctx, progress, immediate=True
        )

    async def make_move(
        self,
        ctx: Context,
        game_id: str,
        row: int,
        col: int,
        llm_side: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        progress: Progress = Progress(),
    ) -> str:
        """Place one of your stones and wait for the human's reply.

        The server first verifies that it is really your turn (the engine has
        no player identity), submits the move, and returns when the human has
        answered or the game is over. A decisive move returns immediately.

        Coordinates are 1-based: ``row`` and ``col`` both start at 1, exactly
        like the labels of the rendered board. The target cell must be empty.

        Args:
            game_id: Game id returned by ``start_game``.
            row: 1-based row of the stone.
            col: 1-based column of the stone.
            llm_side: Your side; omit it to use the side remembered from
                ``start_game``. Pass it to re-attach after a restart.
            timeout_seconds: Maximum time to wait for the human's reply.

        Returns:
            The refreshed board after the human's answer, or after your move
            when the game ended; timeouts add a note to call
            ``wait_for_turn``.
        """
        operation: Callable[
            [float, Callable[[str], None], threading.Event], GameResult
        ] = functools.partial(
            self._service.make_move, game_id, row, col, llm_side
        )
        return await self._execute(
            operation, timeout_seconds, ctx, progress, immediate=True
        )

    async def wait_for_turn(
        self,
        ctx: Context,
        game_id: str,
        llm_side: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        progress: Progress = Progress(),
    ) -> str:
        """Wait until you may move again, or report that the human is thinking.

        Use this after a timeout, after a cancelled task, with a client that
        does not support MCP tasks, or to re-attach to a game after the server
        restarted (pass ``llm_side`` in that case). It returns immediately if
        it is already your turn or the game is over.

        Args:
            game_id: Game id returned by ``start_game``.
            llm_side: Your side; omit it when this server still remembers the
                game.
            timeout_seconds: Maximum time to wait.

        Returns:
            The current board at the next turn boundary, or the unchanged
            board with a note when the timeout expires first.
        """
        operation: Callable[
            [float, Callable[[str], None], threading.Event], GameResult
        ] = functools.partial(
            self._service.wait_for_turn, game_id, llm_side
        )
        return await self._execute(
            operation, timeout_seconds, ctx, progress, immediate=False
        )

    def get_game_state(self, game_id: str) -> str:
        """Read the current state of a game without writing anything.

        Useful for polling clients and for inspecting a game whose session
        this server no longer remembers: in that case the footer reports the
        side as unknown.

        Args:
            game_id: Game id returned by ``start_game``.

        Returns:
            The rendered board and footer of the authoritative snapshot.
        """
        try:
            result: GameResult = self._service.get_game_state(game_id)
        except GameError as exc:
            raise ToolError(str(exc)) from exc
        return self._renderer.render(result)

    async def _execute(
        self,
        operation: Callable[
            [float, Callable[[str], None], threading.Event], GameResult
        ],
        timeout_seconds: float,
        ctx: Context,
        progress: Progress,
        immediate: bool,
    ) -> str:
        """Run one business call in a worker thread and render its result.

        Args:
            operation: The service call, bound to its non-wait arguments; it
                receives the wait budget, the status sink and the stop event.
            timeout_seconds: Budget requested by the caller.
            ctx: Tool context, used to detect inline execution.
            progress: Task progress handle forwarded to ``ProgressBridge``.
            immediate: Whether an inline call must return without waiting.

        Returns:
            The rendered board text.

        Raises:
            ToolError: If the business layer reports an expected failure.
        """
        budget: float = self._budget(timeout_seconds, ctx, immediate)
        stop_event = threading.Event()
        bridge = ProgressBridge(asyncio.get_running_loop(), progress)
        try:
            result: GameResult = await asyncio.to_thread(
                operation, budget, bridge, stop_event
            )
        except asyncio.CancelledError:
            # Cooperative cancel: the waiter stops at its next slice boundary
            # and the game, the session and the UI window stay untouched.
            stop_event.set()
            raise
        except WaitCancelledError as exc:
            # The worker noticed the cancellation just before the event loop
            # delivered it; report the call as cancelled, not as a failure.
            raise asyncio.CancelledError(str(exc)) from exc
        except GameError as exc:
            raise ToolError(str(exc)) from exc
        return self._renderer.render(result)

    @classmethod
    def _budget(
        cls, timeout_seconds: float, ctx: Context, immediate: bool
    ) -> float:
        """Choose the wait budget for the current execution mode.

        Args:
            timeout_seconds: Budget requested by the caller.
            ctx: Tool context; background tasks may wait the full budget.
            immediate: Whether an inline call must return without waiting.

        Returns:
            The budget handed to the business layer.
        """
        if ctx.is_background_task:
            # The client polls tasks/get, so a long wait costs nothing.
            return timeout_seconds
        if immediate:
            return cls.IMMEDIATE_WAIT_SECONDS
        return min(timeout_seconds, cls.INLINE_WAIT_SECONDS)

    @classmethod
    def _task_config(cls) -> TaskConfig:
        """Build a fresh task configuration for one waiting tool.

        Returns:
            ``optional`` mode with the documented polling interval.
        """
        return TaskConfig(
            mode="optional",
            poll_interval=timedelta(seconds=cls.TASK_POLL_SECONDS),
        )
