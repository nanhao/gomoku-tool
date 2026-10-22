"""Tests for the engine outcome codes."""

import pytest

from gomoku_tool.models.winner import Winner


class TestWinner:
    """Outcome codes must be decoded exactly as the engine reports them."""

    def test_codes_are_decoded(self) -> None:
        """The four engine codes map to their enum members."""
        assert Winner.from_code(1) is Winner.BLACK
        assert Winner.from_code(2) is Winner.WHITE
        assert Winner.from_code(3) is Winner.TIE
        assert Winner.from_code(4) is Winner.RUNNING

    def test_unknown_code_is_rejected(self) -> None:
        """An unrecognised outcome is a protocol error, not a running game."""
        for code in (0, 5, -1):
            with pytest.raises(ValueError):
                Winner.from_code(code)

    def test_is_over_is_true_only_for_terminal_outcomes(self) -> None:
        """RUNNING is the only non-terminal state."""
        assert Winner.BLACK.is_over
        assert Winner.WHITE.is_over
        assert Winner.TIE.is_over
        assert not Winner.RUNNING.is_over

    def test_labels_are_human_readable(self) -> None:
        """The footer uses these exact labels."""
        assert Winner.BLACK.label == "black wins"
        assert Winner.WHITE.label == "white wins"
        assert Winner.TIE.label == "tie"
        assert Winner.RUNNING.label == "game running"

    def test_winner_of_a_side(self) -> None:
        """A side's winning code is the engine's own value code."""
        assert Winner.from_side(1) is Winner.BLACK
        assert Winner.from_side(2) is Winner.WHITE
