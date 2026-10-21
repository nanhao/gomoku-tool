"""Tests for the rendered board text returned to the LLM."""

from gomoku_tool.business.board_renderer import BoardRenderer
from gomoku_tool.models.game_result import GameResult
from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner
from tests.fakes.snapshot_factory import SnapshotFactory


class TestBoardRenderer:
    """The rendered text is the tool surface: it must be stable and precise."""

    def test_empty_board_matches_the_documented_layout(self) -> None:
        """Header, grid, footer and an empty move list are all rendered."""
        result = GameResult(
            snapshot=SnapshotFactory.empty(current_player=Side.BLACK),
            llm_side=Side.BLACK,
        )

        text = BoardRenderer().render(result)

        assert text == (
            "     1  2  3  4  5\n"
            " 1   .  .  .  .  .\n"
            " 2   .  .  .  .  .\n"
            " 3   .  .  .  .  .\n"
            " 4   .  .  .  .  .\n"
            " 5   .  .  .  .  .\n"
            "game_id: g1\n"
            "you: black (X)   current_player: 1 (black to move, your turn)\n"
            "winner: 4 (game running)\n"
            "moves: (none)"
        )

    def test_stones_and_move_history_are_rendered(self) -> None:
        """X is black, O is white and moves are listed chronologically."""
        snapshot = SnapshotFactory.with_moves(
            [(3, 3, Side.BLACK), (3, 4, Side.WHITE)],
            current_player=Side.WHITE,
        )
        result = GameResult(snapshot=snapshot, llm_side=Side.BLACK)

        text = BoardRenderer().render(result)

        assert " 3   .  .  X  O  ." in text
        assert "current_player: 2 (white to move, human's turn)" in text
        assert "moves: 1. B(3,3)  2. W(3,4)" in text

    def test_finished_game_reports_the_winner(self) -> None:
        """The footer names the terminal outcome instead of a turn."""
        snapshot = SnapshotFactory.with_moves(
            [(1, 1, Side.BLACK)],
            current_player=Side.BLACK,
            winner=Winner.BLACK,
        )
        result = GameResult(snapshot=snapshot, llm_side=Side.BLACK)

        text = BoardRenderer().render(result)

        assert "current_player: 1 (game over)" in text
        assert "winner: 1 (black wins)" in text
        assert "moves: 1. B(1,1)" in text

    def test_unknown_side_omits_the_ownership_hint(self) -> None:
        """After a restart the LLM side may be unknown; rendering still works."""
        result = GameResult(snapshot=SnapshotFactory.empty(), llm_side=None)

        text = BoardRenderer().render(result)

        assert "you: unknown" in text
        assert "current_player: 1 (black to move)" in text

    def test_notes_are_rendered_as_note_lines(self) -> None:
        """Timeout and UI notes are part of the answer the LLM reads."""
        result = GameResult(
            snapshot=SnapshotFactory.empty(current_player=Side.WHITE),
            llm_side=Side.BLACK,
            timed_out=True,
            notes=("still waiting for the human's move", "ui note"),
        )

        text = BoardRenderer().render(result)

        assert text.endswith(
            "note: still waiting for the human's move\nnote: ui note"
        )
