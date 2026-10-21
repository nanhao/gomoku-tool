# gomoku-tool — Design 1

This document specifies the first complete implementation of the MCP server.
It follows the contract already written in `README.md` (tool surface, engine REST
API, Redis move events, gomoku-ui launch command) and fixes every decision the
implementation needs.

## 1. Goals and Constraints

Goals:

- Let an LLM play Gomoku against a human through four MCP tools:
  `start_game`, `make_move`, `wait_for_turn`, `get_game_state`.
- Resolve every waiting tool at a **turn boundary**: it returns only when the
  LLM may act (or the game is over), never in the middle of the human's turn.
- Open the gomoku-ui window for the human when a game starts.
- Survive a missing/failing Redis by polling the engine snapshot.
- Expose the long waits as MCP Tasks (`io.modelcontextprotocol/tasks`).

Hard constraints:

- **No game rules here.** The engine is the only authority for legality,
  winner and turn. This server never computes a five-in-a-row.
- **MCP adapter and business logic are strictly separated.** The business layer
  imports no FastMCP, no httpx, no redis and no subprocess module. It is tested
  with in-memory fakes.
- One class per module, no module-level functions or variables, full type
  annotations, rich comments, files below 500 lines (project coding rules).
- 1-based coordinates end to end.

## 2. Layering

Dependency direction (no cycles, no lazy imports, no forward references used to
hide cycles):

```text
MCP client
    │  stdio: tools/call · tasks/get · tasks/cancel
    ▼
tools/            MCP adapter: FastMCP registration, task config, Progress,
    │             argument defaults, ToolError mapping
    ▼
business/         GameService · TurnWaiter · SessionRegistry · GameSession
    │             BoardRenderer — pure orchestration and presentation
    ▼
ports/            GameGateway · MoveEventFeed · MoveSubscription · WindowLauncher
    ▲
    │ implemented by
client/           EngineClient (httpx)         ─┐
events/           RedisMoveEventFeed (redis-py) ├─ adapters
ui/               UiLauncher (subprocess)      ─┘

models/ + errors/ + config.py   shared kernel, no I/O
main.py                         composition root (entry script)
```

- `models` decode the engine's two wire formats (REST snapshot, Redis event)
  and hold the values exchanged between layers.
- `business` holds all decisions that are worth testing: turn ownership, wait
  termination, session bookkeeping, board rendering.
- `ports` are `typing.Protocol` interfaces owned by the business layer; the
  adapters implement them, so tests substitute fakes and no I/O is needed.
- `tools` is the only module that knows FastMCP. It translates tool arguments
  to service calls and service results to rendered text.

## 3. Components

