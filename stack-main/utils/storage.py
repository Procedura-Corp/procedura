# utils/storage.py
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Storage:
    base: Path          # unified base (e.g., /var/procedura) or fallback
    root_name: str      # module- or caller-provided root token (e.g., "runtime")
    world_id: str       # e.g., "world", "<agent-hash>", "<agent-name>"
    main_dir: str       # usually "dbits"

    @property
    def world_root(self) -> Path:
        """
        Final <base>/<root_name>/<world_id> directory, with the special case:
        if root_name is empty (absolute override), world_root = <base>/<world_id>.
        """
        root = self.base if not self.root_name else (self.base / self.root_name)
        return root / self.world_id


def _is_abs(p: str | None) -> bool:
    """Return True if *p* is absolute after expanding '~'."""
    try:
        return bool(p) and Path(p).expanduser().is_absolute()
    except Exception:
        return False


def resolve_storage(
    world_root: str | None,
    world_id: str | None,
    main_dir: str | None,
    *,
    default_root_name: str | None = None,   # allow None so we can accept legacy alias
    default_world_id: str,
    default_main_dir: str = "dbits",
    **_compat,  # accept legacy kw: default_root
) -> Storage:
    """Routing rules (no public API changes):
      1) If world_root is ABSOLUTE → use it as the *root dir* (no base).
      2) Else:
         base = $PROCEDURA_DATA_ROOT (if set) OR cwd-resolved default (keeps legacy behavior).
         root_name = world_root if given else default_root_name (treated as a subfolder under base).
      3) world_id = arg or default_world_id.
      4) main_dir = arg or default_main_dir.

      Final bucket root:
        ABSOLUTE:                <world_root>/<world_id>/<main_dir>/
        RELATIVE + unified base: <PROCEDURA_DATA_ROOT>/<root_name>/<world_id>/<main_dir>/
        RELATIVE w/o env:        <cwd>/<root_name>/<world_id>/<main_dir>/
    """
    # Legacy kw alias: default_root → default_root_name
    if default_root_name is None:
        default_root_name = _compat.pop("default_root", None)
    if default_root_name is None:
        raise TypeError("resolve_storage: missing 'default_root_name' (or legacy 'default_root').")

    # 1) Decide absolute vs relative semantics for world_root
    if _is_abs(world_root):
        base = Path(world_root).expanduser().resolve()
        root_name = ""  # no extra layer
    else:
        # Unified base (env), or fallback to cwd for legacy relative roots
        env_base = os.getenv("PROCEDURA_DATA_ROOT")
        base = Path(env_base).expanduser().resolve() if env_base else Path.cwd().resolve()
        root_name = (world_root or default_root_name)

    wid  = (world_id  or default_world_id)
    mdir = (main_dir  or default_main_dir)

    # Ensure the bucket root exists; WorldLattice will create deeper dirs on write
    target = (base if not root_name else base / root_name) / wid / mdir
    target.mkdir(parents=True, exist_ok=True)

    return Storage(base=base, root_name=root_name, world_id=wid, main_dir=mdir)


# ───────────────────────── convenience helpers ─────────────────────────
def container_dir(store: Storage) -> Path:
    """
    Directory that CONTAINS the <world_id> folder:
      <base>/<root_name>  (or just <base> when 'root_name' is empty)
    """
    return store.base if not store.root_name else (store.base / store.root_name)


def resolve_planes_root(root_dir: str) -> Path:
    """
    Resolve a planes root under the unified base:
      absolute(root_dir) → root_dir
      relative(root_dir) → $PROCEDURA_DATA_ROOT/<root_dir> (or ./<root_dir> if env unset)
    Ensures the directory exists and returns the absolute path.
    """
    p = Path(root_dir)
    if p.is_absolute():
        out = p
    else:
        base = Path(os.getenv("PROCEDURA_DATA_ROOT", ".")).expanduser().resolve()
        out = (base / p).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out
