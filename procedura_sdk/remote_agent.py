# procedura_sdk/remote_agent.py
from __future__ import annotations

import asyncio
import contextlib   # ← needed by _close()
import json
import os
import pathlib
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, List, Optional

import websockets

TOKEN_PATH = pathlib.Path(os.getenv("PROCEDURA_TOKEN_FILE", "~/.procedura/token")).expanduser()

@dataclass
class WSConfig:
    url: str                          # e.g. "wss://example.com:8765" or "ws://127.0.0.1:8765"
    subprotocol_token: Optional[str] = None
    auth_header_token: Optional[str]  = None
    ping_interval: int = 120
    ping_timeout:  int = 300
    connect_timeout: float = 5.0

def _load_saved_token() -> Optional[str]:
    try:
        return TOKEN_PATH.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None

def _save_token(tok: str | None) -> None:
    if not tok:
        return
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(tok, encoding="utf-8")

class RemoteAgent:
    """
    Minimal client for ws_adapter:
      - request/response correlation via 'id'
      - sync runs: returns final 'finished.result'
      - async runs: yields events ('running' ... 'finished')
    """

    def __init__(self, url: str, token: Optional[str] = None):
        tok = token or _load_saved_token()
        self.cfg = WSConfig(
            url=url,
            subprotocol_token = tok,
            auth_header_token = tok,
        )
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._inbox: "asyncio.Queue[dict]" = asyncio.Queue()
        self._by_job: dict[str, "asyncio.Queue[dict]"] = {}

    # ─────────────────────────── connection ───────────────────────────

    async def _connect(self) -> None:
        if self._ws and not self._ws.closed:
            return
        headers = {}
        if self.cfg.auth_header_token:
            headers["Authorization"] = f"Bearer {self.cfg.auth_header_token}"
        subprotocols = [self.cfg.subprotocol_token] if self.cfg.subprotocol_token else None
        self._ws = await asyncio.wait_for(
            websockets.connect(
                self.cfg.url,
                extra_headers=headers or None,
                subprotocols=subprotocols,
                ping_interval=self.cfg.ping_interval,
                ping_timeout=self.cfg.ping_timeout,
                max_size=8 * 1024 * 1024,
            ),
            timeout=self.cfg.connect_timeout,
        )
        # start receiver pump
        self._recv_task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        try:
            assert self._ws
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                # Route by 'id' (aka job_id)
                jid = str(msg.get("id") or msg.get("job_id") or "")
                if jid and jid in self._by_job:
                    await self._by_job[jid].put(msg)
                else:
                    await self._inbox.put(msg)
        except Exception:
            pass  # closed is fine

    async def _close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
            self._recv_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

    # ─────────────────────────── low-level send ───────────────────────────

    async def _send(self, payload: dict) -> None:
        await self._connect()
        assert self._ws
        await self._ws.send(json.dumps(payload))

    # ─────────────────────────── request patterns ───────────────────────────

    async def _request_sync(self, cmd: str, args: List[str]) -> dict:
        """
        For ws_adapter 'sync' requests:
          - server sends {"id": <msg_id>, "status": "ack"}
          - and also a targeted event: {"id": <msg_id>, "status": "finished", "result": ...}
        """
        msg_id = uuid.uuid4().hex[:8]
        q: "asyncio.Queue[dict]" = asyncio.Queue()
        self._by_job[msg_id] = q
        try:
            await self._send({"id": msg_id, "cmd": cmd, "args": args, "mode": "sync"})
            # 1) tiny ACK (we don't need to inspect it)
            _ = await asyncio.wait_for(q.get(), timeout=10.0)
            # 2) targeted final frame
            while True:
                ev = await asyncio.wait_for(q.get(), timeout=120.0)
                if ev.get("status") in {"finished", "error"}:
                    return ev
        finally:
            self._by_job.pop(msg_id, None)

    async def _request_async_stream(self, cmd: str, args: List[str]) -> AsyncGenerator[dict, None]:
        """
        For ws_adapter 'async' requests:
          - immediate response: {"id": <msg_id>, "status": "started", "job_id": "..."}
          - then targeted frames ('running' ... 'finished')
        """
        msg_id = uuid.uuid4().hex[:8]
        q: "asyncio.Queue[dict]" = asyncio.Queue()
        self._by_job[msg_id] = q
        try:
            await self._send({"id": msg_id, "cmd": cmd, "args": args, "mode": "async"})
            started = await asyncio.wait_for(q.get(), timeout=10.0)
            yield {"phase": "started", **started}
            while True:
                ev = await asyncio.wait_for(q.get(), timeout=3600.0)
                st = ev.get("status")
                if st == "running":
                    yield {"phase": "running", **ev}
                elif st in {"finished", "error"}:
                    yield {"phase": st, **ev}
                    return
        finally:
            self._by_job.pop(msg_id, None)

    # ─────────────────────────── public high-level API ───────────────────────────

    def login_password(self, credential: str, *, replace: bool = True, device: str = "cli", ttl: int = 3600) -> dict:
        """
        credential: "email:password" or b64 with optional "b64:" prefix
        """
        flags = [
            "--replace" if replace else "--attach",
            f"--device={device}",
            f"--ttl={ttl}",
        ]
        return self.run("login_password", [credential] + flags)

    def worldstate_snapshot(self, terse: bool = True) -> dict:
        args = ["--terse"] if terse else []
        return self.run("worldstate_snapshot", args)

    # Core runner (sync) – returns final result or raises on error.
    def run(self, module: str, args: List[str] | None = None) -> Any:
        return asyncio.run(self._run_sync(module, args or []))

    async def _run_sync(self, module: str, args: List[str]) -> Any:
        ev = await self._request_sync(module, args)
        status = ev.get("status")
        if status == "finished":
            out = ev.get("result")
            # Persist and adopt a newly issued token from login_password
            if module == "login_password" and isinstance(out, dict):
                tok = out.get("session_token") or None
                if tok:
                    _save_token(tok)
                    self.cfg.subprotocol_token = tok
                    self.cfg.auth_header_token = tok
            return out
        raise RuntimeError(ev.get("message") or "request failed")

    # Async stream – yields events (running → finished)
    async def run_async_stream(self, module: str, args: List[str] | None = None) -> AsyncGenerator[dict, None]:
        async for ev in self._request_async_stream(module, (args or [])):
            yield ev

