"""In-memory implementation of the engine gateway port.

The fake is deliberately script-driven: each test queues the snapshots the
"engine" should return, so assertions stay about the service's behavior and
not about a second implementation of the game.
"""

from collections import deque

from gomoku_tool.errors.game_error import GameError
from gomoku_tool.models.game_snapshot import GameSnapshot


class FakeGameGateway:
    """Records calls and replays pre-programmed snapshots.

    Attributes:
        current: Snapshot returned when the read queue is empty.
        create_result: Snapshot returned by ``create_game``.
        submit_result: Snapshot returned by ``submit_move``.
        read_results: Snapshots consumed by consecutive ``get_game`` calls.
        create_error: Raised by ``create_game`` when set.
        submit_error: Raised by ``submit_move`` when set.
        created_sizes: Board sizes of every create call, in order.
        reads: Game ids of every read call, in order.
        submitted: ``(game_id, row, col)`` triples of every move call.
    """

    def __init__(
        self,
        current: GameSnapshot | None = None,
        order: list[str] | None = None,
    ) -> None:
        """Create a gateway with an optional fallback snapshot and call log.

        Args:
            current: Snapshot returned once the read queue is exhausted.
            order: Optional shared log receiving one token per port call; it
                lets a test assert cross-port ordering (subscribe before read).
        """
        self.current: GameSnapshot | None = current
        self.create_result: GameSnapshot | None = None
        self.submit_result: GameSnapshot | None = None
        self.read_results: deque[GameSnapshot] = deque()
        self.create_error: Exception | None = None
        self.submit_error: Exception | None = None
        self.created_sizes: list[int] = []
        self.reads: list[str] = []
        self.submitted: list[tuple[str, int, int]] = []
        self._order: list[str] | None = order

    def create_game(self, board_size: int) -> GameSnapshot:
        """Return the programmed creation result.

        Args:
            board_size: Edge length requested by the service.

        Returns:
            The programmed snapshot, also installed as ``current``.

        Raises:
            Exception: The programmed ``create_error`` when one is set.
        """
        self.created_sizes.append(board_size)
        self._record("create")
        if self.create_error is not None:
            raise self.create_error
        snapshot: GameSnapshot | None = self.create_result or self.current
        if snapshot is None:
            raise GameError("FakeGameGateway has no snapshot to create")
        self.current = snapshot
        return snapshot

    def get_game(self, game_id: str) -> GameSnapshot:
        """Return the next programmed snapshot.

        Args:
            game_id: Identifier of the game to read.

        Returns:
            The next queued snapshot, or ``current`` when the queue is empty.

        Raises:
            GameError: If no snapshot was programmed at all.
        """
        self.reads.append(game_id)
        self._record("read")
        if self.read_results:
            self.current = self.read_results.popleft()
        if self.current is None:
            raise GameError("FakeGameGateway has no snapshot to read")
        return self.current

    def submit_move(self, game_id: str, row: int, col: int) -> GameSnapshot:
        """Record a submitted move and return the programmed result.

        Args:
            game_id: Identifier of the game to continue.
            row: 1-based row of the stone.
            col: 1-based column of the stone.

        Returns:
            The programmed ``submit_result``, also installed as ``current``.

        Raises:
            Exception: The programmed ``submit_error`` when one is set.
        """
        self.submitted.append((game_id, row, col))
        self._record("submit")
        if self.submit_error is not None:
            raise self.submit_error
        snapshot: GameSnapshot | None = self.submit_result or self.current
        if snapshot is None:
            raise GameError("FakeGameGateway has no snapshot to submit")
        self.current = snapshot
        return snapshot

    def _record(self, token: str) -> None:
        """Append one token to the shared call log when logging is enabled.

        Args:
            token: Short name of the port call.
        """
        if self._order is not None:
            self._order.append(token)
