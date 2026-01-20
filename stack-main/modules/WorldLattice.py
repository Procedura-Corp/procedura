"""

 (c) 2024 Janusz Jeremiasz Filipiak

 WorldLattice is a wrapper for algorithmic memory providing anchor-relative
 coordinate buckets, persistence and basic convenience methods.

 An insert stack at x,y,z is constructed by chaining other references and
 the resulting structure recurses into dbits who have the same x y z but
 are weaved into it depth-first.

 Recursion is present if lbit0.other != lbit1 

 WorldLattice is designed as a first level encapsulation of the x,y,z stack.

"""
from __future__ import annotations

import os
import json
import time
import pickle
import hashlib
import warnings

from typing import Any, Dict, List, Optional, Set

try:
    import matplotlib
    matplotlib.use('WebAgg')
    import matplotlib.pyplot as plt
    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False

from modules import AlgorithmicMemory as am
from utils.storage import resolve_storage, container_dir
from utils.lattice_buckets import (
    file_path_for_coords, ensure_bucket_dir, bucket_center_coords)
#from utils.logger_instance import logger
from utils.parsing import safe_json_loads


# main_directory = 'dbits'

# def file_path_for_coords(x, y, z):
#    return os.path.join(main_directory, f"{x}_{y}_{z}_lattice")

