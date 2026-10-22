"""In-process state of one tracked game."""

import threading
from dataclasses import dataclass, field

from gomoku_tool.models.game_snapshot import GameSnapshot
from gomoku_tool.models.side import Side
from gomoku_tool.ports.move_subscription import MoveSubscription


@dataclass(eq=False)
class GameSession:
    """What the server remembers about one game between tool calls.

    Attributes:
        game_id: uuid of the game.
        llm_side: Side the LLM plays; an explicit tool argument can override it.
        subscription: Live move-event subscription, or ``None`` when Redis is
            unavailable (the waiter then polls the engine).
        last_snapshot: Most recent authoritative snapshot read from the engine.
        move_lock: Serializes move submissions for this game so two concurrent
            tool calls cannot race the turn guard.
    """

    game_id: str
    llm_side: Side
    subscription: MoveSubscription | None = None
    last_snapshot: GameSnapshot | None = None
    move_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False
    )
