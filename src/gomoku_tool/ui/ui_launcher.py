"""Starts the gomoku-ui desktop window the human plays in.

Launching is best effort by contract: the game already exists in the engine
when this adapter runs, so a missing checkout or interpreter is reported back
as a :class:`LaunchResult` and becomes a note under the board, never an error.
"""

import subprocess
from typing import ClassVar

from gomoku_tool.config import ServerConfig
from gomoku_tool.models.launch_result import LaunchResult
from gomoku_tool.models.side import Side


class UiLauncher:
    """Implements :class:`WindowLauncher` with ``subprocess.Popen``.

    The child is detached on purpose: the MCP server must not wait for the
    window, and must not keep its stdio streams (stdout belongs to the MCP
    transport). Handles are retained so a running window is not garbage
    collected before the process exits.
    """

    # Arguments of the gomoku-ui entry script (see its README).
    SIDE_FLAG: ClassVar[str] = "--side"
    ENGINE_URL_FLAG: ClassVar[str] = "--engine-url"
    REDIS_URL_FLAG: ClassVar[str] = "--redis-url"

    def __init__(self, config: ServerConfig) -> None:
        """Create the launcher for one configured checkout.

        Args:
            config: Resolved server configuration (UI dir, interpreter,
                engine and Redis URLs).
        """
        self._config: ServerConfig = config
        self._processes: list[subprocess.Popen[bytes]] = []

    def launch(self, game_id: str, human_side: Side) -> LaunchResult:
        """Open a gomoku-ui window for one game.

        Args:
            game_id: uuid of the game the window should display.
            human_side: Side the human plays in that window.

        Returns:
            Whether the process started, the exact command, and the failure
            reason when it did not.
        """
        command: tuple[str, ...] = self._command(game_id, human_side)
        script = self._config.ui_script
        if not script.is_file():
            return LaunchResult.failed(
                command, f"gomoku-ui entry script not found at {script}"
            )
        if not self._config.ui_python.is_file():
            return LaunchResult.failed(
                command,
                f"gomoku-ui interpreter not found at "
                f"{self._config.ui_python}",
            )
        try:
            process: subprocess.Popen[bytes] = subprocess.Popen(
                command,
                cwd=str(self._config.ui_dir),
                # Never inherit the MCP server's streams: stdout carries the
                # protocol, and a chatty Tk window must not corrupt it.
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return LaunchResult.failed(command, str(exc))
        self._processes.append(process)
        return LaunchResult.launched(command)

    def _command(self, game_id: str, human_side: Side) -> tuple[str, ...]:
        """Build the exact argv of the gomoku-ui entry script.

        Args:
            game_id: uuid of the game to display.
            human_side: Side the human plays.

        Returns:
            The argv reported to the LLM when the launch fails.
        """
        return (
            str(self._config.ui_python),
            str(self._config.ui_script),
            game_id,
            self.SIDE_FLAG,
            human_side.label,
            self.ENGINE_URL_FLAG,
            self._config.engine_url,
            self.REDIS_URL_FLAG,
            self._config.redis_url,
        )
