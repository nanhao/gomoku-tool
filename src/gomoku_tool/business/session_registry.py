"""Thread-safe registry of the games tracked by this server."""

import threading

from gomoku_tool.business.game_session import GameSession


class SessionRegistry:
    """Maps game ids to in-process sessions and owns their subscriptions."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._sessions: dict[str, GameSession] = {}
        self._lock: threading.Lock = threading.Lock()

    def register(self, session: GameSession) -> GameSession:
        """Store a session, replacing and closing any previous one.

        Args:
            session: The session to track.

        Returns:
            The registered session, for convenient chaining.
        """
        with self._lock:
            previous: GameSession | None = self._sessions.get(session.game_id)
            self._sessions[session.game_id] = session
        # Close outside the registry lock: close() may touch the network and
        # must never block lookups of other games.
        if previous is not None and previous is not session:
            self.release_subscription(previous)
        return session

    def get(self, game_id: str) -> GameSession | None:
        """Return the session of a game, or ``None`` when it is not tracked.

        Args:
            game_id: uuid of the game.

        Returns:
            The tracked session, if any.
        """
        with self._lock:
            return self._sessions.get(game_id)

    def remove(self, game_id: str) -> None:
        """Forget a game and release its subscription.

        Args:
            game_id: uuid of the game to remove.
        """
        with self._lock:
            session: GameSession | None = self._sessions.pop(game_id, None)
        if session is not None:
            self.release_subscription(session)

    def close_all(self) -> None:
        """Forget every game and release all subscriptions (shutdown)."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self.release_subscription(session)

    @classmethod
    def release_subscription(cls, session: GameSession) -> None:
        """Close a session's subscription exactly once.

        Args:
            session: The session whose Redis handle should be released.
        """
        subscription = session.subscription
        if subscription is not None:
            session.subscription = None
            subscription.close()
