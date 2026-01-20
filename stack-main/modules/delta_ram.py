from __future__ import annotations

"""
DeltaRAM – incremental diff‑based variant of RuntimeRAM
===========================================================
This subclass stores **delta records** rather than full snapshots:

    ┌────────┐       ┌───────────┐       ┌───────────┐
    │schema=1│ ───▶  │schema=2   │ ───▶  │schema=2   │  …
    │snapshot│  base │Δ changed  │ base  │Δ changed  │
    └────────┘       └───────────┘       └───────────┘

Each commit writes:
    {
        "schema" : 2,
        "rev"    : <int>,            # logical revision counter
        "ts"     : "ISO‑8601",
        "base"   : <head_idx>,       # previous commit index (‑1 if none)
        "changed": {k: v, …},        # keys added/updated
        "deleted": [k1, k2, …]       # keys removed since *base*
    }

Reload reconstructs the dictionary by chasing the *base* chain until it
finds a schema‑1 snapshot, then applies diffs forward.

The original RuntimeRAM remains untouched; existing code keeps using full
snapshots.  You can migrate module‑by‑module—just instantiate
``DeltaRAM`` instead of ``RuntimeRAM``.

(c) 2025 Janusz Jeremiasz Filipiak
"""

import copy
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Dict, List
import shutil

from modules.runtime_ram import RuntimeRAM, ConcurrencyError  # type: ignore

# Type aliases for clarity
Payload = Dict[str, Any]
ChangedDict = Dict[str, Any]
DeletedList = List[str]


class DeltaRAM(RuntimeRAM):  # ─────────────────────────────────────────
    """RuntimeRAM subclass that commits *diffs* against the previous revision."""

    SCHEMA = 2  # increment when record shape changes

    # ------------------------------------------------------------------
    # Construction – extend parent bootstrapping
    # ------------------------------------------------------------------
    def __init__(self, *args,
                 autosave_every: int | None = None,
                 **kwargs):
        """
        Parameters
        ----------
        autosave_every : int | None
            If set, expose it via a .autosave_every attribute so calling
            code can decide when to commit. This value is **not** used
            internally by DeltaRAM.
        """
        super().__init__(*args, **kwargs)
        # Keep a copy of the last committed state for diff computation
        self._base_cache: dict[str, Any] = copy.deepcopy(self._cache)


        # Public counters expected by agent.py  ────────────────────────
        self.autosave_every = autosave_every or 0     # 0 = disabled
        self._ops_since_commit = 0                    # already used by parent

    # ------------------------------------------------------------------
    # Public helper for external callers
    # ------------------------------------------------------------------
    @property
    def ops_since_commit(self) -> int:
        """Expose how many set/del operations happened since last commit."""
        return self._ops_since_commit

    # ------------------------------------------------------------------
    # Override commit to write deltas instead of full payload
    # ------------------------------------------------------------------
    def commit(self, *, compress: bool = True) -> int:  # type: ignore[override]
        with self._lock:
            if not self._dirty:
                return self._head_idx  # nothing to do

            # 1. Compute diff vs. _base_cache
            changed: ChangedDict = {
                k: v for k, v in self._cache.items()
                if k not in self._base_cache or self._base_cache[k] != v
            }
            deleted: DeletedList = [k for k in self._base_cache if k not in self._cache]

            # No actual difference → skip write, just clear dirty flag
            if not changed and not deleted:
                self._dirty = False
                return self._head_idx

            record: Payload = {
                "schema": self.SCHEMA,
                "rev": self._head_idx + 1 if self._head_idx >= 0 else 0,
                "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                "base": self._head_idx,
                "changed": changed,
                "deleted": deleted,
            }

            idx = (
                self._bs.write_compressed(record)
                if compress
                else self._bs.write(record)
            )

            # 2. Book‑keeping
            self._head_idx = idx
            self._dirty = False
            self._ops_since_commit = 0
            self._last_commit_ts = datetime.now(tz=timezone.utc).timestamp()
            self._base_cache = copy.deepcopy(self._cache)
            return idx

    # ------------------------------------------------------------------
    # Override reload – reconstruct dict by applying diffs
    # ------------------------------------------------------------------
    def reload(self, idx: int | None = None) -> None:  # type: ignore[override]
        with self._lock:
            target = idx if idx is not None else self._head_idx
            if target < 0:
                self._cache.clear()
                self._base_cache.clear()
                self._head_idx = -1
                self._dirty = False
                return

            data = self._materialize(target)
            self._cache = data
            self._base_cache = copy.deepcopy(data)
            self._head_idx = target
            self._dirty = False

    # ------------------------------------------------------------------
    # Private – recursively reconstruct state at *idx*
    # ------------------------------------------------------------------
    def _materialize(self, idx: int) -> dict[str, Any]:
        rec = self._bs.read(idx)
        if rec is None:
            return {}

        # Snapshot record – terminate recursion
        if isinstance(rec, Mapping) and rec.get("schema") == 1 and "payload" in rec:
            return dict(rec["payload"])  # shallow copy OK

        # Diff record – recurse to base, then apply
        if isinstance(rec, Mapping) and rec.get("schema") == self.SCHEMA:
            base_idx = rec.get("base", -1)
            state = self._materialize(base_idx) if base_idx >= 0 else {}
            # Apply changes (add/update)
            state.update(rec.get("changed", {}))
            # Apply deletions
            for k in rec.get("deleted", []):
                state.pop(k, None)
            return state

        # Unknown record type → treat as empty
        return {}

    def _reload_latest(self) -> None:          # override
        """Locate newest record (schema 1 **or 2**) and hydrate _cache."""
        idx = self._bs._discover_max_index()   # last written index
        while idx >= 0:
            rec = self._bs.read(idx)
            schema = rec.get("schema") if isinstance(rec, Mapping) else None
            if schema == 1 and "payload" in rec:          # full snapshot
                self._cache = dict(rec["payload"])
                self._head_idx = idx
                self._base_cache = copy.deepcopy(self._cache)
                return
            if schema == self.SCHEMA:                     # diff record
                self._cache = self._materialize(idx)
                self._head_idx = idx
                self._base_cache = copy.deepcopy(self._cache)
                return
            idx -= 1
        # nothing found
        self._cache.clear()
        self._head_idx = -1

    # ───────────────────────── dict-like helpers ──────────────────────────
    def keys(self):
        return self._cache.keys()

    def items(self):
        return self._cache.items()

    def values(self):
        return self._cache.values()

    # ───────────────────────── util  ─────────────────────────
    def delete_bucket(self) -> None:            # modules/delta_ram.py
        """
        Wipe the BitStream bucket backing this DeltaRAM and reset in-memory state.
        Safe to call even if the bucket was already removed.
        """
        # 1. Delegate to BitStream (recursively deletes its directory)
        self._bs.delete_bucket()

        # 2. Clear RAM state so the object can keep running empty
        self._cache.clear()
        self._base_cache.clear()
        self._head_idx = -1
        self._dirty = False
