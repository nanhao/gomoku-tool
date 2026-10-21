"""Tests for environment-driven server configuration."""

from pathlib import Path

from gomoku_tool.config import ServerConfig


class TestServerConfig:
    """Configuration precedence and derived paths must match the README."""

    def test_defaults_are_the_documented_local_setup(self) -> None:
        """With no environment the server targets the local stack."""
        config = ServerConfig.from_env({})

        assert config.engine_url == "http://127.0.0.1:8000"
        assert config.redis_url == "redis://localhost:6379/0"
        assert config.ui_dir == Path(r"D:\projects\gomoku-ui")
        assert config.ui_python == Path(
            r"D:\projects\gomoku-ui\.venv\Scripts\python.exe"
        )
        assert config.ui_script == Path(
            r"D:\projects\gomoku-ui\src\scripts\play_game.py"
        )

    def test_environment_overrides_urls_and_ui_directory(self) -> None:
        """Every documented variable replaces its default."""
        config = ServerConfig.from_env(
            {
                "GOMOKU_ENGINE_URL": "http://192.0.2.10:9000/",
                "REDIS_URL": "redis://192.0.2.10:6380/1",
                "GOMOKU_UI_DIR": r"D:\apps\gomoku-ui",
            }
        )

        assert config.engine_url == "http://192.0.2.10:9000"
        assert config.redis_url == "redis://192.0.2.10:6380/1"
        assert config.ui_dir == Path(r"D:\apps\gomoku-ui")
        assert config.ui_python == Path(
            r"D:\apps\gomoku-ui\.venv\Scripts\python.exe"
        )
        assert config.ui_script == Path(
            r"D:\apps\gomoku-ui\src\scripts\play_game.py"
        )

    def test_explicit_ui_python_wins_over_the_derived_path(self) -> None:
        """A custom interpreter (e.g. a python.org build) can be selected."""
        config = ServerConfig.from_env(
            {
                "GOMOKU_UI_DIR": r"D:\apps\gomoku-ui",
                "GOMOKU_UI_PYTHON": r"C:\Python313\python.exe",
            }
        )

        assert config.ui_python == Path(r"C:\Python313\python.exe")
