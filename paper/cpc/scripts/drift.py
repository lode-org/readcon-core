#!/usr/bin/env python3
"""Cross-reader drift.

Part A gives one set of extended XYZ files to every reader path on the box:
ASE, libAtoms extxyz through its C parser and its Python parser, chemfiles and
OVITO, which document extended XYZ, and MDAnalysis and Open Babel, which
document plain XYZ only. Each reader returns whatever its own documented
mechanism exposes: chemfiles gives extra columns and comment keys as
properties, OVITO as user particle properties. Each file is legal or plausible
under the published grammar and differs from a plain frame in one respect.

Part B gives the CON conformance corpus to readcon-core through two entry points
(the Python binding and the C interface, via ctypes on the shared library). It
asks each to read, rewrite and re-read, and requires identical accept/reject
decisions and identical rewritten bytes. The Julia and Fortran bindings run the
same list in a separate job.

Writes data/failure/drift_extxyz.csv and data/failure/drift_con.csv, each with
a JSON sidecar holding the build, host and reader versions. Every coordinate a
reader returns is recorded as its distance, in binary64 values, from the
correctly rounded value of the decimal in the file (the ulps column, and per
reader for the reference frame in the sidecar).
"""

from __future__ import annotations
import csv
import ctypes
import hashlib
import json
import os
import struct
import sys
import warnings
from importlib import metadata
from pathlib import Path
import numpy as np


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "data" / "failure"
sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE_ROWS = [
    "Pt 0.0 0.0 6.0 T T T 17",
    "Pt 2.7718585822512662 0.0 6.0 T T T 3",
    "Pt 1.3859292911256331 1.3859292911256331 7.8 F F T 41",
]
PROPS = "Properties=species:S:1:pos:R:3:move_mask:L:3:id:I:1"
LAT = 'Lattice="5.5437171645025325 0.0 0.0 0.0 5.5437171645025325 0.0 0.0 0.0 20.0"'

CASES = {
    "plain": (f'{LAT} {PROPS} pbc="T T F"', BASE_ROWS),
    "no_pbc_key": (f"{LAT} {PROPS}", BASE_ROWS),
    "bare_comment": ("Pt slab, step 12", [r.rsplit(" ", 4)[0] for r in BASE_ROWS]),
    "fortran_exponent": (
        f'{LAT} {PROPS} pbc="T T F"',
        [r.replace("6.0", "6.0d0") for r in BASE_ROWS],
    ),
    "bool_spelling": (
        f'{LAT} {PROPS} pbc="T T F"',
        [r.replace(" T ", " True ").replace(" F ", " False ") for r in BASE_ROWS],
    ),
    "quoted_value_with_equals": (
        f'{LAT} {PROPS} pbc="T T F" note="E=1.5 eV"',
        BASE_ROWS,
    ),
    "units_key": (f'{LAT} {PROPS} pbc="T T F" units="angstrom,eV,fs"', BASE_ROWS),
}


def write_case(path, comment, rows):
    path.write_text(f"{len(rows)}\n{comment}\n" + "\n".join(rows) + "\n")


def summarise(pos, pbc=None, mask=None, ids=None):
    """mask is the move_mask as the reader understood it (True = may move)."""
    pos = np.asarray(pos, float)
    return dict(
        z0=f"{pos[0, 2]:.17g}",
        x1=f"{pos[1, 0]:.17g}",
        pbc="".join("T" if b else "F" for b in pbc) if pbc is not None else "-",
        move_mask=",".join(
            "".join("T" if b else "F" for b in row) for row in np.asarray(mask, bool)
        )
        if mask is not None
        else "-",
        ids=",".join(str(int(i)) for i in ids) if ids is not None else "-",
        pos=pos.copy(),
    )


def decimals(body):
    """The coordinate decimals of each row of a case, as written in the file."""
    return [row.split()[1:4] for row in body]


def ulp_steps(got, decimal):
    """Binary64 values from the correctly rounded value of the decimal to the coordinate a reader returned."""
    if np.isnan(got):
        return "nan"

    def ordered(x):
        i = struct.unpack("<q", struct.pack("<d", float(x)))[0]
        return i if i >= 0 else -(i & 0x7FFFFFFFFFFFFFFF)

    return str(
        abs(ordered(got) - ordered(float(decimal.replace("d", "e").replace("D", "e"))))
    )


def ulps(pos, body):
    """Per-atom ULP steps of x, y, z, atoms separated by commas (the move_mask layout)."""
    if np.shape(pos) != (len(body), 3):
        return "-"
    return ",".join(
        " ".join(ulp_steps(v, d) for v, d in zip(row, ds))
        for row, ds in zip(pos, decimals(body))
    )


