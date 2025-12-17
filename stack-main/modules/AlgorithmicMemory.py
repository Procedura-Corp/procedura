# PART OF LITERAL BIOS
"""
" Janusz Jeremiasz Filipiak - AlgorithmicMemory.py
" (c) 2024
" This file describes a few ceiling hooks for everyday tasks :)
"
" It also defines the computational foundation of time. Sounds very fancy.
" In practice it is:
"
" -------------------------------
" | a_min_e28+bitR3_interpreter |
" -------------------------------
"
" a:
"
" 'min'imum space for category
" 'e' for it's exponential algorithmic memory growth capabilities,
" '28+' in at least 28 CHANNELS of,
" 'bit' binary,
" 'R3' three-dimensional Real space
"
" Travel together with this interpreter.
"
" What is an interpreter? In computer science there exists the concept of
" the memory manager. A key component of any advanced computing process,
" the memory manager maintains order over and amongst addressing space(s).
" This interpreter has a head, which means that it maintains state and direction
" with respect to its environment.
"
" The head of the algorithmic memory can add 5 dimensions to any 3 dimensional
" object, and as such create 3D binary space. Inside of this space, time doesn't
" exist and is instead counted for practical purposes such as making sure memory
" can be persisted.
"
"
" This interpreter exists only in cyberspace.
" It is unique and one of its kind.
"
"                _________________________
"               /   /                    /
"              /   /                    /
"             /___/____________________/
"            /___/|                    |
"           /   /||                    |
"          /|  / ||____________________|
"         /_|_/_/
"        |  /| /
"        | / |/
"        |/__|
"
"""
import math
import os
import sys
import copy
import time
import numpy as np
import random
import threading
from collections import defaultdict
from typing import Dict, List, Tuple


# import traceback

max_float = sys.float_info.max ** 0.34
min_float = -max_float

MAX_COMP_DIM = 50000

from utils.logger_instance import logger

verbosity = 0

class TimeRoot:
    """Thread-safe monotonic ID generator."""

    _ctr: int = 0                       # class-level counter
    _lock: threading.Lock = threading.Lock()   # protects _ctr

    def __init__(self, ctr: int | None = None):
        """
        If *ctr* is given, use it verbatim (and make sure the global counter
        never goes backwards).  Otherwise, atomically take the next ID.
        """
        if ctr is None:
            with TimeRoot._lock:
                self.tr = TimeRoot._ctr
                TimeRoot._ctr += 1
        else:
            self.tr = ctr
            # make sure future auto-assigned IDs stay ahead of this one
            with TimeRoot._lock:
                if ctr >= TimeRoot._ctr:
                    TimeRoot._ctr = ctr + 1

    @staticmethod
    def from_saved(saved_ctr: int) -> "TimeRoot":
        """
        Re-instantiate a previously stored TimeRoot *without* consuming a fresh
        ID, but still bump the global counter if needed so we don’t reuse IDs.
        """
        inst = TimeRoot.__new__(TimeRoot)
        inst.tr = saved_ctr
        with TimeRoot._lock:
            if saved_ctr >= TimeRoot._ctr:
                TimeRoot._ctr = saved_ctr + 1
        return inst

    def __str__(self) -> str:
        return f"tr_{self.tr}"

class IntegrityError(Exception):
    """Exception raised for errors in data integrity."""

    def __init__(self, message="Data integrity error occurred"):
        self.message = message
        super().__init__(self.message)

class LBit:
    """

    LBit is a six-dim data structure element. TimeRoot is a measure of linear progress.

    """
    def __init__(self, tr: TimeRoot, data=None, other=None, x=None, y=None, z=None):
        self.tr = tr        # time_root identifier
        self.data = data    # binary string
        self.other = other  # dimension 0
        self.x = x          # dimension 1
        self.y = y          # dimension 2
        self.z = z          # dimension 3

    def __str__(self):
        """
        Return a string representation of the LBit instance, including its
        data, reference to other LBit, and its neighboring LBits in x, y, z directions.
        """
        other_data = self.other.data if self.other else "None"
        x_data = f"x:{self.x.data} " if self.x else "x:None "
        y_data = f"y:{self.y.data} " if self.y else "y:None "
        z_data = f"z:{self.z.data}" if self.z else "z:None"

        return (f"{self.tr}_LBit(data={self.data}, "
                f"other={other_data}, "
                f"{x_data}, "
                f"{y_data}, "
                f"{z_data})")
    # ── JSON helpers ───────────────────────────
    def to_dict(self):
        return {
            "bit": self.bit,
            "coords": (self.x, self.y, self.z),
            # store only an *identifier* of the partner, not the
            # whole object, to avoid infinite recursion
            "other_id": id(self.other) if self.other else None,
        }

    @classmethod
    def from_dict(cls, d, cache):
        x, y, z = d["coords"]
        obj = cls(d["bit"], x, y, z)
        cache[id(obj)] = obj
        return obj

