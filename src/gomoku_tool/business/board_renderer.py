"""Rendering a game result as the text the LLM sees."""

from typing import ClassVar

from gomoku_tool.models.game_result import GameResult
from gomoku_tool.models.game_snapshot import GameSnapshot
from gomoku_tool.models.move import Move
from gomoku_tool.models.side import Side


class BoardRenderer:
    """Produces the stable ASCII board and footer used by every tool."""

    # Cell symbols; the engine codes map to sides and to these characters.
    EMPTY_SYMBOL: ClassVar[str] = "."
    CELL_WIDTH: ClassVar[int] = 3
    ROW_LABEL_WIDTH: ClassVar[int] = 2

    def render(self, result: GameResult) -> str:
        """Render a tool result.

        Args:
            result: Snapshot, LLM side, timeout flag and notes.

        Returns:
            The multi-line text returned to the LLM.
        """
        snapshot: GameSnapshot = result.snapshot
        lines: list[str] = [self._header(snapshot.board_size)]
        for index, row in enumerate(snapshot.board, start=1):
            lines.append(self._row(index, row))
        lines.append(f"game_id: {snapshot.game_id}")
        lines.append(self._side_line(result))
        lines.append(
            f"winner: {int(snapshot.winner)} ({snapshot.winner.label})"
        )
        lines.append(self._moves_line(snapshot.moves))
        for note in result.notes:
            lines.append(f"note: {note}")
        return "\n".join(lines)

    @classmethod
    def _header(cls, board_size: int) -> str:
        """Render the column-number header.

        Args:
            board_size: Number of columns.

        Returns:
            A line with every 1-based column right-aligned in its cell.
        """
        label_padding: str = " " * (cls.ROW_LABEL_WIDTH + 1)
        columns: str = "".join(
            f"{column:>{cls.CELL_WIDTH}}"
            for column in range(1, board_size + 1)
        )
        return f"{label_padding}{columns}"

    @classmethod
    def _row(cls, index: int, row: tuple[int, ...]) -> str:
        """Render one board row with its 1-based label.

        Args:
            index: 1-based row number.
            row: Cell values of that row.

        Returns:
            The rendered row.
        """
        cells: str = "".join(
            f"{cls._symbol(cell):>{cls.CELL_WIDTH}}" for cell in row
        )
        return f"{index:>{cls.ROW_LABEL_WIDTH}} {cells}"

    @classmethod
    def _symbol(cls, cell: int) -> str:
        """Translate one engine cell value into its board symbol.

        Args:
            cell: ``0`` empty, ``1`` black or ``2`` white.

        Returns:
            ``.``, ``X`` or ``O``.
        """
        if cell == 0:
            return cls.EMPTY_SYMBOL
        try:
            return Side(cell).symbol
        except ValueError:
            # Cell values are validated by the engine; an unexpected code is
            # rendered as empty instead of crashing the whole result.
            return cls.EMPTY_SYMBOL

    @classmethod
    def _side_line(cls, result: GameResult) -> str:
        """Render the ``you`` / ``current_player`` footer line.

        Args:
            result: The tool result being rendered.

        Returns:
            One footer line explaining who the LLM is and who moves next.
        """
        snapshot: GameSnapshot = result.snapshot
        you: str = (
            "unknown"
            if result.llm_side is None
            else f"{result.llm_side.label} ({result.llm_side.symbol})"
        )
        return f"you: {you}   {cls._current_player_text(result)}"

    @classmethod
    def _current_player_text(cls, result: GameResult) -> str:
        """Explain the engine's current player in the caller's terms.

        Args:
            result: The tool result being rendered.

        Returns:
            A ``current_player: ...`` fragment.
        """
        snapshot: GameSnapshot = result.snapshot
        player: Side = snapshot.current_player
        code: int = int(player)
        if snapshot.is_over:
            hint = "game over"
        elif result.llm_side is None:
            hint = f"{player.label} to move"
        elif player is result.llm_side:
            hint = f"{player.label} to move, your turn"
        else:
            hint = f"{player.label} to move, human's turn"
        return f"current_player: {code} ({hint})"

    @classmethod
    def _moves_line(cls, moves: tuple[Move, ...]) -> str:
        """Render the chronological move list.

        Args:
            moves: Every move played so far.

        Returns:
            The ``moves:`` footer line, or ``moves: (none)``.
        """
        if not moves:
            return "moves: (none)"
        rendered: str = "  ".join(
            f"{index}. {move.player.move_label}({move.row},{move.col})"
            for index, move in enumerate(moves, start=1)
        )
        return f"moves: {rendered}"
