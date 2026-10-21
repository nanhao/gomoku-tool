# Gomoku Tool

An MCP server that lets an LLM play Gomoku (Five-in-a-Row) against a human.

`gomoku-tool` sits between three existing pieces:

- an **MCP client** drives the LLM,
- **gomoku-engine** (`D:\projects\gomoku-engine`) owns the game: rules,
  persistence, REST API and Redis move events,
- **gomoku-ui** (`D:\projects\gomoku-ui`) gives the human a desktop board.

This project is the glue between them:

- it exposes the turn loop as MCP tools,
- it launches a gomoku-ui window for the human when a game starts,
- it follows every move over Redis pub/sub and returns to the LLM exactly when
  it is the LLM's turn again,
- it models those turn-sized waits as **MCP Tasks**
  (`io.modelcontextprotocol/tasks`) because a human can think for minutes.

No game rule, no board state and no persistence is implemented here.

## Project Positioning

```
+----------------+
|   MCP client   |   (LLM agent)
+--------+-------+
         |  MCP (stdio): tools/call · tasks/get · tasks/cancel
         v
+----------------------+     HTTP REST      +------------------+
|     gomoku-tool      | ------------------> |  gomoku-engine   | ---> gomoku-core
|  (this repo)         | <------------------ |  REST + events   |
|  adapter + tasks     |     snapshots       +--------+---------+
+---+--------------+---+                              |
    |              |                                  | publishes
    | spawns       | Redis pub/sub (move events)      | move events
    v              |                                  v
+--------------+   +-------------  Redis  <-----------+
|  gomoku-ui   | -- HTTP REST + Redis pub/sub ------> (same engine)
|  human side  |
+--------------+
```

- **LLM side** — an MCP-capable client (IDE agent, desktop chat app, ...) talks
  to this server over stdio.
- **Human side** — plays their side of the same game in the gomoku-ui window
  that `start_game` opens.
- **gomoku-tool** — a protocol adapter plus a convenience layer: engine REST
  client, board rendering, turn waiting, UI launching, and the MCP Tasks
  plumbing. The engine's save files remain the single source of truth.

## Relationship to the Other Repositories

| Repository | Role |
| --- | --- |
| `D:\projects\gomoku-core` | Board representation, rule validation, win detection. **Not used directly** by this project. |
| `D:\projects\gomoku-engine` | Headless game server: sessions, persistence, REST API, Redis move events. The **only game authority**. |
| `D:\projects\gomoku-ui` | Tkinter desktop client the human plays on. Launched per game by this tool. |
| `D:\projects\gomoku-tool` (this repo) | MCP server: tools, turn waiting, UI launching, tasks extension. |

## The Turn Loop

The LLM plays one side (`llm_side`); the human plays the opposite side in the
gomoku-ui window that this server opens. Every tool call resolves exactly at a
**turn boundary**, so the LLM never polls and never places a stone for the
human.

1. `start_game(board_size=15, llm_side="black")`
   - creates the game with `POST /api/v1/games`,
   - launches a gomoku-ui window for the human with the opposite side,
   - subscribes to `gomoku:games:{game_id}:events` **before** reading the
     snapshot (so no move can slip between the two),
   - waits until it is the LLM's turn — immediately when the LLM is black, or
     until the human's first move when the LLM is white,
   - returns the rendered game state.
2. `make_move(game_id, row, col)`
   - verifies server-side that it is really the LLM's turn (the engine has no
     player identity — without this guard the LLM could play the human's side),
   - posts the move, then waits until the human replies or the game ends,
   - returns the refreshed, rendered state.
3. Repeat. When the human's move ends the game, the waiting call returns the
   final board and `winner`; the UI window stays open until the human closes it.

Both waits are long-running (a human may think for minutes) and are therefore
executed as **MCP Tasks** — see the next section.

### Example session

```
LLM  -> start_game(board_size=15, llm_side="black")     # task starts
        server: create game, open gomoku-ui (white) for the human, subscribe
        task completed -> {game_id, empty board, current_player: 1}

LLM  -> make_move(game_id, 8, 8)                        # task starts
        server: POST move, now waiting for white ...
        human clicks (9, 9) in the window -> event next_player=1
        task completed -> board with both stones, current_player: 1

LLM  -> make_move(game_id, 8, 9)                        # ... loop ...
        ...
        human's move sets winner=2 -> task completed with the final board
```