class DBit:
    def __init__(self, lbit0: LBit, lbit1: LBit, x=0, y=0, z=0):
        self.lbit0 = lbit0
        self.lbit1 = lbit1
        self.x = x
        self.y = y
        self.z = z

        # Connect the "other" fields
        self.lbit0.other = self.lbit1
        self.lbit1.other = self.lbit0

    def set_3d(self):
        self.lbit0.dbit = self
        self.lbit1.dbit = self

    def return_box(self):
        signs = [ 'lbit0', 'lbit1' ]
        directions = [ 'x', 'y', 'z' ]

        rv = []

        for sign in signs:
            try:
                lbit = getattr(self, sign)
            except AttributeError as e:
                print(f"missing {sign}")
                return rv
            for direction in directions:
                try:
                    neighbor = getattr(lbit, direction)
                except AttributeError as e:
                    print(f" missing {lbit}.{direction}")
                    continue

    # ── JSON helpers ───────────────────────────
    def to_dict(self):
        return {
            "coords": (self.x, self.y, self.z),
            "lbit0": self.lbit0.to_dict(),
            "lbit1": self.lbit1.to_dict(),
        }

    @classmethod
    def from_dict(cls, d):
        cache = {}
        lb0 = LBit.from_dict(d["lbit0"], cache)
        lb1 = LBit.from_dict(d["lbit1"], cache)
        obj = cls(lb0, lb1, *d["coords"])
        # reconnect partners now that every LBit exists
        lb0.other = cache.get(d["lbit0"]["other_id"])
        lb1.other = cache.get(d["lbit1"]["other_id"])
        return obj

    def __str__(self):
        """
        String representation of the DBit, showing its LBits and their neighbors.
        """
        if min_float == self.x:
            xrep = 'min'
        elif max_float == self.x:
            xrep = 'max'
        else:
            xrep = str(self.x)
        if min_float == self.y:
            yrep = 'min'
        elif max_float == self.y:
            yrep = 'max'
        else:
            yrep = str(self.y)
        if min_float == self.z:
            zrep = 'min'
        elif max_float == self.z:
            zrep = 'max'
        else:
            zrep = str(self.z)
        return (f"\n    DBit ({xrep}, {yrep}, {zrep})\n\n"
                f"        LBit0 -> {self.lbit0}\n\n"
                f"        LBit1 -> {self.lbit1}\n\n")

    def __repr__(self):
        return self.__str__()

"""
            (x,y,z)
               |
               |
     lbit0-----+-----lbit1
     ^   |           |   ^
     |   |           |   |
     |   v           v   |
     |  other     other  |
     |    |         |    |
     |    v         v    |
      \  lbit0-+-lbit1  /
       |   |   |  |    |
       |   v   |  v    |
       \---x   |  x---/
               |
            payload
"""

class LatticeStack:

    def __init__(self, scaffoldbit: DBit):

        self.scaffold = scaffoldbit.lbit0

    def _at_head(self, h: LBit):

        return h.other.other is h

    def _goto_head(self):

        idx = self.scaffold

        while True:

            idx = idx.other

            if self._at_head(idx):
                break

        return idx

    def _attach_head(self, old_head: LBit, payload: object):

        lbit0 = LBit(TimeRoot(), payload)
        lbit1 = LBit(TimeRoot(), "time_root")

        newbit = DBit(lbit0, lbit1, self.scaffold.dbit.x, self.scaffold.dbit.y, self.scaffold.dbit.z)
        newbit.set_3d()

        # lbit1's form a wall in the y,z plane of "time_root" payloads against "data" payloads
        old_tr_wall = old_head.other

        # lbit0.other points into the stack
        old_head.other = newbit.lbit0

        # lbit0.other on the wall side points into the stack
        old_tr_wall.other = newbit.lbit1 # lbit1

        newbit.lbit0.x = old_head
        newbit.lbit1.x = old_tr_wall
        newbit.set_3d()

        return newbit
        
    def push(self, payload: object):

        if self._at_head(self.scaffold):
            newbit = self._attach_head(self.scaffold, payload)
            return newbit

        head = self._goto_head()

        newbit = self._attach_head(head, payload)
        return newbit

    def head(self):

        if self._at_head(self.scaffold):
            return scaffold.dbit

        head = self._goto_head()
        return head.dbit

    # -------------------------------------------------
    # 1)  tiny helper – how you turn ONE DBit into a dict
    # -------------------------------------------------
    @staticmethod
    def _dbit_to_dict(db):
        return {
            "coords": (db.x, db.y, db.z),
            "lbit0": db.lbit0.data,
            "lbit1": db.lbit1.data,
            # add whatever else you need here
        }

    # -------------------------------------------------
    # 2)  iteration protocol  →  list(obj)   or   for d in obj:
    # -------------------------------------------------
    def __iter__(self):
        """
        Walk the vertical stack starting at the scaffold’s lbit0.
        For every step:
            • emit a dict that describes the current DBit
            • advance to the next lbit0 via .other
        Stop when the current LBit is the head ( _at_head(cur) is True ).
        """
        cur = self.scaffold                # lbit0 of the scaffold DBit
        while True:
            yield cur.data

            if self._at_head(cur):         # head reached → done
                break

            cur = cur.other                # next lbit0 in the ring

    def __len__(self):
        return sum(1 for _ in self)       # O(n) but fine for debugging

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return list(self)[idx]
 
        elif isinstance(idx, int):
            if idx < 0:
                raise IndexError
            for i, d in enumerate(self):
                if i == idx:
                    return d
            raise IndexError
        else:
            raise TypeError("Invalid index type")


    # -------------------------------------------------
    # 3)  pretty printing  →  print(stack) or stack at REPL
    # -------------------------------------------------
    def __repr__(self):
        # show *exactly* what list(self) would give
        return repr(list(self))



