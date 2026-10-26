"""Tests for environment-driven server configuration."""

from pathlib import Path

import pytest

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

    def test_http_transport_is_the_default(self) -> None:
        """The server is a long-running HTTP service unless told otherwise.

        It binds every interface so a client on the same network can reach
        it; ``0.0.0.0`` is a bind address, clients connect to a real one.
        """
        config = ServerConfig.from_env({})

        assert config.transport == "http"
        assert config.host == "0.0.0.0"
        assert config.port == 8765

    def test_environment_overrides_transport_and_bind_address(self) -> None:
        """Host, port and transport are configurable; the name is normalized."""
        config = ServerConfig.from_env(
            {
                "GOMOKU_TRANSPORT": "STDIO",
                "GOMOKU_HOST": "192.0.2.10",
                "GOMOKU_PORT": "9100",
            }
        )

        assert config.transport == "stdio"
        assert config.host == "192.0.2.10"
        assert config.port == 9100

    def test_invalid_port_fails_at_startup_with_a_clear_message(self) -> None:
        """A typo in GOMOKU_PORT must not surface as a bind error later."""
        with pytest.raises(ValueError, match="GOMOKU_PORT"):
            ServerConfig.from_env({"GOMOKU_PORT": "eighty"})

    def test_port_out_of_range_is_rejected(self) -> None:
        """Port 0 would bind a random port, so it is an error, not a default."""
        with pytest.raises(ValueError, match="GOMOKU_PORT"):
            ServerConfig.from_env({"GOMOKU_PORT": "70000"})

    def test_unknown_transport_is_rejected(self) -> None:
        """Only the transports FastMCP can serve are accepted."""
        with pytest.raises(ValueError, match="GOMOKU_TRANSPORT"):
            ServerConfig.from_env({"GOMOKU_TRANSPORT": "carrier-pigeon"})
