"""
metrics.py – Observability wrapper for Procedura CLI
====================================================
Provides structured event logging (BitStream) and state persistence (DeltaRAM).
Includes sensitive data redaction and schema validation.
"""
from __future__ import annotations

import json
import time
import os
import sys
import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

# Add stack-main to sys.path so we can import modules.*
STACK_MAIN_PATH = Path(__file__).parent.parent / "stack-main"
if str(STACK_MAIN_PATH) not in sys.path:
    sys.path.insert(0, str(STACK_MAIN_PATH))

from modules.bitstream import BitStream
from modules.delta_ram import DeltaRAM
from utils.logger_instance import logger

# Default configuration
DEFAULT_WORLD_ROOT = "runtime_ram"
EVENTS_WORLD_ID = "cli_events"
STATE_WORLD_ID = "cli_state"

# Sensitive keys to redact (lowercase)
SENSITIVE_KEYS = {
    "password", "token", "secret", "authorization", "key", 
    "session_token", "access_token", "refresh_token", "credential", 'login_password'
}

# Commands that have sensitive arguments (cmd -> list of arg indices to redact)
SENSITIVE_COMMAND_ARGS = {
    "login": [0],
    "login_password": [0],
}

class MetricsClient:
    def __init__(self, world_root: str = DEFAULT_WORLD_ROOT):
        self.world_root = world_root
        # Lazy initialization to avoid IO on import
        self._events_bs: Optional[BitStream] = None
        self._state_dr: Optional[DeltaRAM] = None
        self._schema_version = 1

    @property
    def events(self) -> BitStream:
        if self._events_bs is None:
            self._events_bs = BitStream(
                world_id=EVENTS_WORLD_ID, 
                world_root=self.world_root
            )
        return self._events_bs

    @property
    def state(self) -> DeltaRAM:
        if self._state_dr is None:
            self._state_dr = DeltaRAM(
                world_id=STATE_WORLD_ID, 
                world_root=self.world_root
            )
        return self._state_dr

    def record_event(self, 
                     cmd: str, 
                     args: List[str], 
                     msg_id: str, 
                     start_ts: float,
                     status: str,
                     ack_ts: Optional[float] = None,
                     final_ts: Optional[float] = None,
                     job_id: Optional[str] = None,
                     result: Any = None,
                     error: Optional[str] = None) -> int:
        """
        Record a CLI execution event to BitStream.
        Calculates latencies and redacts sensitive data.
        """
        now = time.time()
        final_ts = final_ts or now
        
        ack_latency = (ack_ts - start_ts) * 1000 if ack_ts else None
        final_latency = (final_ts - start_ts) * 1000

        # Prepare result summary (redacted)
        result_summary = self.redact_sensitive(result)
        
        # Redact sensitive arguments
        safe_args = self._redact_args(cmd, args)
        
        payload_size = len(json.dumps(result_summary)) if result_summary else 0

        event = {
            "schema": self._schema_version,
            "ts": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
            "cmd": cmd,
            "args": safe_args,
            "msg_id": msg_id,
            "job_id": job_id,
            "ack_ts": datetime.fromtimestamp(ack_ts, tz=timezone.utc).isoformat() if ack_ts else None,
            "final_ts": datetime.fromtimestamp(final_ts, tz=timezone.utc).isoformat(),
            "ack_latency_ms": round(ack_latency, 2) if ack_latency is not None else None,
            "final_latency_ms": round(final_latency, 2),
            "status": status,
            "result_summary": result_summary,
            "payload_size": payload_size,
            "error": error,
            "agent_version": "0.1.0"  # TODO: Get from package
        }

        # Write compressed record to BitStream
        idx = self.events.write_compressed(event)

        # Also write to plain JSON for easy inspection
        self._write_json(event)
        
        return idx

    def _write_json(self, event: Dict[str, Any]) -> None:
        """Append event to a plain JSON file (as a list of objects)."""
        try:
            # Resolve path: <world_root>/events.json
            root = Path(self.world_root)
            if not root.is_absolute():
                env_base = os.getenv("PROCEDURA_DATA_ROOT")
                base = Path(env_base).expanduser().resolve() if env_base else Path.cwd().resolve()
                root = base / self.world_root
            
            root.mkdir(parents=True, exist_ok=True)
            log_path = root / "events.json"
            
            # Read existing data or start new list
            data = []
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            data = json.loads(content)
                            if not isinstance(data, list):
                                data = [] # Reset if corrupted/not a list
                except (json.JSONDecodeError, OSError):
                    data = []

            # Append new event
            data.append(event)

            # Write back atomically
            temp_path = log_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            os.replace(temp_path, log_path)

        except Exception:
            # Don't crash the CLI if logging fails
            pass

    def save_error(self, error_data: Dict[str, Any]) -> None:
        """
        Save error responses to a separate errors.json file.
        Called when receiving responses with status: "error".
        """
        try:
            # Resolve path: <world_root>/errors.json
            root = Path(self.world_root)
            if not root.is_absolute():
                env_base = os.getenv("PROCEDURA_DATA_ROOT")
                base = Path(env_base).expanduser().resolve() if env_base else Path.cwd().resolve()
                root = base / self.world_root
            
            root.mkdir(parents=True, exist_ok=True)
            errors_path = root / "errors.json"
            
            # Add timestamp to error data
            error_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **error_data
            }
            
            # Read existing errors or start new list
            errors = []
            if errors_path.exists():
                try:
                    with open(errors_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            errors = json.loads(content)
                            if not isinstance(errors, list):
                                errors = []
                except (json.JSONDecodeError, OSError):
                    errors = []

            # Append new error
            errors.append(error_entry)

            # Write back atomically
            temp_path = errors_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(errors, f, indent=2, ensure_ascii=False)
            
            os.replace(temp_path, errors_path)

        except Exception:
            # Don't crash the CLI if error logging fails
            pass

    def set_state(self, key: str, value: Any, commit: bool = True) -> int:
        """Update persistent state in DeltaRAM."""
        self.state.set(key, value)
        if commit:
            return self.state.commit()
        return -1

    def _redact_args(self, cmd: str, args: List[str]) -> List[str]:
        """Redact sensitive arguments based on command name."""
        if cmd not in SENSITIVE_COMMAND_ARGS or not args:
            return args
        
        indices = SENSITIVE_COMMAND_ARGS[cmd]
        new_args = list(args)
        for idx in indices:
            if 0 <= idx < len(new_args):
                # Don't redact flags just in case
                if not new_args[idx].startswith("-"):
                     new_args[idx] = "<redacted>"
        return new_args

    def redact_sensitive(self, obj: Any) -> Any:
        """Recursively redact sensitive keys in dictionaries."""
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                if k.lower() in SENSITIVE_KEYS:
                    new_obj[k] = "<redacted>"
                else:
                    new_obj[k] = self.redact_sensitive(v)
            return new_obj
        elif isinstance(obj, list):
            return [self.redact_sensitive(item) for item in obj]
        return obj

# Singleton instance
_metrics_instance: Optional[MetricsClient] = None

def get_metrics() -> MetricsClient:
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = MetricsClient()
    return _metrics_instance
