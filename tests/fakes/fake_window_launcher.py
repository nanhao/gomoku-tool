"""In-memory implementation of the window-launcher port."""

from gomoku_tool.models.launch_result import LaunchResult
from gomoku_tool.models.side import Side


class FakeWindowLauncher:
    """Records launch attempts and returns a programmed result.

    Attributes:
        result: Result returned by every launch.
        launches: ``(game_id, human_side)`` pairs, in order.
    """

    def __init__(self, result: LaunchResult | None = None) -> None:
        """Create a launcher that reports success by default.

        Args:
            result: Result to return; ``None`` means "the window opened".
        """
        self.result: LaunchResult = result or LaunchResult(
            started=True, command=("gomoku-ui",)
        )
        self.launches: list[tuple[str, Side]] = []

    def launch(self, game_id: str, human_side: Side) -> LaunchResult:
        """Record one launch attempt.

        Args:
            game_id: Game the human window should display.
            human_side: Side the human plays.

        Returns:
            The programmed launch result.
        """
        self.launches.append((game_id, human_side))
        return self.result
