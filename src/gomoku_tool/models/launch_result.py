"""Outcome of trying to open a gomoku-ui window for the human."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class LaunchResult:
    """Result of one UI launch attempt.

    Attributes:
        started: Whether the child process was created.
        command: Exact argv used, so a failed launch can be reported verbatim.
        error: Failure reason when ``started`` is ``False``.
    """

    started: bool
    command: tuple[str, ...]
    error: str | None = None

    @classmethod
    def launched(cls, command: Sequence[str]) -> Self:
        """Build a success result.

        Args:
            command: The argv of the started process.

        Returns:
            A result describing a window that opened.
        """
        return cls(started=True, command=tuple(command))

    @classmethod
    def failed(cls, command: Sequence[str], error: str) -> Self:
        """Build a failure result.

        Args:
            command: The argv that was attempted.
            error: Human-readable failure reason.

        Returns:
            A result describing a window that did not open.
        """
        return cls(started=False, command=tuple(command), error=error)

    @property
    def command_text(self) -> str:
        """Return the launch command as a copy-pasteable Windows command line."""
        return subprocess.list2cmdline(list(self.command))