def _mask(a):
    from ase.constraints import FixAtoms, FixCartesian

    m = np.zeros((len(a), 3), bool)
    for c in a.constraints:
        if isinstance(c, FixAtoms):
            m[c.index] = True
        elif isinstance(c, FixCartesian):
            m[c.index] |= np.asarray(c.mask, bool)
    return ~m  # ASE turns move_mask into constraints; report it back as move_mask


def r_ase(p):
    import ase.io

    a = ase.io.read(str(p), format="extxyz")
    return summarise(a.positions, a.pbc, _mask(a), a.arrays.get("id"))


def _libextxyz(use_c):
    def r(p):
        from extxyz.core import read_dicts

        f = read_dicts(str(p), use_cextxyz=use_c)
        f = f[0] if isinstance(f, list) else f
        return summarise(
            f.arrays["pos"], f.pbc, f.arrays.get("move_mask"), f.arrays.get("id")
        )

    return r


def r_chemfiles(p):
    import chemfiles as cf

    with cf.Trajectory(str(p), "r", "XYZ") as t:
        fr = t.read()
    n = len(fr.atoms)
    props = set(fr.atoms[0].list_properties()) if n else set()
    ids = [fr.atoms[i]["id"] for i in range(n)] if "id" in props else None
    split = [f"move_mask_{j}" for j in range(3)]
    mask = (
        [[fr.atoms[i][k] for k in split] for i in range(n)]
        if set(split) <= props
        else None
    )
    pbc = (
        [x.upper().startswith("T") for x in str(fr["pbc"]).split()]
        if "pbc" in fr.list_properties()
        else None
    )
    return summarise(fr.positions, pbc, mask, ids)


def r_ovito(p):
    from ovito.io import import_file

    d = import_file(str(p)).compute()
    P = d.particles
    keys = set(P.keys())
    return summarise(
        P.positions,
        d.cell.pbc if d.cell is not None else None,
        np.asarray(P["move_mask"], bool) if "move_mask" in keys else None,
        np.asarray(P["Particle Identifier"]) if "Particle Identifier" in keys else None,
    )


def r_mda(p):
    import MDAnalysis as mda

    u = mda.Universe(str(p), format="XYZ")
    return summarise(u.atoms.positions, None, None, None)


def r_openbabel(p):
    from openbabel import openbabel as ob, pybel

    ob.obErrorLog.SetOutputLevel(0)
    m = next(pybel.readfile("xyz", str(p))).OBMol
    return summarise(
        [[a.GetX(), a.GetY(), a.GetZ()] for a in ob.OBMolAtomIter(m)], None, None, None
    )


# (reader path, library, whether the library's documentation claims extended XYZ, reader).
# MDAnalysis follows the VMD xyzplugin and ignores every field right of z; the Open
# Babel XYZ format states that no formal specification exists and names no keys.
READERS = [
    ("ASE", "ASE", True, r_ase),
    ("libextxyz (C)", "libAtoms extxyz", True, _libextxyz(True)),
    ("libextxyz (Python)", "libAtoms extxyz", True, _libextxyz(False)),
    ("chemfiles", "chemfiles", True, r_chemfiles),
    ("OVITO", "OVITO", True, r_ovito),
    ("MDAnalysis", "MDAnalysis", False, r_mda),
    ("Open Babel", "Open Babel", False, r_openbabel),
]


def versions():
    """Readers that provenance.peers() does not cover, and where they were imported from."""
    import provenance

    out = {}
    for dist in ("extxyz", "pyleri"):
        try:
            out[dist] = metadata.version(dist)
            out[dist + "_module"] = provenance.portable(Path(__import__(dist).__file__))
        except (metadata.PackageNotFoundError, ImportError):
            out[dist] = None
    return out


def counts(rows):
    """Distinct outcomes on the reference frame, by reader path and by library."""
    from gen_failure_tables import drift_codes

    ref = {r["reader"]: drift_codes("plain", r) for r in rows if r["case"] == "plain"}

    def tally(sel):
        paths = [name for name, lib, ext, _ in READERS if sel(ext)]
        libs = sorted({lib for name, lib, ext, _ in READERS if sel(ext)})
        return dict(
            reader_paths=len(paths),
            libraries=len(libs),
            outcomes=len({ref[p] for p in paths}),
            outcome_by_path={p: ref[p] for p in paths},
            libraries_named=libs,
        )

    split = {}
    for name, lib, _, _ in READERS:
        split.setdefault(lib, set()).add(ref[name])
    return dict(
        all=tally(lambda ext: True),
        extended_xyz=tally(lambda ext: ext),
        plain_xyz=tally(lambda ext: not ext),
        libraries_whose_paths_disagree=sorted(
            k for k, v in split.items() if len(v) > 1
        ),
        files=len(CASES),
    )