### Human side

The window opens automatically. The manual equivalent, should it ever be
needed, is the gomoku-ui entry script:

```powershell
cd D:\projects\gomoku-ui
.\.venv\Scripts\python.exe src/scripts/play_game.py <game_id> --side white `
    --engine-url http://127.0.0.1:8000 --redis-url redis://localhost:6379/0
```

## Long-running Tools: the MCP Tasks Extension

A human move can take seconds or minutes. A blocking `tools/call` ties up the
connection, hits client/proxy timeouts, and loses all progress if the client
reconnects. MCP Tasks (SEP-2663, extension id `io.modelcontextprotocol/tasks`)
replace the blocking call with a durable handle, "call now, fetch later".

How this server uses it:

- `start_game`, `make_move` and `wait_for_turn` are **task-augmented**. When the
  client has declared the extension capability, the server answers `tools/call`
  with `resultType: "task"` — a `taskId`, `status: "working"`, a TTL and a
  suggested `pollIntervalMs` — and keeps waiting in the background.
- The client polls `tasks/get`. While `working`, the task carries a status
  message ("waiting for the human's move, move 7"). On `completed` the task
  holds the same result a synchronous call would have returned. `failed`
  carries engine errors (unknown game, illegal move); `cancelled` follows
  `tasks/cancel`.
- `tasks/cancel` is cooperative and only stops the wait. The game and the UI
  window are untouched; `wait_for_turn` resumes the task later.
- A server **must not** return a task to a client that did not declare the
  extension. For such clients the tools run synchronously — `make_move`
  returns right after the move with a "not your turn yet" note, and the LLM
  polls with `get_game_state` / `wait_for_turn`.
- If the human does not move before the wait timeout, the task completes
  normally with the current state and a "still waiting" note; the LLM calls
  `wait_for_turn` to continue. A timeout is not an error.
- The task does not expire mid-game under normal play (TTL is set well above a
  reasonable think time); terminal results stay available for the TTL.

Implementation: this project uses **FastMCP 4** (`fastmcp[tasks]`, which
installs `fastmcp-tasks`). It implements the extension for protocol revision
**2026-07-28** with one registration and a decorator change:

- `TasksExtension()` is registered once on the server;
- the waiting tools are async and declared with `@mcp.tool(task=True)`, which
  maps to execution mode `optional`: task-capable clients get a background
  task, clients without the extension run the same function synchronously;
  the sync path must cap its wait and return a quick "not your turn yet"
  state so a legacy client never holds the connection;
- `Progress.set_message(...)` inside a task feeds the task's status message
  ("waiting for the human's move, move 7");
- the suggested poll interval is set per tool via
  `TaskConfig(mode="optional", poll_interval=...)`.

By contrast, the official Python SDK v2 (`mcp` 2.x, `MCPServer`) supports the
2026-07-28 revision and its extension framework (SEP-2133) but does **not**
ship the tasks extension itself. FastMCP 4 also keeps serving legacy protocol
clients through per-connection negotiation.

Task state lives in FastMCP's Docket backend: the default `memory://` fits a
local game (pending tasks are lost if the server restarts); set
`FASTMCP_DOCKET_URL` to a Redis/Valkey URL if waiting tasks must survive a
restart.

## MCP Tool Surface (planned v1)

| Tool | Parameters | Task-augmented | Purpose |
| --- | --- | --- | --- |
| `start_game` | `board_size: int = 15`, `llm_side: str = "black"`, `timeout_seconds: float = 600` | yes | Create the game, open gomoku-ui for the human (opposite side), wait until it is the LLM's turn, return the state. |
| `make_move` | `game_id: str`, `row: int`, `col: int`, `llm_side: Optional[str] = None`, `timeout_seconds: float = 600` | yes | Guard the turn, submit the move, wait for the human's reply or game over, return the refreshed state. |
| `wait_for_turn` | `game_id: str`, `llm_side: Optional[str] = None`, `timeout_seconds: float = 600` | yes | Resume waiting: after a cancellation or timeout, for clients without task support, or to re-attach after an MCP server restart. |
| `get_game_state` | `game_id: str` | no | Read-only rendered snapshot. |

`llm_side` may be omitted everywhere after `start_game`: the server remembers
each game's session (LLM side, subscription) in-process. Pass it explicitly to
re-attach after a restart.

