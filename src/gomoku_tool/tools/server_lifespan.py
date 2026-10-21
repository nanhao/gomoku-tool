"""Server lifespan: release every adapter resource on shutdown.

``GameService.close`` releases the Redis subscriptions of all tracked games,
then the shared Redis client and the HTTP connection pool are closed. Passing
this object to ``FastMCP(lifespan=...)`` keeps that cleanup in one place
instead of relying on the interpreter teardown.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from gomoku_tool.business.game_service import GameService
from gomoku_tool.client.engine_client import EngineClient
from gomoku_tool.events.redis_move_event_feed import RedisMoveEventFeed


class ServerLifespan:
    """Async context manager that owns the process-wide adapter resources."""

    def __init__(
        self,
        service: GameService,
        engine: EngineClient,
        feed: RedisMoveEventFeed,
    ) -> None:
        """Store the resources to release when the server stops.

        Args:
            service: Business service that owns the per-game subscriptions.
            engine: HTTP client of the engine.
            feed: Redis subscription factory.
        """
        self._service: GameService = service
        self._engine: EngineClient = engine
        self._feed: RedisMoveEventFeed = feed

    @asynccontextmanager
    async def __call__(self, server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        """Run the server, then close the adapters.

        Args:
            server: The MCP server entering its lifespan (unused).

        Yields:
            An empty lifespan context; the tools need no shared state entry.
        """
        try:
            yield {}
        finally:
            # Subscriptions first: closing them may talk to Redis, and the
            # shared client must still be open at that point.
            self._service.close()
            self._feed.close()
            self._engine.close()