| Class | File | Responsibility |
| --- | --- | --- |
| `ServerConfig` | `config.py` | Resolve engine URL, Redis URL, UI dir and UI interpreter from env with documented defaults; derive the UI script path |
| `Side` | `models/side.py` | Engine side codes (`1` black, `2` white) with parsing, opposite, label and board symbol |
| `Winner` | `models/winner.py` | Engine outcome codes (`1` black, `2` white, `3` tie, `4` running) and their human-readable labels |
| `Move` | `models/move.py` | One played move: 1-based row/col + player side |
| `GameSnapshot` | `models/game_snapshot.py` | Immutable decoded `SavedGame`: nested `config`/`state`, board, winner, turn, move history; `from_dict`, `is_over`, `is_turn_of`, `cell_at` |
| `MoveEvent` | `models/move_event.py` | Immutable decoded pub/sub payload; `from_dict` returns `None` for non-move events |
| `LaunchResult` | `models/launch_result.py` | Whether the UI started, the exact command, and the failure reason |
| `WaitOutcome` | `models/wait_outcome.py` | Final snapshot of a wait plus `timed_out` / `cancelled` flags |
| `GameResult` | `models/game_result.py` | Snapshot + LLM side + timeout flag + user-facing notes |
| `GameError` | `errors/game_error.py` | Base class for every expected failure |
| `EngineError` | `errors/engine_error.py` | Engine request failed (HTTP status optional) |
| `TurnViolationError` | `errors/turn_violation_error.py` | Move refused because the LLM does not own the turn / game over |
| `EventStreamError` | `errors/event_stream_error.py` | Redis event delivery failed (triggers polling fallback) |
| `GameGateway` | `ports/game_gateway.py` | Protocol: create / read / submit move |
| `MoveSubscription` | `ports/move_subscription.py` | Protocol: blocking `get_event(timeout)` + `close` |
| `MoveEventFeed` | `ports/move_event_feed.py` | Protocol: open a subscription for one game |
| `WindowLauncher` | `ports/window_launcher.py` | Protocol: launch the human window |
| `GameSession` | `business/game_session.py` | Per-game state: LLM side, live subscription, last snapshot, per-game call lock |
| `SessionRegistry` | `business/session_registry.py` | Thread-safe game-id → session map; closes subscriptions on removal |
| `TurnWaiter` | `business/turn_waiter.py` | Wait until LLM turn or game over: event-driven with snapshot polling fallback, timeout, cancellation |
| `GameService` | `business/game_service.py` | Use cases: start, move, wait, state; turn guard; session re-attach; notes |
| `ServiceMessages` | `business/service_messages.py` | Every user-facing note and domain error template in one reviewable place |
| `BoardRenderer` | `business/board_renderer.py` | Render a `GameResult` as the README board + footer text |
| `EngineClient` | `client/engine_client.py` | httpx implementation of `GameGateway`; maps every failure to `EngineError` |
| `RedisMoveSubscription` | `events/redis_move_subscription.py` | Direct `pubsub.get_message` polling of one game channel; decodes and serializes readers |
| `RedisMoveEventFeed` | `events/redis_move_event_feed.py` | `PING` + subscribe to confirm the stream; failure raises `EventStreamError` |
| `UiLauncher` | `ui/ui_launcher.py` | `subprocess.Popen` of the gomoku-ui entry script; keeps process handles |
| `ProgressBridge` | `tools/progress_bridge.py` | Thread-safe bridge from a worker thread to `Progress.set_message` on the event loop |
| `GameTools` | `tools/game_tools.py` | FastMCP registration, wait budgets, argument translation (thin adapter) |
| `ServerLifespan` | `tools/server_lifespan.py` | Closes subscriptions, the Redis client and the HTTP pool on shutdown |
| `create_server` / `main` | `main.py` | Composition root; the only module with global code |

## 4. Data Contracts

### Engine REST snapshot (consumed)

`POST /api/v1/games`, `POST /api/v1/games/{id}/moves`, `GET /api/v1/games/{id}`
all return:

```json
{
  "game_id": "...",
  "config": {"board_size": 15, "rule_variant": "standard"},
  "state": {"board": [[0]], "winner": 4, "current_player": 1},
  "moves": [{"row": 8, "col": 8, "player": 1}]
}
```

`GameSnapshot.from_dict` validates the nested shape, a square board and the
value codes, and raises `ValueError` on drift. 1-based coordinates.

### Redis event (consumed)

Channel `gomoku:games:{game_id}:events`; one JSON object per move with
`event: "move"`, `game_id`, `move_number`, `row`, `col`, `player`,
`next_player`, `winner`, `game_over`. `MoveEvent.from_dict` ignores unknown
event names and rejects malformed move events.

### Wait termination rule

A wait ends when the **authoritative snapshot** reports `current_player ==
llm_side` or `winner.is_over`. An event is only a wake-up signal; after any
qualifying event the waiter refetches the snapshot. This keeps lost or
out-of-order events harmless.

## 5. Use Cases

### `start_game(board_size=15, llm_side="black", timeout_seconds=600)`

1. Parse the side (`black|b|x|1`, `white|w|o|2`, case-insensitive).
2. `POST /api/v1/games`.
3. Open the Redis subscription **before** reading a snapshot.
4. Launch gomoku-ui with the opposite side; a launch failure is a note, not an
   error.
5. `GET` the snapshot (authoritative starting position).
6. Register the session.
7. If it is already the LLM's turn (black moves first) return immediately;
   otherwise wait until the human's first move, the game ends or the timeout.
