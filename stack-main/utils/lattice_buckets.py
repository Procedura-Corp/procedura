"""
World‑root aware bucket helpers
===============================

This module is a **drop‑in replacement** for the original *utils.lattice_buckets*
with one important upgrade:

*All path helpers can now generate per‑world directories* while remaining 100 %
backwards‑compatible with the legacy layout (`dbits/buckets/…`).

Key points
----------
* The public API (`bucket_hash`, `file_path_for_coords`, etc.) is unchanged.
* **Optional kwargs** `world_root` and `main_dir` let callers override the path
  without touching global state.
* Existing code that doesn’t pass those kwargs keeps writing to the original
  locations.
"""
from __future__ import annotations

import hashlib
import os
from typing import Tuple, Optional

# ─────────────────────────────── Parameters ────────────────────────────────

# Per‑world content lives under  <world_root>/<main_dir>/buckets/
# Legacy code used just <main_dir>/buckets/ so we keep that as the default.

MAIN_DIRECTORY: str = "dbits"  # legacy default for persistence directory
BUCKET_ROOT_LEGACY: str = os.path.join(MAIN_DIRECTORY, "buckets")  # ← kept for old callers

# Hash‑bucket parameters (must match AlgorithmicMemory insert logic)
SCALE_XY: int = 1001          # lattice units per grid in X/Y
BUCKET_XY: int = 1001         # width/height of a bucket in lattice units
ALT_BUCKET_SZ: int = 1001     # height of a bucket in Z

__all__ = [
    "bucket_index",
    "bucket_center",
    "bucket_id_tuple",
    "bucket_id_md5",
    "bucket_hash",
    "area_id_from_coords",
    "file_path_for_coords",
    "ensure_bucket_dir",
    "bucket_center_coords",
]

# ───────────────────────────── Internal helpers ────────────────────────────

def _compose_bucket_base(world_root: Optional[str], main_dir: str) -> str:
    """Return the base directory that holds *buckets* for a given world.

    Parameters
    ----------
    world_root : str | None
        Top‑level folder that namespaces a *world* (e.g. ``"world/earth"``).
        If *None*, the legacy layout ``<main_dir>/buckets`` is used.
    main_dir : str
        Name of the directory that stores lattice persistence (default: ``dbits``).
    """
    if world_root is None:
        return os.path.join(main_dir, "buckets")  # ← legacy path
    return os.path.join(world_root, main_dir, "buckets")

# ───────────────────────── Bucket math (unchanged) ─────────────────────────

def bucket_index(x: int, y: int, z: int) -> Tuple[int, int, int]:
    """Return integer bucket indices ``(bx, by, bz)`` for lattice coord *(x,y,z)*."""
    bx = (x + BUCKET_XY // 2) // BUCKET_XY
    by = (y + BUCKET_XY // 2) // BUCKET_XY
    bz = (z + ALT_BUCKET_SZ // 2) // ALT_BUCKET_SZ
    return bx, by, bz


def bucket_center(x: int, y: int, z: int) -> Tuple[int, int, int]:
    """Return the lattice‑unit centre of the bucket containing ``(x,y,z)``."""
    bx, by, bz = bucket_index(x, y, z)
    return bx * BUCKET_XY, by * BUCKET_XY, bz * ALT_BUCKET_SZ

# ───────────────────── Fast in‑memory bucket identifiers ───────────────────

def bucket_id_tuple(x: int, y: int, z: int) -> Tuple[int, int, int]:
    """3‑tuple bucket key for dict look‑ups."""
    return bucket_index(x, y, z)


def bucket_id_md5(bid: Tuple[int, int, int]) -> str:
    """Convert a ``(bx,by,bz)`` tuple into the legacy MD5 string used on disk."""
    return hashlib.md5(f"{bid[0]}_{bid[1]}_{bid[2]}".encode()).hexdigest()

# Legacy wrapper – kept for backwards compatibility with on‑disk paths

def bucket_hash(x: int, y: int, z: int) -> str:  # noqa: N802 – public name kept
    return bucket_id_md5(bucket_id_tuple(x, y, z))

# ───────────────────────────── File‑path helpers ───────────────────────────

def area_id_from_coords(x: int, y: int, z: int) -> str:
    """Return MD5 hash identifying the bucket that contains ``(x,y,z)``."""
    bx, by, bz = bucket_index(x, y, z)
    return hashlib.md5(f"{bx}_{by}_{bz}".encode()).hexdigest()


def file_path_for_coords(
    x: int,
    y: int,
    z: int,
    *,
    world_root: Optional[str] = None,
    main_dir: str = MAIN_DIRECTORY,
) -> str:
    """Return the on‑disk directory for the lattice anchored at ``(x,y,z)``.

    • **Legacy mode** (``world_root=None``) → ``dbits/buckets/<area>``
    • **Per‑world mode** → ``<world_root>/<main_dir>/buckets/<area>``
    """
    base = _compose_bucket_base(world_root, main_dir)
    area = area_id_from_coords(x, y, z)
    return os.path.join(base, area)


def ensure_bucket_dir(
    x: int,
    y: int,
    z: int,
    *,
    world_root: Optional[str] = None,
    main_dir: str = MAIN_DIRECTORY,
) -> str:
    """Create (if necessary) and return the bucket directory for ``(x,y,z)``."""
    path = file_path_for_coords(x, y, z, world_root=world_root, main_dir=main_dir)
    os.makedirs(path, exist_ok=True)
    return path

# Convenience helper – exact bucket centre from arbitrary coordinate

def bucket_center_coords(x: int, y: int, z: int) -> Tuple[int, int, int]:
    """Return lattice‑unit coords at the centre of the bucket containing ``(x,y,z)``."""
    return bucket_center(x, y, z)
