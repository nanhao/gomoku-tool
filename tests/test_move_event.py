"""Tests for decoding Redis move events."""

import pytest

from gomoku_tool.models.move_event import MoveEvent
from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner


class TestMoveEvent:
    """Only move events are decoded; everything else is ignored."""

    def _payload(self) -> dict[str, object]:
        """Build the exact JSON body the engine publishes."""
        return {
            "event": "move",
            "game_id": "game-1",
            "move_number": 2,
            "row": 9,
            "col": 9,
            "player": 2,
            "next_player": 1,
            "winner": 4,
            "game_over": False,
        }

    def test_move_payload_is_decoded(self) -> None:
        """Every field of the wire format reaches the value object."""
        event = MoveEvent.from_dict(self._payload())

        assert event is not None
        assert event.game_id == "game-1"
        assert event.move_number == 2
        assert event.row == 9
        assert event.col == 9
        assert event.player is Side.WHITE
        assert event.next_player is Side.BLACK
        assert event.winner is Winner.RUNNING
        assert not event.game_over

    def test_unknown_event_name_is_ignored(self) -> None:
        """A future event type must not tear down the subscription."""
        payload = self._payload()
        payload["event"] = "resign"

        assert MoveEvent.from_dict(payload) is None

    def test_malformed_move_event_is_rejected(self) -> None:
        """A move event missing fields cannot be interpreted."""
        payload = self._payload()
        del payload["next_player"]

        with pytest.raises(ValueError, match="Malformed move event"):
            MoveEvent.from_dict(payload)

    def test_game_over_follows_the_reported_flag(self) -> None:
        """The engine's flag wins over anything inferred locally."""
        payload = self._payload()
        payload["winner"] = 1
        payload["game_over"] = True

        event = MoveEvent.from_dict(payload)

        assert event is not None
        assert event.game_over
        assert event.winner is Winner.BLACK

    def test_ends_wait_when_the_llm_is_next_or_game_is_over(self) -> None:
        """The waiter wakes on the LLM's turn or a finished game only."""
        human_moved = MoveEvent.from_dict(self._payload())
        finished_payload = self._payload()
        finished_payload["winner"] = 2
        finished_payload["game_over"] = True
        finished = MoveEvent.from_dict(finished_payload)

        assert human_moved is not None and finished is not None
        assert human_moved.ends_wait_for(Side.BLACK)
        assert not human_moved.ends_wait_for(Side.WHITE)
        assert finished.ends_wait_for(Side.BLACK)
        assert finished.ends_wait_for(Side.WHITE)