8. Return the rendered state with notes (UI status, Redis fallback, timeout).

### `make_move(game_id, row, col, llm_side=None, timeout_seconds=600)`

1. Resolve the LLM side: argument first, then the in-process session. With
   neither, fail with a message telling the caller to pass `llm_side`.
2. Ensure a session and a subscription (re-attach case: subscribe, then GET).
3. `GET` the snapshot and **guard the turn**: game over or
   `current_player != llm_side` raises `TurnViolationError`; no move is sent.
4. `POST /moves`.
5. If the move ended the game, return immediately.
6. Otherwise wait for the human's reply / game over / timeout.
7. Return the refreshed state.

### `wait_for_turn(game_id, llm_side=None, timeout_seconds=600)`

Ensure a session/subscription, read the snapshot, and return immediately when
the LLM may act or the game is over; otherwise run the same wait. Used after a
cancellation, a timeout, for clients without task support, and to re-attach
after a server restart.

### `get_game_state(game_id)`

Read-only `GET` + render. If no session exists the LLM side is unknown and the
footer says so; no waiting, no writes.

## 6. Turn Waiter Algorithm

```text
wait(subscription, llm_side, snapshot, timeout, sink, stop_event):
    if snapshot is terminal for llm_side: return immediately
    deadline = now + timeout
    last_poll = now
    loop:
        if stop_event set: return cancelled outcome
        if snapshot terminal: return current snapshot
        if now >= deadline: return timed-out outcome
        emit status "waiting for the human's move, move N" when N changes
        if subscription is None:
            event = None
        else:
            try: event = subscription.get_event(min(remaining, 0.5s))
            except EventStreamError: subscription = None; status "polling"
        if event qualifies (game_over or next_player == llm_side):
            snapshot = gateway.get_game(id)       # authoritative refresh
            continue
        if subscription is None or now - last_poll >= 2s:
            snapshot = gateway.get_game(id)       # polling fallback / repair
            last_poll = now
```

- Event poll slice (0.5 s) bounds cancellation latency and lets the loop check
  its deadline.
- Snapshot polling every 2 s is the guarantee when Redis is down or loses
  events; it also repairs reconnects.
- `stop_event` (a `threading.Event`) is set by the tool adapter when the MCP
  task is cancelled; the waiter returns a `cancelled` outcome and the service
  raises `WaitCancelledError` to unwind the worker.
- A timeout is **not** an error: the tool returns the current state, a
  "still waiting" note and tells the LLM to call `wait_for_turn`.

## 7. MCP Adapter Layer

- `main.create_server()` wires config → adapters → `GameService` →
  `GameTools`, registers `TasksExtension()` once and calls
  `GameTools.register(mcp)`.
- Waiting tools are async (required by FastMCP tasks) and declared with
  `TaskConfig(mode="optional", poll_interval=2s)`: task-capable clients get a
  background task, legacy clients run them inline.
- The synchronous business call runs in `asyncio.to_thread`, so a wait never
  blocks the server event loop; `asyncio.CancelledError` sets the waiter stop
  event before re-raising.
- Wait budget: background task → `timeout_seconds`; inline call → `0` for
  `start_game` / `make_move` (return immediately) and a short 10 s cap for
  `wait_for_turn`. Inline calls therefore never hold the connection for
  minutes, as documented in the README.
- `Progress.set_message` receives wait status through `ProgressBridge`, which
  schedules the coroutine on the tool's event loop from the worker thread and
  drops duplicate messages.
- Expected business failures (`GameError`, invalid side) are re-raised as
  `fastmcp.exceptions.ToolError`; unexpected exceptions propagate.
- `get_game_state` is a synchronous, non-task tool.

## 8. Board Rendering

Stable output (asserted by tests):

```text
     1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
 1   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
...
 8   .  .  .  .  .  .  .  .  X  .  .  .  .  .  .
game_id: 3383d4f3-7d61-4799-88d5-d2592d80d7b6
you: black (X)   current_player: 2 (white to move, human's turn)
winner: 4 (game running)
moves: 1. B(8,8)
```

