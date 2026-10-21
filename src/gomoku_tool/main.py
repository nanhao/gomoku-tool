"""Entry point of the gomoku-tool MCP server.

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
waiting tools are declared with ``@mcp.tool(task=True)`` once implemented.

Global-scope code is allowed in this entry script only. The tool surface is
registered in a later milestone; this file currently boots an MCP server with
the tasks extension and no tools so the scaffold is runnable::

    python -m gomoku_tool.main   # stdio transport, for MCP clients
    gomoku-tool                  # same, via the installed console script
"""

from fastmcp import FastMCP
from fastmcp_tasks import TasksExtension


def create_server() -> FastMCP:
    """Build and return the MCP server with the gomoku tool surface.

    Returns:
        A :class:`FastMCP` server with the background-tasks extension
        registered. Tool registration lives in ``gomoku_tool.tools`` and will
        be mounted here once implemented.
    """
    mcp: FastMCP = FastMCP("gomoku-tool")
    # Implements io.modelcontextprotocol/tasks; required by task=True tools.
    mcp.add_extension(TasksExtension())
    return mcp


def main() -> None:
    """Start the MCP server on the default stdio transport."""
    create_server().run()


if __name__ == "__main__":
    main()