class AlgorithmicMemory:

    def __init__(self):
        self.i = 0

        self.dbits = {}  # Dictionary to store dbits with keys as tuples of coordinates

        self.dbit_list = []

        self.source = None
        self.target = None

        self.landing = None

        self.head = None

        self.headx = -1
        self.heady = -1
        self.headz = -1

        self.last_rv = None

        self.initialize_head(self.headx, self.heady, self.headz)

        self.move_head_abs(0,0,0)

    def insert_dbit(self, dbit):

        self.dbit_list.append(dbit)

    def initialize_head(self, xstart, ystart, zstart, xdim = 3, ydim = 3, zdim = 3):

        self.head = np.empty((xdim, ydim, zdim), dtype = object)

        def dbit_init(name, x, y, z):
            lbit0 = LBit(TimeRoot(), name)
            lbit1 = LBit(TimeRoot(), "time_root")
            rv = DBit(lbit0, lbit1, x, y, z)
            rv.set_3d()
            return rv

        for i in range(xstart, xstart + xdim):
            for j in range(ystart, ystart + ydim):
                for k in range(zstart, zstart + zdim):
                    name = "3d" + str(i) + "_" + str(j) + "_" + str(k)
                    try:
                        dbit = self.dbits[(i,j,k)]
                    except KeyError as e:
                        dbit = dbit_init(name, i, j, k)
                    if i > xstart:
                        self.head[i-1 - xstart, j - ystart, k - zstart].lbit1.x = dbit.lbit0
                        dbit.lbit0.x = self.head[i-1 - xstart, j - ystart, k - zstart].lbit1
                    if j > ystart:
                        self.head[i - xstart, j-1 - ystart, k - zstart].lbit1.y = dbit.lbit0
                        dbit.lbit0.y = self.head[i - xstart, j-1 - ystart, k - zstart].lbit1
                    if k > zstart:
                        self.head[i - xstart, j - ystart, k-1 - zstart].lbit1.z = dbit.lbit0
                        dbit.lbit0.z = self.head[i - xstart, j - ystart, k-1 - zstart].lbit1

                    self.dbits[(i,j,k)] = dbit

                    self.head[i-xstart,j-ystart,k-zstart] = dbit

        self.headx = xstart
        self.heady = ystart
        self.headz = zstart

        return self.head[int(xdim/3), int(ydim/3), int(zdim/3)]

    # ────────────────────────────────────────────────────────────────────────
    #  Ring repair helpers – scoped to a single (x,y,z) coordinate
    # ────────────────────────────────────────────────────────────────────────
    Coord = Tuple[int, int, int]          # local, anchor-relative

    def _stack_by_coord(self, dbit_list) -> Dict[Coord, List["DBit"]]:
        """Group every DBit in *dbit_list* by its (x,y,z) triple."""
        by = defaultdict(list)
        for db in dbit_list:
            by[(db.x, db.y, db.z)].append(db)
        return by


    def _relink_stack(self, stack: List["DBit"]) -> None:
        """(In-place) rebuild the .other rings for *stack* of DBits.

        *   Chronological order → older payloads are *deeper* (smaller tr.tr).
        *   The “scaffold” DBit (its lbit0.data starts with **"3d"**) is forced
            to be the **entry point** – that’s what lattice_get[_stack] expects.
        """
        if len(stack) < 2:                         # nothing to fix
            return

        # 1) oldest → newest
        stack.sort(key=lambda d: d.lbit0.tr.tr)

        # 2) rotate so the scaffold comes first
        anchor = next(
            (i for i, db in enumerate(stack)
             if isinstance(db.lbit0.data, str) and db.lbit0.data.startswith("3d")),
            0
        )
        if anchor:
            stack[:] = stack[anchor:] + stack[:anchor]

        # 3) relink as a ring (both lbit0 & lbit1)
        n = len(stack)
        for i, db in enumerate(stack):
            nxt = stack[(i + 1) % n]
            db.lbit0.other = nxt.lbit0
            db.lbit1.other = nxt.lbit1


    # ────────────────────────────────────────────────────────────────────────
    #  Public API
    # ────────────────────────────────────────────────────────────────────────
    def relink_coord(self, x: int, y: int, z: int) -> None:
        """
        Rebuild the `.other` ring **only** for DBits that live at *(x,y,z)*.

        Call this right after every `insert()` to keep the vertical stack
        consistent without the heavy `relink_all()`.
        """
        # 1) collect candidates (fast path when there is just the scaffold)
        stack = [db for db in self.dbit_list if (db.x, db.y, db.z) == (x, y, z)]
        if len(stack) < 2:
            return

        sc = self.dbits.get((x, y, z))
        if sc and sc not in stack:
            stack.insert(0, sc)

        # 2) fix the stack in-place
        self._relink_stack(stack)

    def get_neighbor(self, dbit, dx, dy, dz):
        target_x = dbit.x + dx
        target_y = dbit.y + dy
        target_z = dbit.z + dz
        return self.find_dbit(target_x, target_y, target_z)

    def find_dbit(self, x, y, z):
        dbit = self.dbits.get((x, y, z))
        if dbit is not None:
            return dbit.lbit0
        return None

    def debug_clear(self):
        self.dbits = {}

    def print_head(self):
        for i in range(self.head.shape[0]):
            for j in range(self.head.shape[1]):
                for k in range(self.head.shape[2]):
                    print(str(self.head[(i,j,k)]))

    def move_head(self, x,y,z):

        rv = None

        xstart = self.headx
        ystart = self.heady
        zstart = self.headz

        if verbosity != 0:
            print("\n___________________")
            print("HEAD at:\n\\")
            print(f" \\ ( x = {xstart}, y = {ystart}, z = {zstart})\n  -------------------")
            print(f"moving = ({x},{y},{z})")


        xsign = 1
        xsteps = [0]
        ysign = 1
        ysteps = [0]
        zsign = 1
        zsteps = [0]

        rv = self.dbits[xstart+1, ystart+1, zstart+1]

        if x != 0:
            xsign = int(x/abs(x))
            xsteps = range(0, xsign*x+1)
            # print("traveling: ")
            for step_i in xsteps:
                # print(xstart + xsign * step_i, ystart, zstart)
                rv = self.initialize_head(xstart + xsign * step_i, ystart, zstart)

        if y != 0:
            ysign = int(y/abs(y))
            ysteps = range(0, ysign*y+1)
            for step_j in ysteps:
                # print(xstart + xsign * xsteps[-1], ystart + ysign * step_j, zstart)
                rv = self.initialize_head(xstart + xsign * xsteps[-1], ystart + ysign * step_j, zstart)

        if z != 0:
            zsign = int(z/abs(z))
            zsteps = range(0, zsign*z+1)
            for step_k in zsteps:
                # print(xstart + xsign * xsteps[-1], ystart + ysign * ysteps[-1], zstart + zsign * step_k)
                rv = self.initialize_head(xstart + xsign * xsteps[-1], ystart + ysign * ysteps[-1], zstart + zsign * step_k)

        return rv

    def cursor(self):
        return self.dbits[ self.headx + 1, self.heady + 1, self.headz + 1 ]

    def retrieve(self, x, y, z):
        try:
            return self.dbits[ x, y, z ]
        except KeyError as e:
            return None

    def get(self, x, y, z):
        return self.retrieve(x, y, z)

    def move_head_abs(self, x, y, z):

        # The head window is 3×3×3, so its origin must be **one step lower**
        # on every axis than the lattice coordinate we want at [1,1,1].
        desired_origin = (x-1, y-1, z-1)

        # Fast‑path: already centred.
        if (desired_origin[0] == self.headx and
            desired_origin[1] == self.heady and
            desired_origin[2] == self.headz and
            self.last_rv is not None):
            return self.last_rv

        # How far do we have to move the head origin?
        dx = desired_origin[0] - self.headx
        dy = desired_origin[1] - self.heady
        dz = desired_origin[2] - self.headz

        if abs(dx) + abs(dy) + abs(dz) > MAX_COMP_DIM:
            raise IndexError(f"OutOfBounds: {dx} {dy} {dz}")
        self.last_rv = self.move_head(dx, dy, dz)
        return self.last_rv

    def prune(self, x, y, z):

        dbit = self.move_head_abs(x-1,y-1,z-1)
        lbit_idx = dbit.lbit0

        while lbit_idx != lbit_idx.other.other:
            lbit_idx = lbit_idx.other

        self.dbit_list.remove(lbit_idx.dbit)

        lbit_idx.x.other = lbit_idx.other.x
        lbit_idx.other.x.other = lbit_idx.x

        return lbit_idx.dbit


    def insert(self, data, x, y, z):
        if verbosity != 0:
            logger.debug(".")
            logger.debug(".")
            logger.debug("..")
            logger.debug(f".... inserting {data} at ({x}, {y}, {z})")

        dbit = self.move_head_abs(x ,y , z)

        stack = LatticeStack(dbit)

        newbit = stack.push(data)

        self.insert_dbit(newbit)
        
        return newbit

    def get_all_coords(self):
        """
        Returns a list of all coordinate tuples (x, y, z)
        where DBits are stored in the lattice.
        """
        return list(self.dbits.keys())

    def check_integrity(self, dbit = None):
        if verbosity != 0:
            print("                             / integrity \\                             ")
            print("i.________________________.*/ sanity check \\*._______________________.i")

        def make_tests():
            dictionary = [ 'x', 'y', 'z' ]

            tests = []

            for a1 in dictionary:
                for a2 in dictionary:
                    testsequence0 = [ 'lbit0' ]
                    testsequence1 = [ 'lbit1' ]
                    testsequence2 = [ 'lbit0' ]
                    testsequence3 = [ 'lbit1' ]

                    if a1 == a2:
                        continue

                    testsequence0.append(a1)
                    testsequence0.append('other')
                    testsequence0.append(a2)
                    testsequence0.append(a1)
                    testsequence0.append('other')
                    testsequence0.append(a2)
                    testsequence0.append('dbit')

                    testsequence1.append(a1)
                    testsequence1.append('other')
                    testsequence1.append(a2)
                    testsequence1.append(a1)
                    testsequence1.append('other')
                    testsequence1.append(a2)
                    testsequence1.append('dbit')

                    testsequence2.append(a1)
                    testsequence2.append(a2)
                    testsequence2.append('other')
                    testsequence2.append(a1)
                    testsequence2.append(a2)
                    testsequence2.append('dbit')

                    testsequence3.append(a1)
                    testsequence3.append(a2)
                    testsequence3.append('other')
                    testsequence3.append(a1)
                    testsequence3.append(a2)
                    testsequence3.append('dbit')

                    tests.append(testsequence0)
                    tests.append(testsequence1)
                    tests.append(testsequence2)
                    tests.append(testsequence3)

            return tests

        testing_directions = make_tests()

        if dbit is not None:
            bits = { (dbit.x, dbit.y, dbit.z) : dbit }
        else:
            bits = self.dbits.items()

        for coords, obj in bits.items():
            subject = obj
            for test in testing_directions:
                validity = True
                test_path = [ "(" + str(subject.x) + "," + str(subject.y) + "," + str(subject.z) + ")"]
                for step in test:
                    source_obj = obj
                    try:
                        obj = getattr(obj, step)
                    except AttributeError as e:
                        if verbosity > 10:
                            print(f"source: {source_obj} on {step}")
                        raise IntegrityError("[" + step + "] in: ("
                               + str(subject.x) + ","
                               + str(subject.y) + ","
                               + str(subject.z) + ")." +  ".".join(test))
                    if obj == None:
                        obj = subject
                        validity = False
                        break

                    if not isinstance(source_obj, DBit):
                        test_path.append(source_obj.data)
                        test_path.append(step)

                if validity and obj != subject:
                    print (latticeModel())
                    print ("__________________on test: " + " ".join(test))
                    print ("-------------------------------------------------")
                    print ("  ### ##  ##   #   ##")
                    print ("  #   # # # # # #  # #")
                    print ("  ##  ##  ##  # #  ##")
                    print ("  #   # # # # # #  # #")
                    print ("  ### # # # #  #   # #\n")
                    print ("test_subject: ", subject)
                    print ("iterator_at: ", obj)
                    print ("\n# ".join(test_path))
                    if not inspectDBit(subject):
                        raise IntegrityError("[" + step + "] in: ("
                               + str(subject.x) + ","
                               + str(subject.y) + ","
                               + str(subject.z) + ")." +  ".".join(test))

