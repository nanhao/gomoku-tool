"""Thread-safe bridge from a worker thread to ``Progress.set_message``.

The business layer is synchronous and runs in ``asyncio.to_thread``. The wait
status it emits therefore originates on a worker thread, while
``Progress.set_message`` is a coroutine bound to the tool's event loop. The
bridge is the small adapter between the two, and it also drops repeated
messages so a status that did not change is not rewritten.
"""

import asyncio
import threading

from fastmcp.dependencies import Progress


class ProgressBridge:
    """A ``status_sink`` callable that publishes to an MCP task."""

    def __init__(
        self, loop: asyncio.AbstractEventLoop, progress: Progress
    ) -> None:
        """Bind the bridge to one running loop and one progress handle.

        Args:
            loop: Event loop of the tool call that owns ``progress``.
            progress: Injected progress handle of the same tool call.
        """
        self._loop: asyncio.AbstractEventLoop = loop
        self._progress: Progress = progress
        self._last_message: str | None = None
        self._lock: threading.Lock = threading.Lock()

    def __call__(self, message: str) -> None:
        """Report one status message from the worker thread.

        Args:
            message: The new status; identical consecutive messages are
                ignored because tasks are polled by message text.
        """
        with self._lock:
            if message == self._last_message:
                return
            self._last_message = message
        try:
            # The worker thread must never touch the progress object directly;
            # this schedules ``_publish`` on the loop that owns it.
            self._loop.call_soon_threadsafe(self._publish, message)
        except RuntimeError:
            # The loop closed between the worker's last check and this call
            # (server shutting down); a lost status line is harmless.
            pass

    def _publish(self, message: str) -> None:
        """Run on the event loop: schedule the async message update.

        Args:
            message: The status to store on the task.
        """
        self._loop.create_task(self._progress.set_message(message))
