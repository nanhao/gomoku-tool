"""Tests for decoding the engine's REST snapshot."""

import pytest

from gomoku_tool.models.game_snapshot import GameSnapshot
from gomoku_tool.models.side import Side
from gomoku_tool.models.winner import Winner


class TestGameSnapshot:
    """The nested SavedGame wire shape must be decoded without drift."""

    def _payload(self) -> dict[str, object]:
        """Build a small valid SavedGame payload matching the engine."""
        return {
            "game_id": "game-1",
            "config": {"board_size": 3, "rule_variant": "standard"},
            "state": {
                "board": [[1, 0, 0], [0, 2, 0], [0, 0, 0]],
                "winner": 4,
                "current_player": 1,
            },
            "moves": [
                {"row": 1, "col": 1, "player": 1},
                {"row": 2, "col": 2, "player": 2},
            ],
        }

    def test_nested_payload_is_decoded(self) -> None:
        """Board, turn, outcome and move history come from config/state/moves."""
        snapshot = GameSnapshot.from_dict(self._payload())

        assert snapshot.game_id == "game-1"
        assert snapshot.board_size == 3
        assert snapshot.rule_variant == "standard"
        assert snapshot.winner is Winner.RUNNING
        assert snapshot.current_player is Side.BLACK
        assert snapshot.board[0][0] == 1
        assert snapshot.board[1][1] == 2
        assert snapshot.move_count == 2
        assert snapshot.moves[1].player is Side.WHITE

    def test_ragged_board_is_rejected(self) -> None:
        """A board that does not match board_size would break every lookup."""
        payload = self._payload()
        payload["state"] = {
            "board": [[0, 0, 0], [0, 0], [0, 0, 0]],
            "winner": 4,
            "current_player": 1,
        }

        with pytest.raises(ValueError, match="Malformed game snapshot"):
            GameSnapshot.from_dict(payload)

    def test_missing_field_is_rejected(self) -> None:
        """A missing nested object is a protocol error."""
        payload = self._payload()
        del payload["state"]

        with pytest.raises(ValueError, match="Malformed game snapshot"):
            GameSnapshot.from_dict(payload)

    def test_unknown_winner_code_is_rejected(self) -> None:
        """An outcome outside 1..4 must not be silently treated as running."""
        payload = self._payload()
        payload["state"] = {
            "board": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
            "winner": 9,
            "current_player": 1,
        }

        with pytest.raises(ValueError, match="Malformed game snapshot"):
            GameSnapshot.from_dict(payload)

    def test_turn_and_terminal_predicates(self) -> None:
        """Ownership and game-over checks are pure snapshot questions."""
        running = GameSnapshot.from_dict(self._payload())
        finished_payload = self._payload()
        finished_payload["state"] = {
            "board": [[1, 0, 0], [0, 2, 0], [0, 0, 0]],
            "winner": 1,
            "current_player": 1,
        }
        finished = GameSnapshot.from_dict(finished_payload)

        assert running.is_turn_of(Side.BLACK)
        assert not running.is_turn_of(Side.WHITE)
        assert not running.is_over
        assert finished.is_over
        assert not finished.is_turn_of(Side.BLACK)

    def test_cell_lookup_is_one_based(self) -> None:
        """The renderer and tools use 1-based coordinates end to end."""
        snapshot = GameSnapshot.from_dict(self._payload())

        assert snapshot.cell_at(1, 1) == 1
        assert snapshot.cell_at(2, 2) == 2
        with pytest.raises(IndexError):
            snapshot.cell_at(0, 1)
