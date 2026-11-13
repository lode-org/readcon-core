"""One touch checksum for the public-main ladder and the tip ladder.

Both scripts import ``shared_digest``. That function calls
``fold_shared_symbols`` in ``digest_fold``.
"""

from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path

FUNCTION = "fold_shared_symbols"


def harness_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_fold(lib_path: Path):
    lib = ctypes.CDLL(str(lib_path))
    lib.fold_shared_symbols.restype = ctypes.c_uint64
    lib.fold_shared_symbols.argtypes = [
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_uint64,
    ]
    return lib


def f64_bits(value: float) -> int:
    import struct

    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def shared_digest(frames, fold) -> int:
    first = frames[0]
    last = frames[-1]
    symbols = [atom.symbol.encode("utf-8") for atom in first.atoms]
    last_symbols = [atom.symbol.encode("utf-8") for atom in last.atoms]
    if symbols != last_symbols:
        raise SystemExit("symbol sequence differs across frames")
    cell = [f64_bits(value) for value in first.cell]
    if [f64_bits(value) for value in last.cell] != cell:
        raise SystemExit("cell lengths differ across frames")
    n_frames = len(frames)
    held = []
    ptrs = (ctypes.c_void_p * n_frames)()
    for index, frame in enumerate(frames):
        xyz = frame.xyz.reshape(-1)
        held.append(xyz)
        ptrs[index] = xyz.ctypes.data
    n_coords = held[0].shape[0]
    sym_keep = [ctypes.create_string_buffer(item) for item in symbols]
    sym_lens = (ctypes.c_uint64 * len(sym_keep))(*[len(item) - 1 for item in sym_keep])
    sym_ptrs = (ctypes.c_void_p * len(sym_keep))()
    for index, item in enumerate(sym_keep):
        sym_ptrs[index] = ctypes.cast(item, ctypes.c_void_p)
    return int(
        fold.fold_shared_symbols(
            n_frames,
            n_coords,
            ptrs,
            len(sym_keep),
            sym_lens,
            sym_ptrs,
            cell[0],
            cell[1],
            cell[2],
        )
    )
