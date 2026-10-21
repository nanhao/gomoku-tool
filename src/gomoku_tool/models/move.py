"""One played move, as stored in the engine's move history."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from gomoku_tool.models.side import Side


@dataclass(frozen=True)
class Move:
    """A stone placed on the board.

    Attributes:
        row: 1-based row of the stone, matching the engine.
        col: 1-based column of the stone, matching the engine.
        player: The side that placed the stone.
    """

    row: int
    col: int
    player: Side

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Decode one move record from the REST payload.

        Args:
            data: A move object with ``row``, ``col`` and ``player``.

        Returns:
            The decoded move.

        Raises:
            ValueError: If a field is missing or not a number/side code.
        """
        try:
            return cls(
                row=int(data["row"]),
                col=int(data["col"]),
                player=Side.from_value(data["player"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Malformed move record: {data!r}") from exc
