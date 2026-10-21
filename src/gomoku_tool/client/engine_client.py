"""httpx implementation of the engine gateway port.

The adapter is a pure translator: it turns REST calls into
:class:`GameSnapshot` values and *every* failure (transport, HTTP status,
malformed JSON, shape drift) into an :class:`EngineError`. No decision about
the game is taken here.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

import httpx

from gomoku_tool.errors.engine_error import EngineError
from gomoku_tool.models.game_snapshot import GameSnapshot


class EngineClient:
    """REST client of one gomoku-engine instance.

    ``httpx.Client`` owns a connection pool and is safe to share between the
    worker threads the MCP adapter uses, so one instance lives for the whole
    server process and is closed by the server lifespan.
    """

    # Endpoint layout of the engine, documented in the README.
    GAMES_PATH: ClassVar[str] = "/api/v1/games"

    # Local engine calls are cheap; a long timeout would only delay the error
    # that tells the LLM the engine is unreachable.
    DEFAULT_TIMEOUT_SECONDS: ClassVar[float] = 10.0

    # Body preview included in error messages when the engine answers with
    # something that is not a JSON object with a ``detail`` field.
    ERROR_BODY_PREVIEW_CHARS: ClassVar[int] = 200

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Create the client.

        Args:
            base_url: Root URL of the engine, without a trailing slash.
            timeout_seconds: Per-request timeout.
        """
        self._base_url: str = base_url
        self._client: httpx.Client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
        )

    def create_game(self, board_size: int) -> GameSnapshot:
        """Create a game with ``POST /api/v1/games``.

        Args:
            board_size: Edge length of the square board.

        Returns:
            The freshly created game.

        Raises:
            EngineError: If the engine rejects the size or cannot be reached.
        """
        return self._request(
            "POST",
            self.GAMES_PATH,
            json_body={"board_size": board_size},
        )

    def get_game(self, game_id: str) -> GameSnapshot:
        """Read one game with ``GET /api/v1/games/{game_id}``.

        Args:
            game_id: uuid of the game.

        Returns:
            The authoritative snapshot.

        Raises:
            EngineError: If the game is unknown or the engine cannot be
                reached.
        """
        return self._request("GET", f"{self.GAMES_PATH}/{game_id}")

    def submit_move(self, game_id: str, row: int, col: int) -> GameSnapshot:
        """Submit a move with ``POST /api/v1/games/{game_id}/moves``.

        Args:
            game_id: uuid of the game.
            row: 1-based row of the stone.
            col: 1-based column of the stone.

        Returns:
            The state after the move was applied.

        Raises:
            EngineError: If the move is illegal, the game is unknown or the
                engine cannot be reached.
        """
        return self._request(
            "POST",
            f"{self.GAMES_PATH}/{game_id}/moves",
            json_body={"row": row, "col": col},
        )

    def close(self) -> None:
        """Close the underlying connection pool (server shutdown)."""
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        json_body: Mapping[str, Any] | None = None,
    ) -> GameSnapshot:
        """Send one request and decode its body as a game snapshot.

        Args:
            method: HTTP verb to use.
            path: Path relative to ``base_url``.
            json_body: Request body for writes; ``None`` for reads.

        Returns:
            The decoded snapshot.

        Raises:
            EngineError: If the request fails or the body cannot be decoded.
        """
        try:
            response: httpx.Response = self._client.request(
                method, path, json=json_body
            )
        except httpx.HTTPError as exc:
            raise EngineError(
                f"gomoku-engine is unreachable at {self._base_url} "
                f"({method} {path}): {exc}"
            ) from exc
        if response.status_code >= 400:
            raise EngineError(
                f"gomoku-engine rejected {method} {path} with HTTP "
                f"{response.status_code}: {self._error_detail(response)}",
                status_code=response.status_code,
            )
        try:
            return GameSnapshot.from_dict(response.json())
        except (ValueError, TypeError) as exc:
            # ``response.json()`` raises JSONDecodeError (a ValueError) and
            # ``from_dict`` raises ValueError on shape drift; both mean the
            # engine broke its contract, which is an EngineError for callers.
            raise EngineError(
                f"gomoku-engine returned an unreadable game for {method} "
                f"{path}: {exc}"
            ) from exc

    @classmethod
    def _error_detail(cls, response: httpx.Response) -> str:
        """Extract the most useful part of an error response body.

        The engine is a FastAPI application and reports failures as
        ``{"detail": ...}``. Anything else (a proxy page, an empty body) is
        reported as a short preview.

        Args:
            response: The failing HTTP response.

        Returns:
            A one-line description suitable for the LLM.
        """
        try:
            payload: Any = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, Mapping):
            detail: Any = payload.get("detail")
            if detail is not None:
                return str(detail)
        text: str = response.text.strip()
        if not text:
            return "no response body"
        return text[: cls.ERROR_BODY_PREVIEW_CHARS]
