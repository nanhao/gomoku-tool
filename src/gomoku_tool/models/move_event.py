"""A move event decoded from the engine's Redis pub/sub channel."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner


@dataclass(frozen=True)
class MoveEvent:
    """One decoded move event, exactly as broadcast by the engine.

    Attributes:
        game_id: uuid of the game the move belongs to.
        move_number: 1-based position of the move in the game history.
        row: 1-based row of the placed stone.
        col: 1-based column of the placed stone.
        player: Side that placed the stone.
        next_player: Side that must move next; once the game is over it
            keeps the player who made the last move.
        winner: Outcome after this move.
        game_over: Whether this move decided the game, as reported on the wire.
    """

    game_id: str
    move_number: int
    row: int
    col: int
    player: Side
    next_player: Side
    winner: Winner
    game_over: bool

    # Wire name of the only event type this server understands. Declared as a
    # class variable so it never becomes a dataclass field.
    EVENT_NAME: ClassVar[str] = "move"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self | None:
        """Decode one pub/sub payload.

        Args:
            data: The JSON body of a Redis pub/sub message.

        Returns:
            The decoded event, or ``None`` when the payload is not a move event
            (for example a future event type this server must ignore).

        Raises:
            ValueError: If the payload claims to be a move event but a required
                field is missing or has the wrong type.
        """
        if data.get("event") != cls.EVENT_NAME:
            return None
        try:
            winner = Winner.from_code(data["winner"])
            return cls(
                game_id=str(data["game_id"]),
                move_number=int(data["move_number"]),
                row=int(data["row"]),
                col=int(data["col"]),
                player=Side.from_value(data["player"]),
                next_player=Side.from_value(data["next_player"]),
                winner=winner,
                # Be tolerant about the flag's JSON type: the engine sends a
                # real boolean, but any truthy value means "game is over".
                game_over=bool(data.get("game_over", winner.is_over)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Malformed move event: {data!r}") from exc

    def ends_wait_for(self, side: Side) -> bool:
        """Whether this event ends a wait on behalf of ``side``.

        Args:
            side: The side that is waiting (the LLM's side).

        Returns:
            ``True`` when the game ended or the next move belongs to ``side``.
        """
        return self.game_over or self.next_player is side
