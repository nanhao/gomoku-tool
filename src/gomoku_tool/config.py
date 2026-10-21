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
        transport: FastMCP transport to serve: ``http`` (streamable HTTP),
            ``streamable-http``, ``sse`` or ``stdio``.
        host: Interface the HTTP transports bind to.
        port: TCP port the HTTP transports bind to.
    """

    # Environment variables documented in the README.
    ENGINE_URL_ENV_VAR: ClassVar[str] = "GOMOKU_ENGINE_URL"
    REDIS_URL_ENV_VAR: ClassVar[str] = "REDIS_URL"
    UI_DIR_ENV_VAR: ClassVar[str] = "GOMOKU_UI_DIR"
    UI_PYTHON_ENV_VAR: ClassVar[str] = "GOMOKU_UI_PYTHON"
    TRANSPORT_ENV_VAR: ClassVar[str] = "GOMOKU_TRANSPORT"
    HOST_ENV_VAR: ClassVar[str] = "GOMOKU_HOST"
    PORT_ENV_VAR: ClassVar[str] = "GOMOKU_PORT"

    # Defaults of a local desktop setup.
    DEFAULT_ENGINE_URL: ClassVar[str] = "http://127.0.0.1:8000"
    DEFAULT_REDIS_URL: ClassVar[str] = "redis://localhost:6379/0"
    DEFAULT_UI_DIR: ClassVar[Path] = Path(r"D:\projects\gomoku-ui")

    # The server is a long-running HTTP service by default: an MCP client
    # connects to a URL instead of spawning a child process. ``stdio`` stays
    # available for clients that only support spawned servers.
    DEFAULT_TRANSPORT: ClassVar[str] = "http"
    # Loopback by default: the tools open a desktop window and the engine API
    # has no authentication, so LAN exposure must be an explicit choice.
    DEFAULT_HOST: ClassVar[str] = "127.0.0.1"
    # 8000 belongs to gomoku-engine on the documented local setup.
    DEFAULT_PORT: ClassVar[int] = 8765
    SUPPORTED_TRANSPORTS: ClassVar[frozenset[str]] = frozenset(
        {"http", "sse", "streamable-http", "stdio"}
    )

    # Configuration errors name the offending variable so a typo surfaces at
    # startup, before any adapter is built.
    MESSAGE_UNKNOWN_TRANSPORT: ClassVar[str] = (
        "GOMOKU_TRANSPORT must be one of {supported}, got {value!r}."
    )
    MESSAGE_INVALID_PORT: ClassVar[str] = (
        "GOMOKU_PORT must be an integer, got {value!r}."
    )
    MESSAGE_PORT_OUT_OF_RANGE: ClassVar[str] = (
        "GOMOKU_PORT must be between 1 and 65535, got {value}."
    )

    engine_url: str
    redis_url: str
    ui_dir: Path
    ui_python: Path
    transport: str
    host: str
    port: int

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
        transport = cls._parse_transport(env.get(cls.TRANSPORT_ENV_VAR))
        return cls(
            engine_url=engine_url,
            redis_url=redis_url,
            ui_dir=ui_dir,
            ui_python=ui_python,
            transport=transport,
            host=env.get(cls.HOST_ENV_VAR) or cls.DEFAULT_HOST,
            port=cls._parse_port(env.get(cls.PORT_ENV_VAR)),
        )

    @classmethod
    def _parse_transport(cls, raw: str | None) -> str:
        """Normalize and validate the transport name.

        Args:
            raw: Value of ``GOMOKU_TRANSPORT``, if set.

        Returns:
            The lower-cased transport name.

        Raises:
            ValueError: If the name is not one FastMCP can serve.
        """
        transport = (raw or cls.DEFAULT_TRANSPORT).strip().lower()
        if transport not in cls.SUPPORTED_TRANSPORTS:
            raise ValueError(
                cls.MESSAGE_UNKNOWN_TRANSPORT.format(
                    supported=", ".join(sorted(cls.SUPPORTED_TRANSPORTS)),
                    value=transport,
                )
            )
        return transport

    @staticmethod
    def _parse_port(raw: str | None) -> int:
        """Parse the bind port, rejecting typos and port 0.

        Args:
            raw: Value of ``GOMOKU_PORT``, if set.

        Returns:
            The requested port, or the default when unset.

        Raises:
            ValueError: If the value is not an integer in 1..65535.
        """
        if raw is None or not raw.strip():
            return ServerConfig.DEFAULT_PORT
        try:
            port = int(raw)
        except ValueError as error:
            raise ValueError(
                ServerConfig.MESSAGE_INVALID_PORT.format(value=raw)
            ) from error
        if not 1 <= port <= 65535:
            raise ValueError(
                ServerConfig.MESSAGE_PORT_OUT_OF_RANGE.format(value=port)
            )
        return port

    @property
    def ui_script(self) -> Path:
        """Return the gomoku-ui entry script derived from the checkout."""
        return self.ui_dir / "src" / "scripts" / "play_game.py"
