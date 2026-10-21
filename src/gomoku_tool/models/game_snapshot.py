"""Immutable snapshot of one game, decoded from the engine's REST payload."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from gomoku_tool.models.move import Move
from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner


@dataclass(frozen=True)
class GameSnapshot:
    """Everything the business layer needs to know about one game.

    Attributes:
        game_id: The uuid the engine assigned to the game.
        board_size: Edge length of the square board.
        rule_variant: Rules configuration name, e.g. ``"standard"``.
        winner: Outcome reported by the engine.
        current_player: Side that must move next.
        board: Rows of cell values: ``0`` empty, ``1`` black, ``2`` white.
        moves: Played moves in chronological order.
    """

    game_id: str
    board_size: int
    rule_variant: str
    winner: Winner
    current_player: Side
    board: tuple[tuple[int, ...], ...]
    moves: tuple[Move, ...]

    @property
    def move_count(self) -> int:
        """Return the number of moves played so far."""
        return len(self.moves)

    @property
    def is_over(self) -> bool:
        """Whether the engine reports a terminal outcome."""
        return self.winner.is_over

    def is_turn_of(self, side: Side) -> bool:
        """Whether ``side`` may move now.

        Args:
            side: The side asking for the turn.

        Returns:
            ``True`` only for a running game whose ``current_player`` is
            ``side``.
        """
        return not self.is_over and self.current_player is side

    def cell_at(self, row: int, col: int) -> int:
        """Return the cell value at a 1-based coordinate.

        Args:
            row: 1-based row.
            col: 1-based column.

        Returns:
            ``0`` empty, ``1`` black or ``2`` white.

        Raises:
            IndexError: If the coordinate is outside the board.
        """
        # Bounds are checked explicitly: Python's negative indexing would
        # otherwise turn row ``0`` into the last row instead of an error.
        if not 1 <= row <= self.board_size or not 1 <= col <= self.board_size:
            raise IndexError(
                f"Cell ({row}, {col}) is outside the "
                f"{self.board_size}x{self.board_size} board."
            )
        return self.board[row - 1][col - 1]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Decode the nested ``SavedGame`` wire shape returned by the engine.

        Args:
            data: The JSON body with ``game_id``, ``config``, ``state`` and
                ``moves``.

        Returns:
            The decoded snapshot with tuple-backed board and history.

        Raises:
            ValueError: If a required field is missing or invalid, or if the
                board is not square and sized like ``board_size``.
        """
        try:
            config: Mapping[str, Any] = data["config"]
            state: Mapping[str, Any] = data["state"]
            board_size = int(config["board_size"])
            rows: Sequence[Sequence[Any]] = state["board"]
            board = tuple(tuple(int(cell) for cell in row) for row in rows)
            moves = tuple(Move.from_dict(move) for move in data["moves"])
            # A square board is a hard invariant of gomoku-core; refusing a
            # ragged board here keeps every later cell lookup in bounds.
            if len(board) != board_size or any(
                len(row) != board_size for row in board
            ):
                raise ValueError(
                    f"Board shape does not match board_size={board_size}."
                )
            return cls(
                game_id=str(data["game_id"]),
                board_size=board_size,
                rule_variant=str(config["rule_variant"]),
                winner=Winner.from_code(state["winner"]),
                current_player=Side.from_value(state["current_player"]),
                board=board,
                moves=moves,
            )
        except (KeyError, TypeError, ValueError) as exc:
            # Every decoding problem surfaces as one ValueError; the REST
            # client translates it into a user-facing EngineError.
            raise ValueError(f"Malformed game snapshot: {exc}") from exc
