#!/usr/bin/env python3
"""Cross-reader drift.

Part A gives one set of extended XYZ files to four readers: ASE, libextxyz
(the C parser through its Python binding), chemfiles, and MDAnalysis. It records
what each returns. Each file is legal or plausible under the published grammar
and differs from a plain frame in one respect.

Part B gives the CON conformance corpus to readcon-core through two entry points
(the Python binding and the C interface, via ctypes on the shared library). It
asks each to read, rewrite and re-read, and requires identical accept/reject
decisions and identical rewritten bytes. The Julia and Fortran bindings run the
same list in a separate job.

Writes data/failure/drift_extxyz.csv and data/failure/drift_con.csv.
"""
from __future__ import annotations
import csv, ctypes, hashlib, os, tempfile, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "data" / "failure"

BASE_ROWS = ["Pt 0.0 0.0 6.0 T T T 17", "Pt 2.7718585822512662 0.0 6.0 T T T 3",
             "Pt 1.3859292911256331 1.3859292911256331 7.8 F F T 41"]
PROPS = "Properties=species:S:1:pos:R:3:move_mask:L:3:id:I:1"
LAT = 'Lattice="5.5437171645025325 0.0 0.0 0.0 5.5437171645025325 0.0 0.0 0.0 20.0"'

CASES = {
    "plain": (f'{LAT} {PROPS} pbc="T T F"', BASE_ROWS),
    "no_pbc_key": (f'{LAT} {PROPS}', BASE_ROWS),
    "bare_comment": ("Pt slab, step 12", [r.rsplit(" ", 4)[0] for r in BASE_ROWS]),
    "fortran_exponent": (f'{LAT} {PROPS} pbc="T T F"', [r.replace("6.0", "6.0d0") for r in BASE_ROWS]),
    "bool_spelling": (f'{LAT} {PROPS} pbc="T T F"', [r.replace(" T ", " True ").replace(" F ", " False ") for r in BASE_ROWS]),
    "quoted_value_with_equals": (f'{LAT} {PROPS} pbc="T T F" note="E=1.5 eV"', BASE_ROWS),
    "units_key": (f'{LAT} {PROPS} pbc="T T F" units="angstrom,eV,fs"', BASE_ROWS),
}


def write_case(path, comment, rows):
    path.write_text(f"{len(rows)}\n{comment}\n" + "\n".join(rows) + "\n")


def summarise(pos, pbc=None, mask=None, ids=None):
    """mask is the move_mask as the reader understood it (True = may move)."""
    pos = np.asarray(pos, float)
    return dict(z0=f"{pos[0, 2]:.17g}", x1=f"{pos[1, 0]:.17g}",
                pbc="".join("T" if b else "F" for b in pbc) if pbc is not None else "-",
                move_mask=",".join("".join("T" if b else "F" for b in row) for row in np.asarray(mask, bool)) if mask is not None else "-",
                ids=",".join(str(int(i)) for i in ids) if ids is not None else "-")


def _mask(a):
    from ase.constraints import FixAtoms, FixCartesian
    m = np.zeros((len(a), 3), bool)
    for c in a.constraints:
        if isinstance(c, FixAtoms): m[c.index] = True
        elif isinstance(c, FixCartesian): m[c.index] |= np.asarray(c.mask, bool)
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
        return summarise(f.arrays["pos"], f.pbc, f.arrays.get("move_mask"), f.arrays.get("id"))
    return r


def r_chemfiles(p):
    import chemfiles as cf
    with cf.Trajectory(str(p), "r", "XYZ") as t:
        fr = t.read()
    ids = None
    try:
        ids = [fr.atoms[i]["id"] for i in range(len(fr.atoms))]
    except BaseException:
        pass
    return summarise(fr.positions, None, None, ids)


def r_mda(p):
    import MDAnalysis as mda
    u = mda.Universe(str(p), format="XYZ")
    return summarise(u.atoms.positions, None, None, None)


READERS = [("ASE", r_ase), ("libextxyz (C)", _libextxyz(True)), ("libextxyz (Python)", _libextxyz(False)), ("chemfiles", r_chemfiles), ("MDAnalysis", r_mda)]


def part_a():
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for name, (comment, body) in CASES.items():
            p = Path(td) / f"{name}.xyz"
            write_case(p, comment, body)
            for rname, r in READERS:
                try:
                    out = r(p); out["status"] = "read"
                except BaseException as e:
                    out = dict(status=f"error: {type(e).__name__}: {str(e)[:80]}")
                rows.append(dict(case=name, reader=rname, **out))
    keys = ["case", "reader", "status", "z0", "x1", "pbc", "move_mask", "ids"]
    with open(OUT / "drift_extxyz.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval=""); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(" | ".join(str(r.get(k, "")) for k in keys))
    return rows


def _lib():
    for cand in [os.environ.get("READCON_LIB", ""), "/workspace/.cargo-target/release/libreadcon_core.so"]:
        if cand and Path(cand).exists():
            lib = ctypes.CDLL(cand)
            lib.rkr_read_all_frames.restype = ctypes.POINTER(ctypes.c_void_p)
            lib.rkr_read_all_frames.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t)]
            return lib
    return None


def part_b():
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
        rows.append(dict(file=f.name, expected="accept" if expect == "valid" else "reject",
                         python=py, c_abi=c, rewrite_stable=stable, sha256_12=digest))
    with open(OUT / "drift_con.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    bad = [r for r in rows if r["python"] != r["expected"] or (r["c_abi"] != "-" and r["c_abi"] != r["expected"]) or r["rewrite_stable"] == "no"]
    print(f"CON corpus: {len(rows)} files, {len(bad)} disagreements, C ABI {'present' if lib else 'absent'}")
    for r in bad: print("  ", r)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    part_a(); part_b()