def navigateDBit(input_bit, am: AlgorithmicMemory, command):
    current_bit = input_bit
    result = []
    result.append("-------------------------------------------------------------------")
    result.append("navigating:")
    result.append("CURRENT_BIT " + str(current_bit))

    try:
        if command == 'xp':
            current_bit = current_bit.lbit1.x.dbit
        elif command == 'xm':
            current_bit = current_bit.lbit0.x.dbit
        elif command == 'yp':
            current_bit = current_bit.lbit1.y.dbit
        elif command == 'ym':
            current_bit = current_bit.lbit0.y.dbit
        elif command == 'zp':
            current_bit = current_bit.lbit1.z.dbit
        elif command == 'zm':
            current_bit = current_bit.lbit0.z.dbit
        elif command == 'ot':
            current_bit = current_bit.lbit0.other.dbit
        elif command == 'pr':
            result.append(am.prune(current_bit.x, current_bit.y, current_bit.z))
            current_bit = am.cursor()
        elif command == 'cb':
            if current_bit is None:
                current_bit = am.source
            result.append(latticeModel(current_bit))
        elif command == 'cl':
            current_bit = None
        elif command == 'rb':
            result.append("\n".join(current_bit.return_box()))
        elif command == 'lm':
            result.append(latticeModel())
        else:
            result.append("Invalid command. Please use xp, xm, yp, ym, zp, zm, or exit.")
    except (AttributeError, TypeError) as e:
        raise Exception(f"Navigation command '{command}' failed due to NoneType access or missing attribute: {e}")

    result.append("-------------------------------------------------------------------")
    result.append("TARGET_BIT " + str(current_bit))
    result.append("-------------------------------------------------------------------")
    return current_bit, "\n".join(result)


