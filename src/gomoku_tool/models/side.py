"""The two sides of a game, using the engine's own value codes.

The engine speaks integers (``1`` black, ``2`` white) on every wire format.
:class:`Side` is the single place those codes are parsed, so tools can accept
human-friendly spellings while the business layer always compares enums.
"""

from enum import IntEnum, nonmember
from typing import ClassVar, Self


class Side(IntEnum):
    """One player's colour, equal to the engine's value code.

    Attributes:
        BLACK: The side that moves first (engine code ``1``).
        WHITE: The second side (engine code ``2``).
    """

    BLACK = 1
    WHITE = 2

    # Accepted spellings for tool arguments. Keys are lower-case; the letters
    # mirror the board symbols (X for black, O for white) so an LLM that reads
    # the rendered board can pass back what it sees. ``nonmember`` keeps the
    # mapping out of the enum's members, which would otherwise try to build a
    # ``Side`` from a dict.
    ALIASES: ClassVar[dict[str, int]] = nonmember(
        {
            "black": 1,
            "b": 1,
            "x": 1,
            "1": 1,
            "white": 2,
            "w": 2,
            "o": 2,
            "2": 2,
        }
    )

    @classmethod
    def from_value(cls, value: str | int | Self) -> Self:
        """Parse a side from an MCP argument or an engine payload.

        Args:
            value: A :class:`Side`, the engine code ``1``/``2``, or one of the
                aliases ``black|b|x|1`` / ``white|w|o|2`` (case-insensitive).

        Returns:
            The matching side.

        Raises:
            ValueError: If the value is not a known side.
        """
        if isinstance(value, Side):
            return value
        if isinstance(value, int):
            try:
                return cls(value)
            except ValueError as exc:
                raise ValueError(
                    f"Unknown side code {value!r}; use 1 (black) or 2 (white)."
                ) from exc
        if isinstance(value, str):
            try:
                return cls(cls.ALIASES[value.strip().lower()])
            except KeyError as exc:
                raise ValueError(
                    f"Unknown side {value!r}; "
                    "use black/b/x/1 or white/w/o/2."
                ) from exc
        raise ValueError(f"Unknown side {value!r}.")

    def other(self) -> Self:
        """Return the opposite side, which is the human's side."""
        return Side.WHITE if self is Side.BLACK else Side.BLACK

    @property
    def label(self) -> str:
        """Return the lower-case name used in tool output."""
        return "black" if self is Side.BLACK else "white"

    @property
    def symbol(self) -> str:
        """Return the board symbol: ``X`` for black, ``O`` for white."""
        return "X" if self is Side.BLACK else "O"

    @property
    def move_label(self) -> str:
        """Return the one-letter label used in the move list."""
        return "B" if self is Side.BLACK else "W"
