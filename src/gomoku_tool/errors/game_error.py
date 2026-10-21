"""Base class for every expected, user-facing failure."""


class GameError(Exception):
    """A failure the MCP adapter reports as a tool error.

    The message is written for the LLM: it should say what went wrong and, when
    possible, what the caller can do about it.
    """