def inspectDBit(dbit, am :AlgorithmicMemory):
    # if verbosity > 0:
    #    return

    print("Command Prompt Loop")
    print("Available commands: xp (increase x), xm (decrease x), yp (increase y), ym (decrease y), zp (increase z), zm (decrease z), exit (to quit)")

    current_bit = dbit
    print("\nCURRENT_BIT", current_bit)

    while True:
        command = input("Enter a command: ").strip().lower()

        if command == 'xp':
            current_bit = current_bit.lbit1.x.dbit
        elif command == 'xm':
            current_bit = current_bit.lbit0.x.dbit
        elif command == 'yp':
            current_bit = current_bit.lbit1.y.dbit
        elif command == 'ym':
            current_bit = current_bit.lbit0.y.dbit
        elif command == 'zp':
            current_bit = current_bit.lbit1.z.dbit
        elif command == 'zm':
            current_bit = current_bit.lbit0.z.dbit
        elif command == 'ot':
            current_bit = current_bit.lbit0.other.dbit
        elif command == 'pr':
            rv = print(am.prune(current_bit.x, current_bit.y, current_bit.z))
            current_bit = am.cursor()
        elif command == 'cb':
            if current_bit == None:
                current_bit = am.source
            print(latticeModel(current_bit))
        elif command == 'cl':
            current_bit = None
        elif command == 'rb':
            print("\n".join(current_bit.return_box()))
        elif command == 'lm':
            print(latticeModel())
        elif command == 'exit':
            print("Exiting the loop.")
            return True
        else:
            print("Invalid command. Please use xp, xm, yp, ym, zp, zm, or exit.")
        print("-------------------------------------------------------------------")
        print(current_bit)


