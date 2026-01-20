from __future__ import annotations

"""
RuntimeRAM – mutable KV store backed by BitStream snapshots
==========================================================
This module implements the *snapshot* variant discussed in the design
blueprint.  Each ``commit()`` serialises the entire key–value dictionary
and appends it to a BitStream bucket.  The BitStream index of the commit
serves as the *revision ID*.

Later we can upgrade to diff‑based commits without breaking callers –
the public API intentionally hides the underlying record format.

© 2025 Janusz Jeremiasz Filipiak
"""

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping
from pathlib import Path
from typing import Any, Dict, List

from modules.bitstream import BitStream  # Local project import
from utils.logger_instance import logger

class ConcurrencyError(RuntimeError):
    """Raised when the underlying BitStream head has advanced externally."""


class RuntimeRAM:  # ──────────────────────────────────────────────────────────
    """Mutable dictionary persisted as *full‑snapshot* records in BitStream."""

    # ---------------------------------------------------------------------
    # Construction & boot‑strapping
    # ---------------------------------------------------------------------
    def __init__(
        self,
        *,
        world_id: str = "world",
        world_root: str = "runtime_ram",
        autosave_ops: int | None = None,
        autosave_seconds: int | None = None,
    ) -> None:
        """Open or create a RuntimeRAM bucket.

        Parameters
        ----------
        bucket_id : str, default "runtime_ram"
            Name of the BitStream bucket.  Multiple RuntimeRAM instances can
            coexist in separate buckets.
        world_root : str | None
            Root directory on disk.  Follows BitStream defaults if *None*.
        autosave_ops : int | None
            Automatically ``commit()`` after *N* mutating operations.
        autosave_seconds : int | None
            Automatically ``commit()`` every *T* seconds (checked lazily on
            each mutation).  Requires the wall‑clock; not a background thread.
        """
        self._bs = BitStream(world_id=world_id, world_root=world_root or "runtime_ram")

        # In‑memory working copy and pointers
        self._cache: dict[str, Any] = {}
        self._head_idx: int = -1
        self._dirty: bool = False

        # Autosave settings
        self._autosave_ops = autosave_ops if (autosave_ops and autosave_ops > 0) else None
        self._autosave_seconds = autosave_seconds if (autosave_seconds and autosave_seconds > 0) else None
        self._ops_since_commit = 0
        self._last_commit_ts: float = time.time()

        # Concurrency – simple local lock (not cross‑process!)
        self._lock = threading.RLock()

        # Bootstrap from the latest snapshot (if any)
        self._reload_latest()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _reload_latest(self) -> None:
        """Locate and load the most recent snapshot in the BitStream."""
        # BitStream exposes no *tail pointer*; scan backwards until a payload
        # decodes successfully.  The cube is sparse → at most ~27 reads.
        idx = self._bs._discover_max_index()  # pylint: disable=protected-access
        while idx >= 0:
            rec = self._bs.read(idx)
            if isinstance(rec, Mapping) and rec.get("schema") == 1 and "payload" in rec:
                self._cache = dict(rec["payload"])  # shallow copy
                self._head_idx = idx
                return
            idx -= 1
        # No snapshot found – start empty
        self._cache.clear()
        self._head_idx = -1

    def _maybe_autosave(self) -> None:
        """Check autosave thresholds and commit if necessary."""
        if not self._dirty:
            return

        if self._autosave_ops is not None and self._ops_since_commit >= self._autosave_ops:
            self.commit()
            return

        if self._autosave_seconds is not None and (time.time() - self._last_commit_ts) >= self._autosave_seconds:
            self.commit()

    # ------------------------------------------------------------------
    # Dict‑like public API
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any | None = None) -> Any | None:
        return self._cache.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._cache[key]

    def set(self, key: str, value: Any) -> "RuntimeRAM":
        with self._lock:
            self._cache[key] = value
            self._mark_dirty()
        return self

    __setitem__ = set  # alias

    def update(self, mapping: Mapping[str, Any]) -> "RuntimeRAM":
        with self._lock:
            self._cache.update(mapping)
            self._mark_dirty()
        return self

    def delete(self, key: str, *, silent: bool = False) -> "RuntimeRAM":
        with self._lock:
            if silent:
                self._cache.pop(key, None)
            else:
                del self._cache[key]
            self._mark_dirty()
        return self

    def clear(self) -> "RuntimeRAM":
        with self._lock:
            self._cache.clear()
            self._mark_dirty()
        return self

    def as_dict(self) -> dict[str, Any]:
        """Return a *shallow* copy of the working dictionary."""
        return dict(self._cache)

    # ------------------------------------------------------------------
    # Revision & persistence controls
    # ------------------------------------------------------------------
    def head(self) -> int:
        """Current BitStream index of last committed snapshot (−1 if none)."""
        return self._head_idx

    def commit(self, *, compress: bool = True) -> int:
        """Persist the current dictionary to BitStream and return its index."""
        with self._lock:
            if not self._dirty:
                return self._head_idx  # no-op

            record = {
                "schema": 1,  # ← reserved for future migrations
                "rev": self._head_idx + 1 if self._head_idx >= 0 else 0,
                "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                "payload": self._cache,
            }
            idx = (
                self._bs.write_compressed(record)
                if compress
                else self._bs.write(record)
            )
            self._head_idx = idx
            self._dirty = False
            self._ops_since_commit = 0
            self._last_commit_ts = time.time()
            return idx

    def reload(self, idx: int | None = None) -> None:
        """Load snapshot at *idx* (default: latest head)."""
        with self._lock:
            target = idx if idx is not None else self._head_idx
            if target < 0:
                self._cache.clear()
                self._head_idx = -1
                self._dirty = False
                return

            rec = self._bs.read(target)
            if not (isinstance(rec, Mapping) and rec.get("schema") == 1 and "payload" in rec):
                raise ValueError(f"BitStream index {target} does not contain a RuntimeRAM snapshot.")

            self._cache = dict(rec["payload"])
            self._head_idx = target
            self._dirty = False

    def history(self, n: int = 10) -> list[tuple[int, str]]:
        """Return a list of *(idx, timestamp)* tuples for the last *n* snapshots."""
        out: list[tuple[int, str]] = []
        idx = self._bs._discover_max_index()  # pylint: disable=protected-access
        while idx >= 0 and len(out) < n:
            rec = self._bs.read(idx)
            if isinstance(rec, Mapping) and rec.get("schema") == 1:
                out.append((idx, str(rec.get("ts"))))
            idx -= 1
        return out

    # ------------------------------------------------------------------
    # Mutation bookkeeping helpers
    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        self._dirty = True
        self._ops_since_commit += 1
        self._maybe_autosave()

    def __iter__(self):
        return iter(self._cache)

    def __len__(self):
        return len(self._cache)