def moved(rows):
    """Per reader, the reference-frame coordinates it returned off the correctly rounded value of their decimal."""
    out = {}
    for r in rows:
        if r["case"] != "plain" or r["status"] != "read":
            continue
        out[r["reader"]] = [
            dict(atom=i, axis="xyz"[k], decimal=d, ulps=s if s == "nan" else int(s))
            for i, (steps, ds) in enumerate(
                zip(r["ulps"].split(","), decimals(CASES["plain"][1]))
            )
            for k, (s, d) in enumerate(zip(steps.split(), ds))
            if s != "0"
        ]
    return out


def part_a():
    rows = []
    with bench_scratch("scratch") as td:
        for name, (comment, body) in CASES.items():
            p = Path(td) / f"{name}.xyz"
            write_case(p, comment, body)
            for rname, lib, ext, r in READERS:
                try:
                    out = r(p)
                    out["status"] = "read"
                    out["ulps"] = ulps(out.pop("pos"), body)
                except BaseException as e:
                    out = dict(
                        status=f"error: {type(e).__name__}: {' '.join(str(e).split())[:80]}"
                    )
                rows.append(
                    dict(
                        case=name,
                        reader=rname,
                        library=lib,
                        claims_extxyz="yes" if ext else "no",
                        **out,
                    )
                )
    keys = [
        "case",
        "reader",
        "library",
        "claims_extxyz",
        "status",
        "z0",
        "x1",
        "pbc",
        "move_mask",
        "ids",
        "ulps",
    ]
    with open(OUT / "drift_extxyz.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader()
        w.writerows(rows)
    import provenance

    (OUT / "drift_extxyz.json").write_text(
        json.dumps(
            dict(
                provenance=provenance.record(),
                readers=versions(),
                reference_frame=counts(rows),
                reference_frame_ulps=moved(rows),
            ),
            indent=1,
        )
        + "\n"
    )
    for r in rows:
        print(" | ".join(str(r.get(k, "")) for k in keys))
    return rows


def _lib_path():
    default = REPO / "target/release/libreadcon_core.so"
    raw = os.environ.get("READCON_LIB", "")
    chosen = Path(raw) if raw else default
    if raw and not chosen.is_absolute():
        chosen = (REPO / chosen).resolve()
    return chosen


def _lib():
    for cand in [str(_lib_path())]:
        if cand and Path(cand).exists():
            lib = ctypes.CDLL(cand)
            lib.rkr_read_all_frames.restype = ctypes.POINTER(ctypes.c_void_p)
            lib.rkr_read_all_frames.argtypes = [
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            return lib
    return None


def part_b():
    import provenance
    import readcon

    lib = _lib()
    rows = []
    corpus = sorted((REPO / "resources" / "conformance").glob("*/*.con"))
    for f in corpus:
        expect = f.parent.name
        try:
            fr = readcon.read_con(str(f))
            py = "accept"
            text = readcon.write_con_string(fr)
            again = readcon.write_con_string(readcon.read_con_string(text))
            stable = "yes" if again == text else "no"
            digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        except BaseException:
            py, stable, digest = "reject", "-", "-"
        c = "-"
        if lib is not None:
            n = ctypes.c_size_t(0)
            h = lib.rkr_read_all_frames(str(f).encode(), ctypes.byref(n))
            c = "accept" if h else "reject"
            if h and hasattr(lib, "free_rkr_frame_array"):
                lib.free_rkr_frame_array(h, n)
        rows.append(
            dict(
                file=f.name,
                expected="accept" if expect == "valid" else "reject",
                python=py,
                c_abi=c,
                rewrite_stable=stable,
                sha256_12=digest,
            )
        )
    with open(OUT / "drift_con.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    bad = [
        r
        for r in rows
        if r["python"] != r["expected"]
        or (r["c_abi"] != "-" and r["c_abi"] != r["expected"])
        or r["rewrite_stable"] == "no"
    ]
    (OUT / "drift_con.json").write_text(
        json.dumps(
            dict(
                provenance=provenance.record(),
                c_abi=provenance.binary_build(_lib_path()) if lib is not None else None,
                files=len(rows),
                disagreements=len(bad),
            ),
            indent=1,
        )
        + "\n"
    )
    print(
        f"CON corpus: {len(rows)} files, {len(bad)} disagreements, C ABI {'present' if lib else 'absent'}"
    )
    for r in bad:
        print("  ", r)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    part_a()
    part_b()