Rendered state returned by the tools (`X` = black, `O` = white, `.` = empty):

```
     1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
 1   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
 2   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
 3   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
 4   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
 5   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
 6   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
 7   .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
 8   .  .  .  .  .  .  .  .  X  .  .  .  .  .  .
 9   .  .  .  .  .  .  .  .  O  .  .  .  .  .  .
...
game_id: 3383d4f3-7d61-4799-88d5-d2592d80d7b6
you: black (X)   current_player: 1 (black to move, your turn)
winner: 4 (game running)
moves: 1. B(8,8)  2. W(9,9)
```

## gomoku-engine Interface Reference

Everything this project consumes, verified against the engine and the UI
client's decoders.

### REST API

Base URL is configurable via `GOMOKU_ENGINE_URL`, default
`http://127.0.0.1:8000` (the engine binds `0.0.0.0:8000`; see its `start.ps1` or
`python -m gomoku_engine.main --port ...`).

| Method | Path | Body | Success | Errors |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/games` | optional `{"board_size": 15}` | `201` SavedGame | `400` illegal board size |
| `POST` | `/api/v1/games/{game_id}/moves` | `{"row": 8, "col": 8}` | `200` updated SavedGame | `404` unknown game, `400` illegal move |
| `GET` | `/api/v1/games/{game_id}` | — | `200` SavedGame | `404` unknown game |
| `GET` | `/api/v1/health` | — | `200` `{"status": "ok", ...}` | — |

### SavedGame payload (REST wire shape)

The response nests the board under `config` / `state` (this is the shape
gomoku-ui's `GameSnapshot.from_dict` decodes; the engine's on-disk
`save/<game_id>.json` uses a flat variant which this project never reads):

```json
{
  "game_id": "3383d4f3-7d61-4799-88d5-d2592d80d7b6",
  "config": { "board_size": 15, "rule_variant": "standard" },
  "state": {
    "board": [[0, 0, 0, "..."], "..."],
    "winner": 4,
    "current_player": 2
  },
  "moves": [{ "row": 8, "col": 8, "player": 1 }]
}
```

- Coordinates are **1-based** for both rows and columns.
- Board cells: `0` empty, `1` black, `2` white.
- `winner` / `player` / `current_player` codes: `1` black, `2` white, `3` tie,
  `4` unknown (game still running).

### Redis move events

The engine publishes one event per made move (best-effort — when Redis is
unreachable moves are still saved, so waiting must fall back to polling).

| Redis key | Kind | Purpose |
| --- | --- | --- |
| `gomoku:games:{game_id}:events` | pub/sub channel | Live broadcast of every move event of one game |
| `gomoku:games:{game_id}:history` | list | Retained copy of the same events; expires 1 minute after the game is over |

Event payload (JSON on the wire):

```json
{
  "event": "move",
  "game_id": "3383d4f3-7d61-4799-88d5-d2592d80d7b6",
  "move_number": 2,
  "row": 9,
  "col": 9,
  "player": 2,
  "next_player": 1,
  "winner": 4,
  "game_over": false
}
```

The waiter ends when an event reports `next_player == llm_side` (it is the
LLM's turn) or `game_over == true`. Any gap or reconnect is repaired by
refetching the snapshot, which is authoritative.

## gomoku-ui Integration

- Launch command per game (`human_side` = opposite of `llm_side`):

  ```powershell
  <GOMOKU_UI_PYTHON> <GOMOKU_UI_DIR>\src\scripts\play_game.py <game_id> `
      --side <black|white> --engine-url <engine-url> --redis-url <redis-url>
  ```

- Defaults: `GOMOKU_UI_DIR=D:\projects\gomoku-ui`, python =
  `<GOMOKU_UI_DIR>\.venv\Scripts\python.exe`. The UI package must be installed
  in that venv (`pip install -e .` in the UI repo).
- The window opens on the desktop of the machine running this MCP server, so
  run the server locally (stdio), not on a headless host.
- The UI enforces the human's side locally, loads the authoritative snapshot
  and follows events, so it tolerates being opened while it is the LLM's turn.
- A UI launch failure is **not fatal**: the game still exists, and the tool
  result reports the exact command so the human can start the window manually.

## Requirements

