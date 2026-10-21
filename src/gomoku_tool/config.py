"""Runtime configuration resolved from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self


@dataclass(frozen=True)
class ServerConfig:
    """Fully resolved configuration of the MCP server process.

    Attributes:
        engine_url: Base URL of the gomoku-engine REST API, without a
            trailing slash.
        redis_url: Redis instance the engine publishes move events to.
        ui_dir: Checkout of the gomoku-ui desktop client.
        ui_python: Interpreter used to launch the gomoku-ui window.
    """

    # Environment variables documented in the README.
    ENGINE_URL_ENV_VAR: ClassVar[str] = "GOMOKU_ENGINE_URL"
    REDIS_URL_ENV_VAR: ClassVar[str] = "REDIS_URL"
    UI_DIR_ENV_VAR: ClassVar[str] = "GOMOKU_UI_DIR"
    UI_PYTHON_ENV_VAR: ClassVar[str] = "GOMOKU_UI_PYTHON"

    # Defaults of a local desktop setup.
    DEFAULT_ENGINE_URL: ClassVar[str] = "http://127.0.0.1:8000"
    DEFAULT_REDIS_URL: ClassVar[str] = "redis://localhost:6379/0"
    DEFAULT_UI_DIR: ClassVar[Path] = Path(r"D:\projects\gomoku-ui")

    engine_url: str
    redis_url: str
    ui_dir: Path
    ui_python: Path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Build the configuration from environment variables.

        Args:
            environ: Mapping to read; ``None`` means ``os.environ``. Tests pass
                an explicit mapping so they never depend on the host.

        Returns:
            The resolved configuration. Empty values fall back to defaults.
        """
        env: Mapping[str, str] = os.environ if environ is None else environ
        ui_dir = Path(env.get(cls.UI_DIR_ENV_VAR) or cls.DEFAULT_UI_DIR)
        ui_python = Path(
            env.get(cls.UI_PYTHON_ENV_VAR)
            or ui_dir / ".venv" / "Scripts" / "python.exe"
        )
        engine_url = (
            env.get(cls.ENGINE_URL_ENV_VAR) or cls.DEFAULT_ENGINE_URL
        ).rstrip("/")
        redis_url = env.get(cls.REDIS_URL_ENV_VAR) or cls.DEFAULT_REDIS_URL
        return cls(
            engine_url=engine_url,
            redis_url=redis_url,
            ui_dir=ui_dir,
            ui_python=ui_python,
        )

    @property
    def ui_script(self) -> Path:
        """Return the gomoku-ui entry script derived from the checkout."""
        return self.ui_dir / "src" / "scripts" / "play_game.py"