- Header: three spaces, then every column number right-aligned in width 3.
- Rows: 1-based number right-aligned in width 2, one space, then each cell
  (`X`, `O`, `.`) right-aligned in width 3.
- Footer: `game_id`; `you` + `current_player` with turn explanation; `winner`
  with label; move list (`(none)` when empty); one `note:` line per note.
- With no known session: `you: unknown` and the current player line omits the
  ownership hint.

## 9. Session and Subscription Lifecycle

- One `GameSession` per game, held in-process. It stores the LLM side, the
  `MoveSubscription`, the last snapshot and a per-game lock that serializes
  `make_move` calls (two concurrent moves must not race the turn guard).
- `start_game` always registers a session; explicit `llm_side` on other tools
  creates or updates one (re-attach after restart).
- Subscriptions are opened before the first snapshot read and reused across
  calls. A subscription that failed to open is `None`; the waiter then polls.
  A later call retries opening it once Redis may be back.
- When a game ends, the subscription is closed and set to `None`; the session
  keeps the final snapshot. The UI window is untouched.
- `SessionRegistry.close_all()` releases every subscription on server
  shutdown through `ServerLifespan`, which then closes the shared Redis and
  HTTP clients. A subscription that failed to open is simply `None`: the
  waiter polls the engine, so no silent placeholder object is needed.

## 10. Error Policy

| Failure | Raised by | Tool behavior |
| --- | --- | --- |
| Engine unreachable / timeout / non-2xx / malformed payload | `EngineClient` → `EngineError` | `ToolError` with the message |
| Not the LLM's turn / game over on `make_move` | `GameService` → `TurnViolationError` | `ToolError`; no move sent |
| No session and no `llm_side` | `GameService` → `GameError` | `ToolError` telling the caller to pass `llm_side` |
| Redis unavailable / drops | `RedisMoveEventFeed` / subscription → `EventStreamError` | Not fatal: note + snapshot polling |
| Wait timeout | `TurnWaiter` (normal outcome) | Normal result + "still waiting" note |
| MCP task cancelled | `TurnWaiter` → `WaitCancelledError` | Task ends cancelled; game and UI untouched |

## 11. Test Strategy (business layer only)

Fakes replace the three ports; no live engine, Redis or UI is needed.

- `Side`: accepted spellings, rejection, opposite, symbol.
- `Winner`: codes and labels.
- `GameSnapshot`: nested decoding, ragged/missing payload rejection, turn/over
  predicates, cell lookup.
- `MoveEvent`: decoding, unknown event → `None`, malformed → `ValueError`.
- `BoardRenderer`: empty board, stones, header/footer, notes, unknown side.
- `TurnWaiter`: immediate turn, event wakes it, game-over event, unrelated
  event ignored, timeout, polling detects a lost event, stream failure falls
  back to polling, status messages, cancellation.
- `SessionRegistry`: register/get/remove, close-all, replacement.
- `GameService`: start (immediate / waiting / UI failure / Redis fallback),
  turn guard, illegal move, game over after move, timeout note, session
  re-attach, subscription reuse, wait_for_turn, get_game_state unknown session.
- `ServerConfig`: defaults, env overrides, derived UI interpreter/script.

Adapter classes are verified manually against the running engine/UI (documented
in README); they contain no game decisions.

## 12. Risks and Open Questions

- **No player identity in the engine** — side ownership is a cooperative guard
  in this server, as documented.
- **Lost events** — polling every 2 s bounds the damage; an engine outage
  during a wait surfaces as `EngineError` (documented, not retried).
- **Restart** — sessions and subscriptions are in-process; `wait_for_turn` with
  an explicit `llm_side` re-attaches, but the pending MCP task itself does not
  survive (Docket `memory://` default).
- **UI path** — the launcher only starts an existing checkout; a wrong path is
  reported as a note with the exact command, never fatal.
- **Concurrent games** — supported; each session has its own subscription and
  lock. One human per game remains an assumption.