- Python 3.11+ (a python.org build, so Tkinter is available for the UI)
- A reachable **gomoku-engine** instance (run it first; see its README)
- **gomoku-ui** cloned, installed and configured at `GOMOKU_UI_DIR`
- Redis reachable from the engine (live move events; without it this tool
  degrades to polling)

## Setup

```powershell
# 1. Engine (Redis + REST API on :8000) in its own terminal
cd D:\projects\gomoku-engine
.\start.ps1

# 2. Human client, installed once
cd D:\projects\gomoku-ui
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 3. This project
cd D:\projects\gomoku-tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOMOKU_ENGINE_URL` | `http://127.0.0.1:8000` | Base URL of the gomoku-engine REST API |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis instance for move-event subscription |
| `GOMOKU_UI_DIR` | `D:\projects\gomoku-ui` | Gomoku-ui checkout; the launcher derives the script and venv from it |
| `GOMOKU_UI_PYTHON` | `<GOMOKU_UI_DIR>\.venv\Scripts\python.exe` | Interpreter used to launch the gomoku-ui window |

Run the server directly (stdio transport):

```powershell
python -m gomoku_tool.main
# or, after installation
gomoku-tool
```

Register it in an MCP client (example stdio config):

```json
{
  "mcpServers": {
    "gomoku": {
      "command": "D:\\projects\\gomoku-tool\\.venv\\Scripts\\python.exe",
      "args": ["-m", "gomoku_tool.main"],
      "env": {
        "GOMOKU_ENGINE_URL": "http://127.0.0.1:8000",
        "REDIS_URL": "redis://localhost:6379/0",
        "GOMOKU_UI_DIR": "D:\\projects\\gomoku-ui"
      }
    }
  }
}
```

The client must support the `io.modelcontextprotocol/tasks` extension for the
waiting tools to stay non-blocking; otherwise the synchronous fallback applies.

## Directory Layout

```
gomoku-tool/
├── README.md
├── pyproject.toml
├── architecture/              # design documents (to be added)
├── src/
│   └── gomoku_tool/
│       ├── __init__.py
│       ├── main.py            # entry point: FastMCP assembly + registrations
│       ├── config.py          # env resolution: engine, redis, UI paths (planned)
│       ├── client/            # gomoku-engine REST client (planned)
│       ├── events/            # Redis subscription & turn waiting (planned)
│       ├── models/            # DTOs mirroring engine payloads (planned)
│       ├── tools/             # MCP tool definitions (planned)
│       └── ui/                # gomoku-ui process launcher (planned)
└── tests/                     # unit, integration & end-to-end tests
```

## Design Principles

1. **The engine is the single source of truth.** No rules, no state, no
   persistence here — every decision comes from `gomoku-engine`.
2. **Side ownership is enforced in this server.** The engine has no player
   identity, so the turn guard (`current_player == llm_side`) must exist here;
   the tool never places a stone for the human.
3. **Tools resolve at turn boundaries.** Every waiting tool returns only when
   the LLM may act (or the game is over), and time-consuming waits are MCP
   Tasks, never blocked connections.
4. **Subscribe first, then snapshot; events are best-effort, polling is the
   guarantee.** Redis delivers the human's moves fast; GET remains the repair
   mechanism and the fallback.
5. **1-based coordinates end to end** between the LLM, the tools and the engine.

## Development

- Install with dev extras: `pip install -e ".[dev]"`
- Run tests: `python -m pytest`
- Implementation follows a design-first, test-driven workflow; design documents
  live in `architecture/`.

## Assumptions

- Single-user desktop setup: the MCP server, the engine/Redis and the human's
  window all run on the same machine or trusted LAN.
- The engine API is unauthenticated; side choice is a cooperative convention,
  not access control.
- One human per game; concurrent games are supported through the in-process
  session registry.

## Status / Roadmap

- [x] Project scaffold (layout, packaging, README)
- [ ] Engine REST client + models matching the nested wire shape
- [ ] Board renderer with 1-based coordinates
- [ ] Turn waiter: Redis pub/sub with polling fallback and gap repair
- [ ] gomoku-ui launcher with configurable paths
- [ ] Tasks wiring: `TasksExtension()`, `@mcp.tool(task=True)` on the waiting
      tools, progress status messages, poll interval
- [ ] MCP tool registration in `main.py`
- [ ] Tests (unit + integration against a running engine and UI)