class WorldLattice:
    def __init__(self, x, y, z,
                 world_id: str = "world_id",
                 main_dir: str = "dbits",
                 world_root: str = "world_root",
                 lattice_ver: str = "0.1"
    ):
        """
        x, y, z = 'anchor' coordinates for the lattice.
        self.am = AlgorithmicMemory() is the underlying 3D-lattice manager.
        """

        store = resolve_storage(
            world_root if world_root != "world_root" else None,
            world_id   if world_id   != "world_id"   else None,
            main_dir   if main_dir   != "dbits"      else None,
            default_root="world_root",
            default_world_id="world_id",
            default_main_dir="dbits",
        )
        self.world_id    = store.world_id
        self.base_path   = store.world_root.as_posix()
        self.world_root  = container_dir(store).as_posix()
        self.main_dir    = store.main_dir

        self.lattice_ver = lattice_ver
       
        # compute the true bucket center
        cx, cy, cz = bucket_center_coords(x, y, z)

        self.x = cx
        self.y = cy
        self.z = cz

        self.am = am.AlgorithmicMemory()
        self.filepath = self.base_path

        self._dirty: Set[am.DBit] = set()

    def from_anchor(self, dx, dy, dz):
        return self.x + dx, self.y + dy, self.z + dz

    def insert(self, data, x, y, z):
        """
        Insert 'data' at relative coordinate 
        (self.x - x, self.y - y, self.z - z)
        in the underlying AlgorithmicMemory.
        """
        if not isinstance(data, str):
            try: 
                data["lattice_ver"] = self.lattice_ver
                repr_str = json.dumps(data)
            except TypeError:
                repr_str = repr(data)
        else:
            repr_str = data
        dbit = self.am.insert(repr_str, x - self.x, y - self.y, z - self.z)
        self._dirty.add(dbit)
        return dbit

    def has_dirty(self) -> bool:
        return bool(self._dirty)

    def get(self, x:int, y:int, z:int):
        """
        Move the head to absolute coords (self.x - x, self.y - y, self.z - z)
        and return that DBit.
        """
        return self.am.move_head_abs(x - self.x, y - self.y, z - self.z)

    def persist_dirty(self) -> None:
        if not self._dirty:
            return                              # nothing to do

        bucket_dir = file_path_for_coords(self.x, self.y, self.z,
                                          world_root=self.base_path,
                                          main_dir=self.main_dir)
        chain_dir  = os.path.join(bucket_dir, "chain")
        os.makedirs(chain_dir, exist_ok=True)

        # Retrieve HEAD info (may not exist yet)
        head_path  = os.path.join(bucket_dir, "HEAD")
        if os.path.isfile(head_path):
            with open(head_path) as f:
                prev_fname = f.read().strip()
                prev_seq   = int(prev_fname.split('_')[0])
        else:
            prev_fname, prev_seq = "", 0

        # Build json payload purely from the dirty set
        dbits_info: List[Dict] = [{
            "time_root"  : d.lbit0.tr.tr,
            "x"          : d.x,
            "y"          : d.y,
            "z"          : d.z,
            "lbit0_data" : d.lbit0.data,
        } for d in self._dirty]

        max_tr   = max((rec["time_root"] for rec in dbits_info), default=-1)
        payload  = {
            "prev"       : prev_fname,
            "timestamp"  : int(time.time()),
            "max_trctr"  : max_tr,
            "dbits"      : dbits_info,
        }

        blob      = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
        blob_hash = hashlib.sha256(blob).hexdigest()
        next_seq  = prev_seq + 1
        blk_name  = f"{next_seq:06d}_{blob_hash}.json"

        # Safe write → fsync → rename dance
        tmp_path = os.path.join(chain_dir, blk_name + ".tmp")
        with open(tmp_path, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp_path, os.path.join(chain_dir, blk_name))

        # Atomically advance HEAD
        tmp_head = head_path + ".tmp"
        with open(tmp_head, "w") as fh:
            fh.write(blk_name)
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp_head, head_path)

        # Finally mark those DBits as flushed
        self._dirty.clear()

    def get_data(self, x, y, z, data_type=None):
        """
        Retrieve data at absolute coords (x,y,z).
        If `type` is provided, scan the vertical stack for JSON dicts
        where `data["type"] == type` and return the last match.
        Otherwise, parse and return the single payload at the coordinate.
        """
        # If a type filter is requested, use the full stack
        if data_type is not None:
            # get_dict_stack returns parsed Python objects for the stack
            stack = self.get_dict_stack(x, y, z)
            # print("get_data stack: " + str(stack))
            # filter for dict entries matching the type
            matches = [item for item in stack
                       if isinstance(item, dict) and item.get("data_type") == data_type and item.get("lattice_ver") == self.lattice_ver]
            # print("matches: " + str(matches))
            # return the deepest (last) match if any
            return matches[-1] if matches else None

        # Default behavior: single-entry retrieval
        repr_str = self.get(x, y, z).lbit0.data
        # print("get_data: " + repr_str)
        from utils.parsing import safe_json_loads
        return safe_json_loads(repr_str)

    def get_stack(self, x: int, y: int, z: int):
        """Return **only the `data` payloads** for the vertical stack at (x, y, z).

        Walks the `.other` ring once, appending `dbit.lbit0.data` for each
        LBit encountered.  If the coordinate is empty, returns an empty list.
        """
        cbit = self.am.move_head_abs(x - self.x, y - self.y, z - self.z)
        
        stack = am.LatticeStack(cbit)

        """
        if cbit.lbit0.other is cbit.lbit1:
            return []
        start = cbit.lbit0.other
        if not start:
            return []

        stack: list[str] = []
        current = start
        while True:
            logger.debug("appending: " + str(current))
            stack.append(current.data)
            if current is current.other.other:
                break
            current = current.other
        """
            
        return stack[1:]

    def get_dict_stack(self, x: int, y: int, z: int):
        # Try to parse JSON payloads back into Python objects
        stack = self.get_stack(x, y, z)

        parsed = []
        for item in stack:
            if isinstance(item, str):
                try:
                    obj = json.loads(item)
                    # convert anchor lists to tuples, if present
                    if isinstance(obj, dict) and 'anchor' in obj and isinstance(obj['anchor'], list):
                        obj['anchor'] = tuple(obj['anchor'])
                    parsed.append(obj)
                    continue
                except json.JSONDecodeError:
                    pass
            parsed.append(item)
        return parsed

    """
    Optimized `find_in_z` for `WorldLattice` – adaptive *and* contiguous scan
    -----------------------------------------------------------------------
    Changes since last revision
    ~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. **Contiguous sweep inside each interval** – within every expansion step we
       now iterate *all* offsets in `[dz, dz+step)` so no distances are skipped.
    2. Still symmetric (+Z / –Z) and early‑exit on the first hit.
    3. Step spacing grows geometrically via `growth_factor` (≥ 1).

    """

    from typing import Optional

    def find_in_z(
        self,
        x: int,
        y: int,
        z: int,
        name: str,
        z_span: int = 1000,
        *,
        growth_factor: int | float = 1,
    ) -> Optional[str]:
        """Search vertically for *name* above **and** below (x, y, z).

        Behaviour
        =========
        • Checks origin stack first.
        • Expands outward in *intervals* that grow by `growth_factor` after each
          round (1 → linear, >1 → geometric).
        • **New**: within each interval we probe **every** offset so distances are
          never skipped.
        • Returns on the first match (closest in absolute ∆z).

        Parameters
        ----------
        x, y, z : int
            Absolute anchor coordinates.
        name : str
            Sub‑string to look for in LBit data.
        z_span : int, default 3000
            Maximum search distance in *each* direction.
        growth_factor : int | float, default 1
            ≥1 multiplier controlling interval growth.

        Returns
        -------
        str | None
            Matching data string or *None* if not found.
        """

        # Clamp growth_factor
        growth_factor = max(1, growth_factor)

        # --------------------------------------------------
        # Helper: test a vertical stack for the target string
        # --------------------------------------------------
        def _stack_contains(dbit):
            # print("testing: " + str(dbit))
            if not dbit:
                return None
            lbit_idx = dbit.lbit0
            while True:
                if lbit_idx is None:
                    break
                if name in (lbit_idx.data or ""):
                    return lbit_idx.data
                nxt = lbit_idx.other
                if nxt is None or nxt.other is lbit_idx:
                    break  # completed the ring
                lbit_idx = nxt
            return None

        # 0. Origin check
        origin_hit = _stack_contains(self.get(x, y, z))
        if origin_hit:
            return origin_hit

        # 1. Outward expansion with contiguous sweep
        step = 1  # initial step size
        dz = 1    # current outer boundary (inclusive start of interval)

        while dz <= z_span:
            upper_bound = min(dz + step, z_span + 1)
            # Iterate all offsets [dz, dz+step)
            for i in range(dz, upper_bound):
                # +Z direction
                hit = _stack_contains(self.get(x, y, z + i))
                if hit:
                    return hit
                # –Z direction
                hit = _stack_contains(self.get(x, y, z - i))
                if hit:
                    return hit

            # Prepare next interval
            step = int(max(1, round(step * growth_factor)))
            dz += step

        # 2. No match found within ±z_span
        return None


    def find_in_stack(self, name: str, x, y, z):
        """
        Just an example method that returns a list or string representation
        of the DBits at a certain coordinate. (Simplified here.)
        """
        cbit = self.am.move_head_abs(x - self.x, y - self.y, z - self.z)
        lbit_idx = cbit.lbit0

        # print("lbit_idx = " + str(lbit_idx))
        # print("lbit_idx.other = " + str(lbit_idx.other))
        # print(lbit_idx.other != lbit_idx)

        while True:
            if name in lbit_idx.data:
                return lbit_idx.data
            lbit_top = lbit_idx
            lbit_idx = lbit_idx.other
            if lbit_idx.other == lbit_top:
                break

        return "time_root"


    def find_last_in_stack(self, name: str, x: int, y: int, z: int):
        """
        Return the *deepest* lbit.data that contains 'name' in the vertical stack
        at (x,y,z).  If none, return 'time_root'.
        """
        cbit = self.am.move_head_abs(x - self.x, y - self.y, z - self.z)
        lbit_start = lbit_idx = cbit.lbit0
        match = "time_root"

        while True:
            lbit_idx = lbit_idx.other
            if lbit_idx == lbit_start:
                lbit_idx = lbit_idx.other
                break
            if name in lbit_idx.data:
                match = lbit_idx.data
 
        return match

    def stack_last(self, name: str, x: int, y: int, z: int):
        """
        Return the *deepest* lbit.data that contains 'name' in the vertical stack
        at (x,y,z).  If none, return ('tr_00', 'time_root').
        """
        cbit = self.am.move_head_abs(x - self.x, y - self.y, z - self.z)
        start = cbit.lbit1
        if not start:
            return "tr_00", "time_root"

        current = cbit.lbit0
        last_match = ("tr_00", "time_root")

        # Walk the ring once via .other
        while True:
            if name in (current.data or ""):
                last_match = (current.tr, current.data)
            current = current.other
            if current is start:
                break

        return last_match

    # ------------------------------------------------------------------
    # NEW METHODS: Minimal, Non-Empty DBit Persistence
    # ------------------------------------------------------------------

    def persist_non_empty(self) -> None:
        """Deprecated.  For compatibility with older code paths; forwards to
        **write_lattice()** so callers transparently gain the dirty‑cache
        semantics. Emits a *DeprecationWarning* once per call‑site.
        """
        warnings.warn(
            "persist_non_empty() is deprecated; use write_lattice() which now "
            "flushes via the dirty‑cache.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.write_lattice()

    # ------------------------------------------------------------------
    # Visualization method remains the same
    # ------------------------------------------------------------------
    def visualize_lattice(self):
        """
        Example 3D plotting, unchanged from your code. 
        This uses lbit0.data['lat'], etc.
        """
        if not _HAS_MATPLOTLIB:
            print("Matplotlib not installed. Visualization disabled.")
            return

        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')

        x_coords = []
        y_coords = []
        z_coords = []
        labels = []

        
        for dbit in self.am.dbit_list:
            raw = dbit.lbit0.data

            # 1️⃣ attempt to parse JSON to dict
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    raw = {}              # fall through to skip

            # 2️⃣ plot if lat/lon/alt present
            if isinstance(raw, dict) and {'lat','lon','alt'} <= raw.keys():
                x_coords.append(raw['lat'])
                y_coords.append(raw['lon'])
                z_coords.append(raw['alt'])

        ax.scatter(x_coords, y_coords, z_coords, s=50)

        for i, txt in enumerate(labels):
            ax.text(x_coords[i], y_coords[i], z_coords[i], txt, size=10, zorder=1)

        ax.set_xlabel('Latitude')
        ax.set_ylabel('Longitude')
        ax.set_zlabel('Altitude')
        ax.set_title('3D Lattice Visualization')

        plt.show()

    def to_string(self):
        """
        Returns a readable string representation of all non-empty DBits in the lattice.
        """
        lines = []
        lines.append(f"WorldLattice {self.world_root}.{self.world_id} anchored at ({self.x}, {self.y}, {self.z})")
        lines.append(f"Total DBits: {len(self.am.dbit_list)}")
        lines.append("DBits:")

        for dbit in self.am.dbit_list:
            # Convert internal coords back to external
            ext_x = self.x + dbit.x
            ext_y = self.y + dbit.y
            ext_z = self.z + dbit.z

            # Get lbit0.data for display
            lbit0_data = dbit.lbit0.data
            lines.append(f"  ({ext_x}, {ext_y}, {ext_z}): {repr(lbit0_data)}")

        return "\n".join(lines)


    @staticmethod
    def load_from_chain(
            x: int, y: int, z: int,
            world_id="world_id",
            base_path="world_root",
            main_dir="dbits",
            lattice_ver="0.1"
    ) -> "WorldLattice":
        """
        Reconstruct a lattice bucket from its quantized hash chain.

        • Walks HEAD → prev to gather *all* blocks.
        • Replays them oldest-to-newest, restoring payload + TimeRoot IDs.
        • Relinks vertical rings and neighbour pointers.
        """
        store = resolve_storage(
            base_path if base_path != "world_root" else None,
            world_id  if world_id  != "world_id"   else None,
            main_dir  if main_dir  != "dbits"      else None,
            default_root="world_root",
            default_world_id="world_id",
            default_main_dir="dbits",
        )
        bucket_root = store.world_root.as_posix()
        bucket_dir = file_path_for_coords(x, y, z, world_root=bucket_root, main_dir=store.main_dir)
        # logger.debug("loading from chain in: " + bucket_dir)
        head_file  = os.path.join(bucket_dir, "HEAD")
        chain_dir  = os.path.join(bucket_dir, "chain")

        if not (os.path.isfile(head_file) and os.path.isdir(chain_dir)):
            # Nothing to load
            return WorldLattice(x, y, z)

        # 1. Traverse chain from HEAD back to genesis
        blocks = []
        head = open(head_file).read().strip()
        while head:
            block_path = os.path.join(chain_dir, head)
            with open(block_path, "r") as f:
                blk = json.load(f)
            blocks.append(blk)
            head = blk.get("prev", "")

        # 2. Compute global TimeRoot ceiling
        max_tr = max((blk.get("max_trctr", 0) for blk in blocks), default=0)
        from modules.AlgorithmicMemory import TimeRoot
        TimeRoot.trctr = max_tr + 1         # pre-bump for new inserts

        # 3. Fresh lattice & replay (genesis → HEAD)
        wl = WorldLattice(
            x, y, z,
            world_id=store.world_id,
            # pass the CONTAINER dir (absolute) to preserve the same tree:
            world_root=container_dir(store).as_posix(),
            main_dir=store.main_dir,
            lattice_ver=lattice_ver
        )

        for blk in reversed(blocks):
            for rec in blk.get("dbits", []):
                d = wl.am.insert(rec["lbit0_data"], rec["x"], rec["y"], rec["z"])
                d.lbit0.tr = TimeRoot.from_saved(rec["time_root"])

        # logger.debug("load_from_chain reconstructed lattice:\n" + wl.to_string())
        return wl


    # ──────────────────────────────────────────────────────────────
    #  Modified  read_lattice  (static)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def read_lattice(
        x: int,
        y: int,
        z: int,
        *,
        world_id: str = "world_id",
        world_root: str = "world_root",
        main_dir: str = "dbits",
        lattice_ver: str = "0.1"
    ) -> "WorldLattice":
        """
        Load or create a WorldLattice at (x,y,z) using the following precedence:

            1. Hash-chain (HEAD + chain/…)
            2. Legacy non_empty_dbits.json snapshot
            3. Any *.json* snapshot in the bucket directory
            4. Brand-new empty lattice
        """
        store = resolve_storage(
            world_root if world_root != "world_root" else None,
            world_id   if world_id   != "world_id"   else None,
            main_dir   if main_dir   != "dbits"      else None,
            default_root="world_root",
            default_world_id="world_id",
            default_main_dir="dbits",
        )
        bucket_dir = file_path_for_coords(
            x, y, z,
            world_root=store.world_root.as_posix(),
            main_dir=store.main_dir
        )
        # print("reading from: " + bucket_dir)
        head_file  = os.path.join(bucket_dir, "HEAD")

        if os.path.isfile(head_file):
            # bucket_root = os.path.join(world_root, world_id)
            return WorldLattice.load_from_chain(
                x, y, z,
                world_id=store.world_id,
                # must pass the SAME container dir used to find HEAD:
                base_path=container_dir(store).as_posix(),
                main_dir=store.main_dir,
                lattice_ver=lattice_ver
            )

        return WorldLattice(x, y, z, world_id=world_id, world_root=world_root, main_dir=main_dir, lattice_ver=lattice_ver)

    def write_lattice(self):
        """Persist this lattice (non-empty) to its bucket directory."""
        # ensure we create the bucket under <world_root>/<main_dir>/buckets/…
        ensure_bucket_dir(
            self.x, self.y, self.z,
            world_root=self.base_path,
            main_dir=self.main_dir
        )
        self.persist_dirty()

    @staticmethod
    def deep_copy_bucket(x, y, z, src_id, tgt_id, world_root="world_root", main_dir="dbits"):
        # 1. load source
        src = WorldLattice.read_lattice(x, y, z, world_id=src_id,
                                        world_root=world_root,
                                        main_dir=main_dir)

        # 2. init target
        tgt = WorldLattice(src.x, src.y, src.z,
                           world_id=tgt_id,
                           world_root=world_root,
                           main_dir=main_dir)

        # 3. replay DBits
        from modules.AlgorithmicMemory import TimeRoot
        for db in sorted(src.am.dbit_list, key=lambda d: d.lbit0.tr.tr):
            new_dbit = tgt.am.insert(db.lbit0.data, db.x, db.y, db.z)
            new_dbit.lbit0.tr = TimeRoot.from_saved(db.lbit0.tr.tr)

        # 4. persist under world_id2
        tgt.write_lattice()
