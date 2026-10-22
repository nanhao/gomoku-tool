"""Game outcome codes reported by the engine.

``gomoku-core`` numbers outcomes exactly like the stones: ``1`` black wins,
``2`` white wins, ``3`` tie and ``4`` unknown, meaning the game is still
running. The enum keeps those magic numbers out of the business layer.
"""

from enum import IntEnum, nonmember
from typing import ClassVar, Self

from gomoku_tool.models.side import Side


class Winner(IntEnum):
    """One game outcome, equal to the engine's value code."""

    BLACK = 1
    WHITE = 2
    TIE = 3
    RUNNING = 4

    # Human-readable footer labels, keyed by enum name so the mapping cannot
    # drift if members are reordered. ``nonmember`` keeps the mapping out of
    # the enum's members, which would otherwise try to build a ``Winner``
    # from a dict.
    LABELS: ClassVar[dict[str, str]] = nonmember(
        {
            "BLACK": "black wins",
            "WHITE": "white wins",
            "TIE": "tie",
            "RUNNING": "game running",
        }
    )

    @classmethod
    def from_code(cls, code: int | str) -> Self:
        """Decode an engine outcome code.

        Args:
            code: ``1``, ``2``, ``3`` or ``4`` (an int or its string form).

        Returns:
            The matching outcome.

        Raises:
            ValueError: If the code is outside the documented range.
        """
        try:
            return cls(int(code))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Unknown winner code {code!r}; expected 1..4."
            ) from exc

    @classmethod
    def from_side(cls, side: Side | int) -> Self:
        """Return the winning outcome of one side.

        Args:
            side: The winning side (code ``1`` or ``2``).

        Returns:
            :attr:`BLACK` or :attr:`WHITE`.

        Raises:
            ValueError: If the side code is not a valid side.
        """
        return cls(Side.from_value(side))

    @property
    def is_over(self) -> bool:
        """Whether the game has ended (every outcome except ``RUNNING``)."""
        return self is not Winner.RUNNING

    @property
    def label(self) -> str:
        """Return the human-readable outcome used in rendered output."""
        return self.LABELS[self.name]
