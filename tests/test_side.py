"""Tests for the side value code and its accepted spellings."""

import pytest

from gomoku_tool.models.side import Side


class TestSide:
    """The side value object must agree with the engine on codes and names."""

    def test_black_spellings_are_accepted(self) -> None:
        """Every documented spelling of black resolves to BLACK."""
        for value in ("black", "BLACK", " b ", "x", "X", "1", 1, Side.BLACK):
            assert Side.from_value(value) is Side.BLACK

    def test_white_spellings_are_accepted(self) -> None:
        """Every documented spelling of white resolves to WHITE."""
        for value in ("white", "White", " w ", "o", "O", "2", 2, Side.WHITE):
            assert Side.from_value(value) is Side.WHITE

    def test_unknown_side_is_rejected(self) -> None:
        """A name or code the engine does not know must raise ValueError."""
        for value in ("blue", "", "3", 3, 0):
            with pytest.raises(ValueError):
                Side.from_value(value)

    def test_other_returns_the_opposite_side(self) -> None:
        """The human plays exactly the opposite side of the LLM."""
        assert Side.BLACK.other() is Side.WHITE
        assert Side.WHITE.other() is Side.BLACK

    def test_labels_and_board_symbols_match_the_readme(self) -> None:
        """Rendering vocabulary is the documented one (X black, O white)."""
        assert Side.BLACK.label == "black"
        assert Side.WHITE.label == "white"
        assert Side.BLACK.symbol == "X"
        assert Side.WHITE.symbol == "O"
        assert Side.BLACK.move_label == "B"
        assert Side.WHITE.move_label == "W"
