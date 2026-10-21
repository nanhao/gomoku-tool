"""Builders for the immutable values exchanged by the business tests.

The factory only assembles data; it never decides rules. Turn alternation is
modelled mechanically (black moves first, sides alternate) so tests can focus
on the behavior under test instead of board bookkeeping.
"""

from collections.abc import Sequence

from gomoku_tool.models.game_snapshot import GameSnapshot
from gomoku_tool.models.move import Move
from gomoku_tool.models.move_event import MoveEvent
from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner


class SnapshotFactory:
    """Create snapshots, moves and events without a running engine."""

    @classmethod
    def empty(
        cls,
        game_id: str = "g1",
        board_size: int = 5,
        current_player: Side = Side.BLACK,
    ) -> GameSnapshot:
        """Return an empty square board whose turn is ``current_player``.

        Args:
            game_id: Identifier the engine would have assigned.
            board_size: Edge length of the square board.
            current_player: Side that must move next.

        Returns:
            A snapshot with no stones and no move history.
        """
        board: tuple[tuple[int, ...], ...] = tuple(
            tuple(0 for _ in range(board_size)) for _ in range(board_size)
        )
        return GameSnapshot(
            game_id=game_id,
            board_size=board_size,
            rule_variant="standard",
            winner=Winner.RUNNING,
            current_player=current_player,
            board=board,
            moves=(),
        )

    @classmethod
    def with_moves(
        cls,
        moves: Sequence[tuple[int, int, Side]],
        game_id: str = "g1",
        board_size: int = 5,
        current_player: Side | None = None,
        winner: Winner = Winner.RUNNING,
    ) -> GameSnapshot:
        """Return a snapshot with the given moves already played.

        Args:
            moves: ``(row, col, side)`` triples in chronological order, using
                1-based coordinates.
            game_id: Identifier the engine would have assigned.
            board_size: Edge length of the square board.
            current_player: Side to move next; ``None`` derives it from the
                move count (black starts, sides alternate).
            winner: Outcome reported by the engine.

        Returns:
            A snapshot whose board reflects every supplied move.
        """
        cells: list[list[int]] = [[0] * board_size for _ in range(board_size)]
        records: list[Move] = []
        for row, col, side in moves:
            cells[row - 1][col - 1] = int(side)
            records.append(Move(row=row, col=col, player=side))
        turn: Side = current_player or (
            Side.WHITE if len(records) % 2 == 1 else Side.BLACK
        )
        return GameSnapshot(
            game_id=game_id,
            board_size=board_size,
            rule_variant="standard",
            winner=winner,
            current_player=turn,
            board=tuple(tuple(row) for row in cells),
            moves=tuple(records),
        )

    @classmethod
    def event(
        cls,
        move_number: int,
        row: int,
        col: int,
        player: Side,
        next_player: Side,
        winner: Winner = Winner.RUNNING,
    ) -> MoveEvent:
        """Return the move event the engine would publish for one move.

        Args:
            move_number: 1-based position of the move in the game.
            row: 1-based row of the placed stone.
            col: 1-based column of the placed stone.
            player: Side that placed the stone.
            next_player: Side that must move next.
            winner: Outcome after the move; a finished winner also sets
                ``game_over``.

        Returns:
            The decoded event value.
        """
        return MoveEvent(
            game_id="g1",
            move_number=move_number,
            row=row,
            col=col,
            player=player,
            next_player=next_player,
            winner=winner,
            game_over=winner.is_over,
        )