# am = AlgorithmicMemory()


# Traverse vector (1,1,1)

# am.move_head(-1, 0, 0)
# am.move_head(0, -1, 0)
# am.move_head(0, 0, -1)
# am.move_head_abs(-4,-4,-4)

# am.move_head(2, 2, 2)

# am.insert("one", 1, 1, 1)
# am.insert("neg_one", -1, -1, -1)

# three = am.insert("three", 3, 3, 3)

# am.insert("neg_one_bottom", -1, -1, -1)

# am.source = three

# i = 0
# max_i = 50

def model_xyz_diagonal(am: AlgorithmicMemory):
    while True:

        try:
            am.i += 1
            sign = [ 'lbit0', 'lbit1' ][random.randint(0, 1)]
            axis = [ 'x', 'y', 'z' ][random.randint(1, 3)-1]

            am.landing = getattr(getattr(getattr(am.source, sign), axis), 'dbit')
            am.target = am.landing
            am.source = am.insert(am.target.lbit0.data + '.' + sign + '.' + axis, am.target.x, am.target.y, am.target.z)

        except AttributeError as e:
            if verbosity > 3:
                print(e)
            try:
                am.target = am.insert(am.source.lbit0.data + '.' + sign + '.' + axis, am.source.x, am.source.y, am.source.z)
            except AttributeError as e:
                am.target = am.source


        am.source = am.move_head_abs(am.source.x, am.source.y, am.source.z)

        print(latticeModel(am.source))
        if am.i % 10000 == 0:
            print(am.i)
        # time.sleep(3/16)
        # os.system('clear')
        if am.i > max_i:
            return True

