#!/usr/bin/env python3
"""Version and unit safety: header variants given to every reader on the box.

Each variant changes line 2 of one velocity frame. Readers are the
readcon-core Python binding, the readcon-core C interface (ctypes), and the
ASE eon reader (given the coordinate block only, because it stops at a
velocity section). The Julia and Fortran bindings run the same files in a
separate job.

Writes data/failure/version_safety.csv.
"""
from __future__ import annotations
import csv, ctypes, json, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "data" / "failure"
SRC = REPO / "resources" / "test" / "tiny_cuh2.convel"
NAT = "(amu*angstrom^2/eV)^0.5"
U = {"energy": "eV", "length": "angstrom", "mass": "amu"}

VARIANTS = {
    "3.1, natural unit declared": ({"con_spec_version": 3, "con_spec_minor": 1, "sections": ["velocities"], "units": dict(U, time=NAT)}, "accept"),
    "3.1, no time unit": ({"con_spec_version": 3, "con_spec_minor": 1, "sections": ["velocities"], "units": U}, "reject"),
    "3.0, labelled fs": ({"con_spec_version": 3, "sections": ["velocities"], "units": dict(U, time="fs")}, "accept, natural unit"),
    "3.2, unknown key": ({"con_spec_version": 3, "con_spec_minor": 2, "sections": ["velocities"], "units": dict(U, time=NAT), "band_optimizer_state": {"kind": "lbfgs"}}, "accept, keep key"),
    "4.0": ({"con_spec_version": 4, "con_spec_minor": 0, "sections": ["velocities"], "units": dict(U, time=NAT)}, "reject"),
    "missing version": ({"sections": ["velocities"], "units": dict(U, time=NAT)}, "reject"),
    "3.1, mask 9": ({"con_spec_version": 3, "con_spec_minor": 1, "sections": ["velocities"], "units": dict(U, time=NAT)}, "reject"),
}


def make(path, header, mask9=False):
    lines = SRC.read_text().splitlines()
    lines[1] = json.dumps(header)
    if mask9:
        lines[11] = lines[11].replace(" 7    0", " 9    0")
    path.write_text("\n".join(lines) + "\n")


def lib():
    p = Path("/workspace/.cargo-target/release/libreadcon_core.so")
    L = ctypes.CDLL(str(p))
    L.rkr_read_all_frames.restype = ctypes.c_void_p
    L.rkr_read_all_frames.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t)]
    return L


def main():
    import readcon, ase.io
    L = lib()
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for name, (hdr, rule) in VARIANTS.items():
            p = Path(td) / "v.con"
            make(p, hdr, mask9="mask 9" in name)
            row = dict(variant=name, rule=rule)
            try:
                fr = readcon.read_con(str(p))
                out = json.loads(readcon.write_con_string(fr).splitlines()[1])
                row["python"] = "accept"
                row["python_time_unit"] = out.get("units", {}).get("time", "-")
                row["python_kept_unknown_key"] = "yes" if "band_optimizer_state" in out else ("-" if "band_optimizer_state" not in hdr else "no")
            except BaseException as e:
                row["python"] = "reject: " + str(e).split(":")[0][:40]
                row["python_time_unit"] = "-"; row["python_kept_unknown_key"] = "-"
            n = ctypes.c_size_t(0)
            row["c_abi"] = "accept" if L.rkr_read_all_frames(str(p).encode(), ctypes.byref(n)) else "reject"
            q = Path(td) / "coords.con"
            q.write_text(p.read_text().split("\n\nCu\nVelocities")[0] + "\n")
            try:
                a = ase.io.read(str(q), format="eon")
                row["ase_eon"] = "accept"
            except BaseException as e:
                row["ase_eon"] = "reject"
            rows.append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "version_safety.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for r in rows: print(r)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        d = Path(sys.argv[2]); d.mkdir(parents=True, exist_ok=True)
        for i, (name, (hdr, _)) in enumerate(VARIANTS.items()):
            make(d / f"variant{i}.con", hdr, mask9="mask 9" in name)
            print(d / f"variant{i}.con", name)
    else:
        main()
