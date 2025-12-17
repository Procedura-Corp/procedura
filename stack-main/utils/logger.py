"""
logger.py – unified file+console+stream logger with pluggable sinks
==================================================================
Adds **real-time streaming hooks** so any component (SpawnManager,
WSAgentAdapter, etc.) can subscribe and forward log entries to external
channels (e.g. WebSockets for the browser terminal).

New in v1.1 (2025-06-01)
------------------------
• log_prompt()   – persist successful LLM calls
• log_failure()  – persist failed LLM calls
• exception()    – drop-in replacement for logging.Logger.exception()
• log_info()     – convenience wrapper for ad-hoc INFO records
• contextlib import (needed for remove_sink)
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
import traceback
import textwrap
from datetime import datetime
from typing import Any, Callable, List, Optional
from collections.abc import Iterable
from utils.types import StoryFrame

# ────────────────────────────────────────────────────────────────
# Wire-tap helper (stdout prints bypass the logger pipeline)
# ────────────────────────────────────────────────────────────────
_WIRE = os.getenv("LOG_WIRE_TAP", "0").strip().lower() in {"1", "true", "yes", "on"}
def _wire_print(*a) -> None:
    if _WIRE:
        try:
            print("[wire:logger]", *a, flush=True)
        except Exception:
            pass

class Logger:
    COLORS = {
        "DEBUG": "\033[90m",    # Dark Gray
        "INDEX": "\033[95m",
        "INFO": "\033[94m",     # Blue
        "WARNING": "\033[93m",  # Yellow
        "ERROR": "\033[91m",    # Red
        "ENDC": "\033[0m",
    }

    # ────────────────────────────────────────────────────────────────
    def __init__(
        self,
        base_log_dir: str = "logs",
        console_log: bool = True,
        log_level: str = "DEBUG",
    ) -> None:
        self.base_log_dir = base_log_dir
        self.console_log = console_log
        self.log_level = log_level.upper()

        # Dynamically updated by WSAdapter so we know how wide to wrap.
        self._term_cols: int | None = None

        # Fan-out subscribers (callables) that receive each log record
        self._sinks: List[Callable[[dict], None]] = []

        # On-disk dirs
        self.prompts_log_dir = os.path.join(self.base_log_dir, "prompts")
        self.failures_log_dir = os.path.join(self.base_log_dir, "failures")
        self.system_log_dir = os.path.join(self.base_log_dir, "system")
        self.story_log_dir  = os.path.join(self.base_log_dir, "story")
        os.makedirs(self.prompts_log_dir, exist_ok=True)
        os.makedirs(self.failures_log_dir, exist_ok=True)
        os.makedirs(self.system_log_dir, exist_ok=True)
        os.makedirs(self.story_log_dir,  exist_ok=True)
        _wire_print(f"init base_dir={self.base_log_dir} level={self.log_level}")

        # ── runtime toggle (default OFF; can be flipped via get_logger()) ──
        self.prompt_logging_enabled = self._env_bool("PROMPT_LOGGING", False)

    # ────────────────────────────────────────────────────────────────
    # Sink management
    # ────────────────────────────────────────────────────────────────
    def add_sink(self, fn: Callable[[dict], None]) -> None:
        """Subscribe *fn* to receive each log record as JSON-serialisable dict."""
        if fn not in self._sinks:
            self._sinks.append(fn)
            _wire_print(f"add_sink fn={getattr(fn,'__name__', type(fn).__name__)} count={len(self._sinks)}")

    def remove_sink(self, fn: Callable[[dict], None]) -> None:
        with contextlib.suppress(ValueError):
            self._sinks.remove(fn)
            _wire_print(f"remove_sink fn={getattr(fn,'__name__', type(fn).__name__)} count={len(self._sinks)}")

    # ────────────────────────────────────────────────────────────────
    # Utilities
    # ────────────────────────────────────────────────────────────────
    def _timestamp(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _write_json(self, directory: str, prefix: str, data: dict) -> str:
        filename = f"{prefix}_{self._timestamp().replace(':', '').replace('-', '')}.json"
        filepath = os.path.join(directory, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return filepath

    def _get_caller_info(self) -> str:
        stack = inspect.stack()
        return stack[3].function if len(stack) > 3 else "<unknown>"

    def _should_log(self, level: str) -> bool:
        order = ["DEBUG", "INFO", "INDEX", "WARNING", "ERROR"]
        return order.index(level.upper()) >= order.index(self.log_level)

    def _console_log(self, text: str, level: str) -> None:
        if not self.console_log:
            return
        color = self.COLORS.get(level, self.COLORS["INFO"])
        endc = self.COLORS["ENDC"]
        
        for logical_line in text.splitlines() or [""]:
            for wrapped in self._wrap(logical_line):
                print(f"{color}{wrapped}{endc}", flush=True)

    def _env_bool(self, name: str, default: bool) -> bool:
        val = os.getenv(name)
        if val is None:
            return default
        return str(val).strip().lower() not in {"0", "false", "no", "off"}

    # ────────────────────────────────────────────────────────────────
    # Make any object JSON‑serialisable by coercing “exotic” values to str
    # ────────────────────────────────────────────────────────────────
    def _json_safe(self, obj: Any) -> Any:
        """Recursively walk *obj* and turn unknown types into strings."""

        # Primitive / already safe
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj

        # Mappings
        if isinstance(obj, dict):
            return {self._json_safe(k): self._json_safe(v) for k, v in obj.items()}

        # Iterables (list, tuple, set, deque, …)
        if isinstance(obj, Iterable):
            return [self._json_safe(v) for v in obj]

        # Fallback – represent by str()
        return str(obj)

    def _emit_to_sinks(self, record: dict) -> None:
        # Fast‑path for StoryFeed segments
        if record.get("type") == "storyframe":
            if not self._sinks:
                _wire_print("emit:storyframe sinks=0 (dropping)")
            else:
                _wire_print(f"emit:storyframe sinks={len(self._sinks)}")
            safe_record = self._json_safe(record)
            for fn in self._sinks:
                try:
                    fn(safe_record)
                except Exception:
                    traceback.print_exc()
            return

        # ----- normal developer‑log flow (wrap long "message" lines) -----
        if "message" in record and record["message"]:
            lines: list[str] = []
            for ln in record["message"].splitlines() or [""]:
                lines.extend(self._wrap(ln))
            record = {**record, "message": "\r\n".join(lines)}

        if not self._sinks:
            _wire_print("emit:log sinks=0 (dropping)")
        else:
            _wire_print(f"emit:log sinks={len(self._sinks)} level={record.get('level')}")

        safe_record = self._json_safe(record)
        for fn in self._sinks:
            try:
                fn(safe_record)
            except Exception:
                traceback.print_exc()

    # ────────────────────────────────────────────────────────────────
    # Terminal-size awareness
    # ────────────────────────────────────────────────────────────────
    def update_term_size(self, cols: int, rows: int | None = None) -> None:
        """Called by WSAdapter whenever the browser resizes the xterm pane."""
        if cols and cols > 0:
            self._term_cols = cols
            _wire_print(f"term_size cols={cols} rows={rows}")

    # Helper: soft-wrap a long line while preserving the original indent.
    def _wrap(self, text: str) -> list[str]:
        if not self._term_cols:
            return [text]

        # Detect existing leading whitespace so continuation lines stay aligned.
        leading_ws = len(text) - len(text.lstrip(" \t"))
        indent = " " * leading_ws

        return textwrap.wrap(
            text,
            width=self._term_cols,
            subsequent_indent=indent,
            break_long_words=False,
            break_on_hyphens=False,
        )

    # ────────────────────────────────────────────────────────────────
    # Core logging
    # ────────────────────────────────────────────────────────────────
    def log_system(self, message: Any, level: str = "INFO") -> None:
        level = level.upper()
        if not self._should_log(level):
            return

        caller = self._get_caller_info()

        if isinstance(message, str):
            safe_message = message
        else:
            safe_message = json.dumps(message, default=str, ensure_ascii=False)

        record = {
            "ts": self._timestamp(),
            "level": level,
            "caller": caller,
            "message": safe_message,
            "payload": message,
        }
        
        # Persist to disk (rotated by timestamp)
        self._write_json(self.system_log_dir, "system", record)

        # Console / stderr
        self._console_log(f"[{level}] ({caller}) {safe_message}", level)

        # Real-time fan-out
        self._emit_to_sinks(record)

    # Convenience wrappers ------------------------------------------
    def debug(self, msg: str, *args):
        self.log_system(msg % args if args else msg, "DEBUG")

    def info(self, msg: str, *args):
        self.log_system(msg % args if args else msg, "INFO")

    def index(self, msg: str, *args):
        self.log_system(msg % args if args else msg, "INDEX")

    def warning(self, msg: str, *args):
        self.log_system(msg % args if args else msg, "WARNING")

    def error(self, msg: str, *args):
        self.log_system(msg % args if args else msg, "ERROR")

    def story_text(self, content: str, **meta):
        self.log_storyframe({"type": "text", "content": content}, meta)

    def story_picture(self, src: str, caption: str | None = None, **meta):
        self.log_storyframe({"type": "picture", "src": src, "caption": caption}, meta)


    # ────────────────────────────────────────────────────────────────
    # Extras utilised by other modules
    # ────────────────────────────────────────────────────────────────
    def log_prompt(
        self,
        prompt: str,
        response: str,
        usage: Optional[dict],
        model: str,
    ) -> None:
        """Persist a successful LLM call and broadcast it (if enabled)."""
        if not self.prompt_logging_enabled:
            return

        record = {
            "ts": self._timestamp(),
            "type": "prompt",
            "model": model,
            "prompt": prompt,
            "response": response,
            "usage": usage or {},
        }
        path = self._write_json(self.prompts_log_dir, "prompt", record)
        self._console_log(f"[PROMPT] {model} logged → {path}", "DEBUG")
        self._emit_to_sinks(record)

    def log_failure(self, prompt: str, error: str, model: str) -> None:
        """Persist an LLM failure and broadcast it."""
        record = {
            "ts": self._timestamp(),
            "type": "failure",
            "model": model,
            "prompt": prompt,
            "error": error,
        }
        path = self._write_json(self.failures_log_dir, "failure", record)
        self._console_log(f"[FAILURE] {model}: {error} → {path}", "ERROR")
        self._emit_to_sinks(record)

    def log_info(self, message: str) -> None:
        """
        Light-weight alias for `log_system(message, "INFO")`.

        Useful when an external module wants to attach extra metadata
        before logging:
            logger.log_info(json.dumps({"event": "cache_hit", "key": k}))
        """
        self.log_system(message, "INFO")

    # ────────────────────────────────────────────────────────────────
    # Story / UI segment logging
    # ────────────────────────────────────────────────────────────────
    def log_storyframe(
        self,
        frame: "StoryFrame",
        meta: Optional[dict] = None,
    ) -> None:
        """
        Append a UI‑level StoryFrame to all sinks *without* mixing it
        with the normal terminal log stream.
        """
        record = {
            "ts": self._timestamp(),
            "type": "storyframe",
            "frame": frame,
            **(meta or {}),          # optional: level, caller, tags …
        }

        # Persist for replay / auditing
        self._write_json(self.story_log_dir, "frame", record)

        # Fan‑out (no console echo — it is a UI artefact, not a dev log)
        self._emit_to_sinks(record)


    # Fully compatible with logging.Logger.exception(...)
    def exception(self, msg: str, *args) -> None:
        """Log an ERROR plus the current traceback."""
        text = msg % args if args else msg
        stack = traceback.format_exc()
        self.log_system(f"{text}\n{stack}", "ERROR")

    # ────────────────────────────────────────────────────────────────
    # Debug helpers
    # ────────────────────────────────────────────────────────────────
    def dump_stack(self):
        """Write the current stack to disk and return the path."""
        stack_log = {
            "timestamp": self._timestamp(),
            "stack": traceback.format_stack(),
        }
        path = self._write_json(self.system_log_dir, "stack_dump", stack_log)
        self._console_log(f"[STACK DUMP] {path}", "DEBUG")
        self._emit_to_sinks(
            {"level": "DEBUG", "message": f"Stack dumped to {path}", "ts": self._timestamp()}
        )
        return path

    # ────────────────────────────────────────────────────────────────
    # Runtime toggle API (import get_logger() and flip from a module)
    # ────────────────────────────────────────────────────────────────
    def set_prompt_logging(self, enabled: bool) -> None:
        self.prompt_logging_enabled = bool(enabled)
        self._console_log(f"[CONFIG] prompt_logging={self.prompt_logging_enabled}", "DEBUG")
        self._emit_to_sinks({
            "ts": self._timestamp(), "type": "config",
            "key": "prompt_logging", "value": self.prompt_logging_enabled
        })

    def get_logging_config(self) -> dict:
        return {"prompt_logging": self.prompt_logging_enabled}

# ─────────────────────────── singleton factory ────────────────────────────
_logger_instance: Logger | None = None


def get_logger() -> Logger:
    """Return a process-wide shared Logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
        _wire_print("get_logger: created new Logger singleton")
    return _logger_instance