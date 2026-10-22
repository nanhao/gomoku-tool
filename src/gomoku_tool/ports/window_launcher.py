"""Launcher for the human's gomoku-ui window."""

from gomoku_tool.models.launch_result import LaunchResult
from gomoku_tool.models.side import Side


class WindowLauncher:
    """Starts the desktop window the human plays in."""

    def launch(self, game_id: str, human_side: Side) -> LaunchResult:
        """Open a gomoku-ui process for one game.

        Args:
            game_id: uuid of the game the window should display.
            human_side: Side the human plays.

        Returns:
            Whether the process started, the exact command, and any failure
            reason. A failure is reported, never raised.
        """
        ...
