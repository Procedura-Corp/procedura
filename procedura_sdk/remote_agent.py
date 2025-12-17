# procedura_sdk/remote_agent.py
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import uuid
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, List, Optional

import websockets

from procedura_sdk.metrics import get_metrics

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
      - request/response correlation via 'id' (and remap to 'job_id' when provided)
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
                # Route by 'id' (aka client msg id) or server 'job_id'
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

    async def _request_sync(
        self,
        cmd: str,
        args: List[str],
        *,
        ack_timeout: float = 10.0,
        final_timeout: float = 600.0,
    ) -> dict:
        """
        For ws_adapter 'sync' requests:
          - server usually sends {"id": <msg_id>, "status": "ack"[,"job_id": "..."]}
          - then a targeted final: {"id": <msg_id> OR "job_id": "...", "status": "finished", "result": ...}
          - some errors come as a single immediate {"status": "error"} (no ack).
        """
        msg_id = uuid.uuid4().hex[:8]
        start_ts = time.time()
        ack_ts: Optional[float] = None
        
        q: "asyncio.Queue[dict]" = asyncio.Queue()
        self._by_job[msg_id] = q
        job_id_key_added = None
        
        # Metrics helper
        def _record(status: str, result: Any = None, error: str = None, job_id: str = None):
            metrics = get_metrics()
            metrics.record_event(
                cmd=cmd,
                args=args,
                msg_id=msg_id,
                start_ts=start_ts,
                status=status,
                ack_ts=ack_ts,
                final_ts=time.time(),
                job_id=job_id or job_id_key_added,
                result=result,
                error=error
            )
            # Save error responses to separate errors.json
            if status == "error" and isinstance(result, dict):
                metrics.save_error(result)

        try:
            await self._send({"id": msg_id, "cmd": cmd, "args": args, "mode": "sync"})

            # 1) First frame could be 'ack' OR immediate 'error'/'finished'
            try:
                first = await asyncio.wait_for(q.get(), timeout=ack_timeout)
                ack_ts = time.time()
            except asyncio.TimeoutError:
                err_msg = f"timeout waiting for ack after {ack_timeout}s"
                _record("timeout", error=err_msg)
                return {
                    "status": "error",
                    "code": "ACK_TIMEOUT",
                    "message": err_msg,
                    "cmd": cmd,
                }
            except asyncio.CancelledError:
                _record("error", error="ack wait cancelled")
                return {
                    "status": "error",
                    "code": "ACK_CANCELLED",
                    "message": "ack wait cancelled",
                    "cmd": cmd,
                }

            # If server immediately finished/errored, return it.
            status = first.get("status")
            if status in {"error", "finished"}:
                # For errors, pass the whole object as result to capture extra context (like 'coord')
                res = first.get("result") if status == "finished" else first
                _record(status, result=res, error=first.get("message"), job_id=first.get("job_id"))
                return first

            # NEW: if ack includes a server job_id, also route by that key
            job_id = first.get("job_id")
            if isinstance(job_id, str) and job_id:
                self._by_job[job_id] = q
                job_id_key_added = job_id

            # 2) Wait for targeted final (could arrive with id=msg_id or job_id)
            try:
                while True:
                    ev = await asyncio.wait_for(q.get(), timeout=final_timeout)
                    status = ev.get("status")
                    if status in {"finished", "error"}:
                        # For errors, pass the whole object as result to capture extra context
                        res = ev.get("result") if status == "finished" else ev
                        _record(status, result=res, error=ev.get("message"), job_id=ev.get("job_id"))
                        return ev
            except asyncio.TimeoutError:
                err_msg = f"timeout waiting for final result after {final_timeout}s"
                _record("timeout", error=err_msg)
                return {
                    "status": "error",
                    "code": "FINAL_TIMEOUT",
                    "message": err_msg,
                    "cmd": cmd,
                }
            except asyncio.CancelledError:
                _record("error", error="final wait cancelled")
                return {
                    "status": "error",
                    "code": "FINAL_CANCELLED",
                    "message": "final wait cancelled",
                    "cmd": cmd,
                }
        finally:
            self._by_job.pop(msg_id, None)
            if job_id_key_added:
                self._by_job.pop(job_id_key_added, None)

    async def _request_async_stream(self, cmd: str, args: List[str]) -> AsyncGenerator[dict, None]:
        """
        For ws_adapter 'async' requests:
          - immediate response: {"id": <msg_id>, "status": "started", "job_id": "..."}
          - then targeted frames (by "id" OR "job_id") → ('running' ... 'finished')
        """
        msg_id = uuid.uuid4().hex[:8]
        q: "asyncio.Queue[dict]" = asyncio.Queue()
        self._by_job[msg_id] = q
        job_id_key_added = None
        try:
            await self._send({"id": msg_id, "cmd": cmd, "args": args, "mode": "async"})
            started = await asyncio.wait_for(q.get(), timeout=10.0)

            # NEW: also bind the same queue to server job_id for subsequent frames
            job_id = started.get("job_id")
            if isinstance(job_id, str) and job_id:
                self._by_job[job_id] = q
                job_id_key_added = job_id

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
            if job_id_key_added:
                self._by_job.pop(job_id_key_added, None)

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
    def run(
        self,
        module: str,
        args: List[str] | None = None,
        *,
        ack_timeout: float = 10.0,
        final_timeout: float = 600.0,
    ) -> Any:
        return asyncio.run(self._run_sync(module, args or [], ack_timeout=ack_timeout, final_timeout=final_timeout))

    async def _run_sync(self, module: str, args: List[str], *, ack_timeout: float, final_timeout: float) -> Any:
        # Do NOT prepend the module; ws_adapter already does that.
        ev = await self._request_sync(module, args, ack_timeout=ack_timeout, final_timeout=final_timeout)
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
            
            # Check if worldstate_snapshot has empty entities (init failed)
            if module == "worldstate_snapshot" and isinstance(out, dict):
                entities = out.get("entities")
                if isinstance(entities, dict) and len(entities) == 0:
                    error_response = {
                        "status": "error",
                        "code": "EMPTY_WORLD",
                        "message": "World not initialized: entities is empty",
                        "cmd": module,
                        "result": out
                    }
                    get_metrics().save_error(error_response)

            return out
        # Graceful error bubble-up
        if status == "error":
            # return structured dict so CLI can print JSON nicely
            return ev
        raise RuntimeError(ev.get("message") or "request failed")

    # Async stream – yields events (running → finished)
    async def run_async_stream(self, module: str, args: List[str] | None = None) -> AsyncGenerator[dict, None]:
        async for ev in self._request_async_stream(module, (args or [])):
            yield ev

