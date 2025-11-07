# Procedura Python SDK

Beginner-friendly **Python SDK & CLI** for driving a Procedura Agent over **WebSocket/WSS**.
Run modules like `login_password` and `worldstate_snapshot` with *zero code* via the `procedura` CLI, or a tiny Python API.

---

## Features

* **One-line login** (persists session token).
* **Run agent modules** synchronously or with **streaming progress**.
* **Token handling** compatible with your `ws_adapter`:

  * Sends token via **WebSocket subprotocol** (preferred) and **Authorization: Bearer** (fallback).
  * Persists token to `~/.procedura/token` and reuses automatically.
* **Beginner-friendly ergonomics** with a minimal `RemoteAgent` class.

---

## Repository layout

```
procedura/
├─ pyproject.toml                 # build config (points to packages under ./procedura)
└─ procedura_sdk/
   ├─ __init__.py
   ├─ __main__.py                 # enables: python -m procedura_sdk
   ├─ cli.py                      # implements "procedura" command
   └─ remote_agent.py             # RemoteAgent – the core client
```

---

## Requirements

* Python **3.10+**
* `websockets >= 12.0`
* A running Procedura **ws_adapter** endpoint (`ws://` or `wss://`), e.g. `ws://127.0.0.1:8765`.

> **Note (Debian/Ubuntu / WSL):** System Python is PEP 668 “externally managed.” Use a **virtualenv** (recommended) or `pipx`.

---

## Install

### Option A — Project virtualenv (recommended)

```bash
cd /mnt/c/Users/jerem/projects/procedura
python3 -m venv .venv
source .venv/bin/activate

python -m pip install -U pip setuptools wheel
python -m pip install -e .
```

### Option B — pipx (global shim, isolated env)

```bash
sudo apt update && sudo apt install -y pipx
pipx ensurepath
cd /mnt/c/Users/jerem/projects/procedura
pipx install --editable .
```

> You can force system install with `--break-system-packages`, but it’s not recommended.

---

## Quick start

### 1) Log in (stores token)

```bash
procedura --url ws://127.0.0.1:8765 login "admin@procedura.org:secret123" --ttl 7200
```

* Token is saved to **`~/.procedura/token`** for reuse.
* The server may also echo the token via the subprotocol.

### 2) Run a module (sync)

```bash
procedura --url ws://127.0.0.1:8765 run worldstate_snapshot -- --terse
```

> The `--` separates CLI flags from module args.
> This prints the agent’s **live** `AgentWorldState` snapshot.

### 3) Stream a long-running module (async)

```bash
procedura --url ws://127.0.0.1:8765 stream place_ooi_sprites -- --dry-run --n 4 --radius 400
```

You’ll see `started` → `running` updates → `finished`.

---

## Python API

```python
from procedura_sdk import RemoteAgent

ra = RemoteAgent("ws://127.0.0.1:8765")

# Login; supports "email:password" or base64 with optional "b64:" prefix
ra.login_password("admin@procedura.org:secret123", replace=True, device="cli", ttl=3600)

# Fetch the current worldstate
snap = ra.worldstate_snapshot(terse=True)
print(snap)

# Run any module synchronously
result = ra.run("worldstate_snapshot", ["--terse"])
print(result)

# Stream events from an async module
import asyncio
async def main():
    async for ev in ra.run_async_stream("place_ooi_sprites", ["--dry-run", "--n", "4"]):
        print(ev)
asyncio.run(main())
```

---

## How it talks to the server

* **Message shape**:

  ```json
  { "id": "<client-generated>", "cmd": "<module>", "args": ["<module>", "..."], "mode": "sync|async" }
  ```

* **Sync mode**:

  1. Server sends tiny **`ack`** (`{"id":"…","status":"ack"}`).
  2. Then a **targeted** final event (`{"id":"…","status":"finished","result":{...}}`).

* **Async mode**:

  * Immediate `{"status":"started","job_id":"…"}` followed by **targeted** `running` updates and a final `finished` event.

* **Auth**:

  * Client sends token as **subprotocol** (preferred by `ws_adapter`) and as **Authorization: Bearer** header (fallback).
  * Tokens are **idempotent** if you pass a device key (`--device=cli`), matching server behavior.

---

## CLI reference

```
procedura --url <ws-or-wss-endpoint> [--token <session-token>] <command> …

Commands:
  login   "<email:password>" [--attach] [--device <key>] [--ttl <secs>]
  run     <module> [--] [module args...]
  stream  <module> [--] [module args...]

Examples:
  procedura --url ws://127.0.0.1:8765 login "user@example.com:pass" --ttl 7200
  procedura --url ws://127.0.0.1:8765 run worldstate_snapshot -- --terse
  procedura --url ws://127.0.0.1:8765 stream place_ooi_sprites -- --dry-run --n 6
```

> On Windows PowerShell, wrap credentials in single quotes if needed:
> `login 'user@example.com:pass'`

---

## Token storage

* File: **`~/.procedura/token`**
* Override via env: `PROCEDURA_TOKEN_FILE=/custom/path/token`
* On successful `login_password`, the SDK:

  * Saves the token to disk,
  * Immediately adopts it for both subprotocol and Authorization header.

---

## Troubleshooting

* **“externally-managed-environment / PEP 668”**
  Use a venv or `pipx` (see Install section).
* **`procedura: command not found`**
  If using a venv, run `source .venv/bin/activate`. With `pipx`, open a new shell after `pipx ensurepath`.
* **Handshake fails with WSS**
  You may need to trust the CA or extend `_connect()` to pass a custom `ssl.SSLContext`.
* **Running inside Jupyter / already have an event loop**
  The SDK uses `asyncio.run()` in `RemoteAgent.run()`. For notebooks, prefer the async generator `run_async_stream()` or adapt to a loop-aware helper.

---

## Development

```bash
# In repo root (procedura/)
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[dev]"   # if you add optional dev deps later
```

Run from source:

```bash
procedura --help
python -m procedura_sdk --help
```

---

## Roadmap

* TLS options & pinned certs for `wss://`.
* Reconnect/backoff & keep-alive helpers (`__keepalive`).
* Diagnostics (`__diag_ws_metrics`, `__diag_auth`) as `procedura ws diag`.
* Loop-aware sync runner for notebook environments.

---

## License

MIT © 2025 Procedura Corp.

