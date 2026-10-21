"""Entry point of the gomoku-tool MCP server (composition root).

This project is a thin MCP adapter: it exposes tools that let an LLM start
games, inspect boards and make moves by calling the REST API of the
``gomoku-engine`` server at ``D:\\projects\\gomoku-engine``, opens a
``gomoku-ui`` window for the human opponent, and follows every move over Redis
pub/sub. No game rule is implemented here; the engine (and behind it
``gomoku-core``) stays the single source of truth.

Turn-sized waits (``start_game`` / ``make_move`` return only when it is the
LLM's turn again) are task-augmented through the MCP Tasks extension
(``io.modelcontextprotocol/tasks``, SEP-2663), provided by FastMCP 4 via the
``fastmcp-tasks`` package: :class:`TasksExtension` is registered here and the
waiting tools are declared with an optional ``TaskConfig``.

Global-scope code is allowed in this entry script only; everything else lives
in one-class-per-file modules. Run it with::

    python -m gomoku_tool.main   # stdio transport, for MCP clients
    gomoku-tool                  # same, via the installed console script
"""

from fastmcp import FastMCP
from fastmcp_tasks import TasksExtension

from gomoku_tool.business.board_renderer import BoardRenderer
from gomoku_tool.business.game_service import GameService
from gomoku_tool.client.engine_client import EngineClient
from gomoku_tool.config import ServerConfig
from gomoku_tool.events.redis_move_event_feed import RedisMoveEventFeed
from gomoku_tool.tools.game_tools import GameTools
from gomoku_tool.tools.server_lifespan import ServerLifespan
from gomoku_tool.ui.ui_launcher import UiLauncher


def create_server() -> FastMCP:
    """Build the MCP server with its adapters, tools and lifespan.

    Returns:
        A :class:`FastMCP` server exposing the four gomoku tools, with the
        background-tasks extension registered and every adapter wired to the
        configured engine, Redis instance and gomoku-ui checkout.
    """
    config: ServerConfig = ServerConfig.from_env()
    engine: EngineClient = EngineClient(config.engine_url)
    feed: RedisMoveEventFeed = RedisMoveEventFeed(config.redis_url)
    service: GameService = GameService(engine, feed, UiLauncher(config))
    mcp: FastMCP = FastMCP(
        "gomoku-tool",
        lifespan=ServerLifespan(service, engine, feed),
    )
    # Implements io.modelcontextprotocol/tasks; required by task tools.
    mcp.add_extension(TasksExtension())
    GameTools(service, BoardRenderer()).register(mcp)
    return mcp


def main() -> None:
    """Start the MCP server on the default stdio transport."""
    create_server().run()


if __name__ == "__main__":
    main()
