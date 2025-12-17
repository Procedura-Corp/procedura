"""
bitstream.py – append‑only key/value store with optional Zstandard compression
------------------------------------------------------------------------------
An **OOP** wrapper over *WorldLattice* that now supports
`write_compressed()` / transparent decompression on `read()`.

Example
~~~~~~
>>> bs = BitStream(world_root="runtime_world")
>>> ref = bs.write({"plain": True})          # uncompressed
>>> ref2 = bs.write_compressed({"c": "zstd"})
>>> bs.read(ref2) == {"c": "zstd"}
True

Compressed rows are stored as a base‑85 string with flag ``"c": true`` so
older readers ignore them gracefully.

© 2024‑2025 Janusz Jeremiasz Filipiak
"""
from __future__ import annotations

import json
import base64
from pathlib import Path
from typing import Callable, Any
import shutil, errno

try:
    import zstandard as zstd  # type: ignore
except ModuleNotFoundError:   # fallback keeps the module usable w/o dep
    zstd = None               # write_compressed() will downgrade to write()

from modules.WorldLattice import WorldLattice
from utils.storage import resolve_storage, container_dir

class BitStream:  # ───────────────────────────────────────────────────────────
    """Append‑only integer‑addressed stream backed by a 512³ voxel cube."""

    # ─────────────────────── class helpers (static) ────────────────────────
    @staticmethod
    def _coord_from_index(n: int) -> tuple[int, int, int]:
        """Divide *n* into three base‑512 digits: x (LSB), y, z (MSB)."""
        x = n & 0x1FF
        y = (n >> 9) & 0x1FF
        z = (n >> 18) & 0x1FF
        return x, y, z

    @staticmethod
    def _bisect_last_true(lo: int, hi: int, pred: Callable[[int], bool]) -> int:
        """Greatest *idx* in [lo, hi] where *pred* is True, −1 if none."""
        last = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if pred(mid):
                last = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return last

    # ───────────────────────────── init & helpers ──────────────────────────
    def __init__(
        self,
        *,
        world_id: str = "world",
        world_root: str | Path = "bitstream_root",
    ) -> None:
        """Create or open a bit‑stream bucket centred at (0,0,0)."""
        store = resolve_storage(
            str(world_root) if world_root != "bitstream_root" else None,
            world_id        if world_id    != "world"         else None,
            None,
            default_root="bitstream_root",
            default_world_id="world",
            default_main_dir="dbits",
        )
        self._world_id = store.world_id
        self._world_root = container_dir(store)  # parent of <world_id>

        # One bucket – large enough for 134 M rows
        self._wl = WorldLattice.read_lattice(
            0,
            0,
            0,
            world_id=self._world_id,
            world_root=self._world_root.as_posix(),
            main_dir=store.main_dir,
        )

        self._next_index: int | None = None   # lazy‑initialised on first op

    # ------------------------------------------------------------------
    #  Internal helpers that depend on WorldLattice instance
    # ------------------------------------------------------------------
    def _is_filled(self, rel_x: int, rel_y: int, rel_z: int) -> bool:
        """True iff the voxel at *relative* coord contains user payload."""
        abs_x = self._wl.x + rel_x
        abs_y = self._wl.y + rel_y
        abs_z = self._wl.z + rel_z
        db = self._wl.get(abs_x, abs_y, abs_z)   # creates scaffold if missing
        return db.lbit0.other is not db.lbit1     # scaffold → empty

    def _discover_max_index(self) -> int:
        """Return the greatest used index by scanning ≤ 27 voxels."""
        # Completely empty cube?
        if not self._is_filled(0, 0, 0):
            return -1

        z = self._bisect_last_true(0, 511, lambda zz: self._is_filled(0, 0, zz))
        y = self._bisect_last_true(0, 511, lambda yy: self._is_filled(0, yy, z))
        x = self._bisect_last_true(0, 511, lambda xx: self._is_filled(xx, y, z))
        return x + 512 * y + 262_144 * z

    # ------------------------------------------------------------------
    #  Public API – plain write / read
    # ------------------------------------------------------------------
    def write(self, payload: Any) -> int:
        """Append *payload* (JSON‑serialisable) and return its logical address."""
        if self._next_index is None:
            self._next_index = self._discover_max_index() + 1

        n = self._next_index
        self._next_index += 1

        rel_x, rel_y, rel_z = self._coord_from_index(n)
        abs_x = self._wl.x + rel_x
        abs_y = self._wl.y + rel_y
        abs_z = self._wl.z + rel_z

        record = json.dumps(
            {"index": n, "payload": payload},
            separators=(",", ":")
        )
        
        self._wl.insert(record, abs_x, abs_y, abs_z)
        self._wl.write_lattice()     # persist delta
        return n

    # ------------------------------------------------------------------
    #  Public API – compressed write
    # ------------------------------------------------------------------
    def write_compressed(self, payload: Any) -> int:
        """Same as :py:meth:`write` but stores the *payload* Zstd‑compressed.

        Falls back to plain ``write`` if the *zstandard* module is absent.
        """
        if zstd is None:                     # dependency missing
            return self.write(payload)

        if self._next_index is None:
            self._next_index = self._discover_max_index() + 1

        n = self._next_index
        self._next_index += 1

        rel_x, rel_y, rel_z = self._coord_from_index(n)
        abs_x = self._wl.x + rel_x
        abs_y = self._wl.y + rel_y
        abs_z = self._wl.z + rel_z

        raw  = json.dumps(payload, separators=(",", ":")).encode()
        comp = zstd.ZstdCompressor().compress(raw)
        b85  = base64.b85encode(comp).decode()

        record = json.dumps({"index": n, "c": True, "payload": b85}, separators=(",", ":"))
        self._wl.insert(record, abs_x, abs_y, abs_z)
        self._wl.write_lattice()     # persist delta
        return n

    # ------------------------------------------------------------------
    #  Public API – read (auto‑decompress)
    # ------------------------------------------------------------------
    def read(self, i: int):
        """Return payload at logical address *i* or *None* if absent.

        Automatically decompresses and JSON‑decodes compressed entries.
        """
        rel_x, rel_y, rel_z = self._coord_from_index(i)
        abs_x = self._wl.x + rel_x
        abs_y = self._wl.y + rel_y
        abs_z = self._wl.z + rel_z

        stack = self._wl.get_dict_stack(abs_x, abs_y, abs_z)
        for raw_rec in reversed(stack):
            # records are stored as JSON strings; tolerate dicts for fwd‑compat
            if isinstance(raw_rec, str):
                try:
                    rec = json.loads(raw_rec)
                except json.JSONDecodeError:
                    continue
            else:
                rec = raw_rec

            if rec.get("index") != i:
                continue

            if rec.get("c"):
                if zstd is None:
                    # Reader lacks zstd – expose compressed blob untouched
                    return rec.get("payload")
                try:
                    comp = base64.b85decode(rec["payload"].encode())
                    raw  = zstd.ZstdDecompressor().decompress(comp)
                    return json.loads(raw.decode())
                except Exception:
                    return None
            else:
                return rec.get("payload")
        return None

    # ───────────────────────── util  ─────────────────────────
    def delete_bucket(self) -> None:
        """
        Recursively delete the voxel-cube directory that backs this BitStream.

        This is **destructive** – all rows disappear permanently, so only call
        from maintenance tools such as `clear_diffqueue`.
        """
        bucket_dir = self._world_root / self._world_id
        try:
            shutil.rmtree(bucket_dir)
        except FileNotFoundError:
            # already gone – nothing to do
            return
        except OSError as exc:
            # surface a cleaner message for callers
            raise RuntimeError(f"bitstream: cannot delete bucket {bucket_dir}: {exc}") from exc
