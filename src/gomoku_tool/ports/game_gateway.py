"""Business-facing interfaces implemented by the I/O adapters."""

from gomoku_tool.models.game_snapshot import GameSnapshot


class GameGateway:
    """The engine operations this server uses; no rules live behind it."""

    def create_game(self, board_size: int) -> GameSnapshot:
        """Create a new game and return its initial snapshot.

        Args:
            board_size: Edge length of the square board.

        Returns:
            The freshly created game.

        Raises:
            EngineError: If the engine rejects or cannot be reached.
        """
        ...

    def get_game(self, game_id: str) -> GameSnapshot:
        """Read the authoritative snapshot of one game.

        Args:
            game_id: uuid of the game.

        Returns:
            The current game state.

        Raises:
            EngineError: If the engine rejects or cannot be reached.
        """
        ...

    def submit_move(self, game_id: str, row: int, col: int) -> GameSnapshot:
        """Submit one move and return the updated snapshot.

        Args:
            game_id: uuid of the game.
            row: 1-based row of the stone.
            col: 1-based column of the stone.

        Returns:
            The state after the move was applied.

        Raises:
            EngineError: If the move is illegal or the engine fails.
        """
        ...