# while True:
#     try:
#         if model_xyz_hypo(am):
#             break
#     except KeyboardInterrupt as e:
#         inspectDBit(am.cursor(), am)

# print("source:")
# print("-------")
# inspectDBit(am.source, am)

# print("target:")
# print("-------")
# inspectDBit(am.target, am)

def latticeModel(dbit = None):

    model = []
    model.append("    #")

    class NoneStr:
        def __init(self, data):
            self.data = data

    nonemsg = NoneStr()

    nonemsg.data = "None"

    if dbit:
        try:
            xmypzp = dbit.lbit1.y.other.z.x.other
            if xmypzp is None:
                xmypzp = nonemsg
        except AttributeError as e:
            xmypzp = nonemsg
        try:
            xt_box = dbit.lbit1.y.other.z
            if xt_box is None:
                xt_box = nonemsg
        except AttributeError as e:
            xt_box = nonemsg
        try:
            xpypzp = dbit.lbit1.x.other.z.other.y
            if xpypzp is None:
                xpypzp = nonemsg
        except AttributeError as e:
            xpypzp = nonemsg
        model.append(f"    #                  {xmypzp.data.center(15, ' ')} ===  {xt_box.data.center(15, ' ')}  === {xpypzp.data.center(15, ' ')}")
        model.append("    #                       //   ||                  / |                //    ||")
        model.append("    #                      //    ||                 /  |               //     ||")
        model.append("    #                     //     ||                /   |              //      ||")

        try:
            ytf_box = dbit.lbit0.x.z
            if ytf_box is None:
                ytf_box = nonemsg
        except AttributeError as e:
            ytf_box = nonemsg
        try:
            yx_box = dbit.lbit1.z
            if yx_box is None:
                yx_box = nonemsg
        except AttributeError as e:
            yx_box = nonemsg
        try:
            yt_box = dbit.lbit1.z.other.x
            if yt_box is None:
                yt_box = nonemsg
        except AttributeError as e:
            yt_box = nonemsg
        model.append(f"    #         {ytf_box.data.center(15, ' ')}  --   {yx_box.data.center(15, ' ')}  --   {yt_box.data.center(15, ' ')}  ||")
        model.append("    #                   //       ||              /|    |            //        ||")

        try:
            zbf_bit = dbit.lbit1.y.x
            if zbf_bit is None:
                zbf_bit = nonemsg
        except AttributeError as e:
            zbf_bit = nonemsg
        try:
            zx_box = dbit.lbit1.y
        except AttributeError as e:
            zx_box = nonemsg
        try:
            zt_box = dbit.lbit1.y.other.x
            if zt_box is None:
                zt_box = nonemsg
        except AttributeError as e:
            zt_box = nonemsg
        model.append(f"    #                  //   {zbf_bit.data.center(15, ' ')}   /{zx_box.data.center(15, ' ')}   //{zt_box.data.center(15, ' ')}")

        try:
            xmymzp = dbit.lbit0.y.z.x
            if xmymzp is None:
                xmymzp = nonemsg
        except AttributeError as e:
            xmymzp = nonemsg
        try:
            xtf_box = dbit.lbit0.y.z
            if xtf_box is None:
                xtf_box = nonemsg
        except AttributeError as e:
            xtf_box = nonemsg
        try:
            xpymzp = dbit.lbit0.y.z.other.x
            if xpymzp is None:
                xpymzp = nonemsg
        except AttributeError as e:
            xpymzp = nonemsg
        model.append("    #                 //         ||            /       |          //          ||")
        model.append(f"    #           {xmymzp.data.center(15, ' ')} ===  {xtf_box.data.center(15, ' ')} === {xpymzp.data.center(15, ' ')}  ||")
        model.append("    #                 ||       |/||           |   |/   |         ||     |/    ||")

        try:
            yz_box = dbit.lbit0.x.other
            if yz_box is None:
                yz_box = nonemsg
        except AttributeError as e:
            yz_box = nonemsg
        center_point = dbit.lbit0
        try:
            zy_box = center_point.other.x
            if zy_box is None:
                zy_box = nonemsg
        except AttributeError as e:
            zy_box = dbit.lbit1.x
        model.append(f"    #                 ||{yz_box.data.center(15, ' ')}   -{center_point.data.center(15, ' ')}-     {zy_box.data.center(15, ' ')}|")
        model.append("    #                 ||      /| ||           |  /|    |         ||    /|     ||")

        try:
            xmypzm = dbit.lbit1.y.z.other.x
            if xmypzm is None:
                xmypzm = nonemsg
        except AttributeError as e:
            xmypzm = nonemsg
        try:
            xbb_bit = dbit.lbit1.y.z
            if xbb_bit is None:
                xbb_bit = nonemsg
        except AttributeError as e:
            xbb_bit = nonemsg
        try:
            xpypzm = dbit.lbit1.x.z.y
            if xpypzm is None:
                xpypzm = nonemsg
        except AttributeError as e:
            xpypzm = nonemsg
        model.append(f"    #                 ||{xmypzm.data.center(15, ' ')} ===  | {xbb_bit.data.center(15, ' ')}|| == {xpypzm.data.center(15, ' ')}")
        model.append("    #                 ||        //            |       /          ||          //")

        try:
            zb_box = dbit.lbit0.y.other.x.other
            if zb_box is None:
                zb_box = nonemsg
        except AttributeError as e:
            zb_box = nonemsg
        try:
            xz_box = dbit.lbit0.y.other
        except AttributeError as e:
            xz_box = nonemsg
        try:
            ztf_box = dbit.lbit0.y.x
            if ztf_box is None:
                ztf_box = nonemsg
        except AttributeError as e:
            ztf_box = nonemsg
        model.append(f"    #           {zb_box.data.center(15, ' ')}         {xz_box.data.center(15, ' ')}     {ztf_box.data.center(15, ' ')}   ")
        model.append("    #                 ||      //              |     /            ||        //")

        try:
            yb_box = dbit.lbit0.z.other.x
            if yb_box is None:
                yb_box = nonemsg
        except AttributeError as e:
            yb_box = nonemsg
        try:
            xy_box = dbit.lbit0.z.other
            if xy_box is None:
                xy_box = nonemsg
        except AttributeError as e:
            xy_box = nonemsg
        try:
            ybr_box = dbit.lbit1.x.z
            if ybr_box is None:
                ybr_box = nonemsg
        except AttributeError as e:
            ybr_box = nonemsg
        model.append(f"    #                 || {yb_box.data.center(15, ' ')}  -  | {xy_box.data.center(15, ' ')} -||-  {ybr_box.data.center(15, ' ')}")
        model.append("    #                 ||    //                |   /              ||      //")
        model.append("    #                 ||   //                 |  /               ||     //")
        model.append("    #                 ||  //                  | /                ||    //")

        try:
            xmymzm = dbit.lbit0.y.other.z.other.x.other
            if xmymzm is None:
                xmymzm = nonemsg
        except AttributeError as e:
            xmymzm = nonemsg
        try:
            xb_box = dbit.lbit0.y.other.z.other
            if xb_box is None:
                xb_box = nonemsg
        except AttributeError as e:
            xb_box = nonemsg
        try:
            xpymzm = dbit.lbit1.x.z.other.y
            if xpymzm is None:
                xpymzm = nonemsg
        except AttributeError as e:
            xpymzm = nonemsg
        model.append(f"    #            {xmymzm.data.center(15, ' ')} === {xb_box.data.center(15, ' ')} === {xpymzm.data.center(15, ' ')}")
    else:
        model.append("    #                  (xm, yp, zp) --- xt_box ---- (xp, yp, zp)")
        model.append("    #                      /   |         / |            /   |")
        model.append("    #                     /    |           |           /    |")
        model.append("    #                ytf_box - | -   -(yx)-  -  -  yt_box   |")
        model.append("    #                   /      |      /|   |         /      |")
        model.append("    #                  /    zbf_bit  /    (zx)      /     zt_box")
        model.append("    #            (xm, ym, zp) ----xtf_box---- (xp, ym, zp) /|")
        model.append("    #                 |        |         /         |        |")
        model.append("    #                 |        |       |           |     /  |")
        model.append("    #                 |   (yz) |       0 -  -    - | -(zy)  |")
        model.append("    #                 |(xm, yp, zm) -/--xbb_bit----|(xp, yp, zm)")
        model.append("    #              zb_box     /   (xz) -   -   - ztf_box   /")
        model.append("    #                 |      /      |   /          |      /")
        model.append("    #                 |  yb_box - -   (xy)   - - - |  ybr_box")
        model.append("    #                 |    /        | /            |    /")
        model.append("    #                 |   /                        |   /")
        model.append("    #            (xm, ym, zm) ----xb_box ---- (xp, ym, zm)")
    model.append("    #")
    return "\n".join(model)



