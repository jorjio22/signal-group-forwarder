# Signal Forwarder

A web-based Signal group forwarder built with FastAPI.

This repository contains the current refactored application only: a local web UI, SQLite-backed settings, a `signal-cli` integration layer, and a worker that forwards plain-text messages from one Signal group to another under controlled rules.

## What It Does

- Links a single Signal account as a linked device using a QR code in the web UI
- Lists Signal groups and lets you select one forwarding rule: `Group A -> Group B`
- Persists app settings in SQLite
- Forwards plain-text messages from the selected source group to the selected target group
- Preserves forwarding for both:
  - normal received messages (`dataMessage`)
  - linked-device self-sync messages (`syncMessage.sentMessage`)
- Applies:
  - source-group filtering
  - quiet hours in `Europe/Kyiv`
  - backlog window filtering
  - rate limiting
  - durable dedupe
- Provides live in-memory logs in the web UI
- Supports logout / local reset back to the unlinked state

## Current Capabilities

- FastAPI server with Jinja templates
- Dark admin-style desktop UI
- QR-based linked-device login flow
- Group discovery and persisted source/target selection
- Persisted settings:
  - `backlog_minutes`
  - `quiet_start_local`
  - `quiet_end_local`
  - `rate_limit_seconds`
- Supervisor-managed worker lifecycle
- Real `signal-cli` JSON-RPC receive/send loop
- SQLite-backed runtime/account/settings state
- Test coverage for core forwarding and logout behavior

## Main UI Sections

- `Dashboard`
  - bot status
  - linked account summary
  - current routing/settings summary
  - live log panel
- `Login`
  - QR-based linked-device flow
  - account status
  - logout/reset entry point
- `Groups`
  - refresh Signal groups
  - choose source group
  - choose target group
- `Settings`
  - backlog window
  - quiet hours
  - rate limit
- `Status`
  - account state
  - worker / JSON-RPC state
  - supervisor state
  - manual worker restart for diagnostics

## Tech Stack

- Python 3.12+
- FastAPI
- Jinja2
- WebSocket live logs
- SQLite
- `signal-cli`
- `qrcode` + `Pillow`
- `pytest`

## Requirements

You need a working `signal-cli` installation available to the app.

By default, the refactored app expects:

- `signal-cli` to be available on `PATH`, or
- `SIGNAL_CLI_EXECUTABLE` to point to the executable you want to use

The repository does **not** include runtime Signal account data, local SQLite state, or bundled `signal-cli` binaries.

## Local Development Setup

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Ensure `signal-cli` is installed and callable:

```bash
signal-cli --version
```

4. Optionally set environment variables if you want to override defaults.

Common environment variables:

- `SIGNAL_CLI_EXECUTABLE`
- `SIGNAL_CONFIG_DIR`
- `APP_DB_PATH`
- `APP_NAME`
- `APP_DEBUG`
- `BACKLOG_MINUTES_DEFAULT`
- `QUIET_START_DEFAULT`
- `QUIET_END_DEFAULT`
- `RATE_LIMIT_SECONDS_DEFAULT`
- `LINK_DEVICE_NAME`

## Running the App Locally

Start the web app with Uvicorn:

```bash
uvicorn app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

Typical first-run flow:

1. Open `Login`
2. Start the QR link session
3. Scan the QR code from your primary Signal device
4. Open `Groups` and select source/target groups
5. Open `Settings` and confirm quiet hours/backlog/rate limit
6. Confirm worker state on `Status` or `Dashboard`

## Runtime Data and What Not To Commit

Runtime data is local and should never be committed:

- linked Signal account data
- Signal session/config files
- SQLite runtime DB
- QR artifacts
- logs
- temporary files

This repository already ignores those local/runtime artifacts through `.gitignore`.

## Project Structure

```text
app/
  main.py
  config.py
  db.py
  logging.py
  deps.py
  bot_status.py
  domain/
  models/
  services/
  web/

container/
  future containerization work area

migrations/
  SQLite schema

tests/
  focused tests for quiet hours, forwarding, logout, and supporting behavior
```

High-level module responsibilities:

- `app/services/auth.py`
  - linked-device QR login
  - account-state transitions
  - logout / forced local reset
- `app/services/groups.py`
  - group discovery
  - source/target selection persistence
- `app/services/settings.py`
  - settings validation and persistence
- `app/services/forwarder.py`
  - message parsing
  - filtering
  - JSON-RPC send/receive loop
  - dedupe and rate limiting
- `app/services/supervisor.py`
  - worker lifecycle and reconcile decisions
- `app/services/signal_cli.py`
  - `signal-cli` command execution and JSON-RPC process handling

## Testing

Run tests with:

```bash
pytest -q
```

Current tests cover:

- quiet-hours logic
- backlog cutoff behavior
- forwarding of both `dataMessage` and `syncMessage.sentMessage`
- durable dedupe behavior
- logout forced local reset cleanup

## Current Status

The repository is in a good local-app state for further work:

- refactored web app is present
- QR login works through `signal-cli`
- groups/settings/logout flow is implemented
- forwarding worker is implemented
- tests cover key logic paths

## Roadmap

Planned next direction:

- Linux-native packaging
- single-container deployment
- TrueNAS-oriented runtime setup
- productionizing the `container/` area

The current repository is intentionally focused on the refactored application codebase rather than the removed legacy Windows packaging/scripts.
