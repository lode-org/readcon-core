#!/usr/bin/env python3
"""Bytes per atom of one checkpoint frame and of the 10,000-frame file.

CON 3.1 (readcon-core), extended XYZ (ASE), H5MD written by MDAnalysis and
H5MD written with h5py (binary64 positions plus mask and id datasets) carry
the same 218-atom frame. Each file is also gzipped at level 6.
"""
import gzip, os, sys, tempfile
from pathlib import Path
import numpy as np, h5py, readcon, ase.io
import MDAnalysis as mda
from MDAnalysis.coordinates.memory import MemoryReader

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "bench" / "work" / "frames-10000.con"
OUT = ROOT / "data" / "sizes.csv"


def gz(p):
    return len(gzip.compress(Path(p).read_bytes(), 6))


def h5py_write(path, pos, cell, mask, ids):
    with h5py.File(path, "w") as f:
        g = f.create_group("particles/all")
        b = g.create_group("box"); b.attrs["dimension"] = 3
        b.attrs["boundary"] = np.array([b"periodic"] * 3)
        b.create_dataset("edges", data=np.diag(cell))
        p = g.create_group("position")
        p.create_dataset("value", data=pos, dtype="f8")
        p.create_dataset("step", data=np.arange(len(pos)))
        p["value"].attrs["unit"] = "angstrom"
        g.create_dataset("id", data=ids, dtype="i8")
        g.create_dataset("fixed", data=mask, dtype="u1")


def mda_write(path, pos, cell, symbols):
    u = mda.Universe.empty(pos.shape[1], trajectory=False)
    u.add_TopologyAttr("names", symbols)
    u.load_new(pos.astype(np.float32), format=MemoryReader,
               dimensions=np.r_[np.diag(cell), 90, 90, 90])
    with mda.Writer(str(path), n_atoms=pos.shape[1], lengthunit="Angstrom", timeunit="ps") as w:
        for _ in u.trajectory:
            w.write(u)


def main():
    frames = readcon.read_con(str(SRC))
    n_frames = len(frames)
    atoms = frames[0].to_ase()
    n = len(atoms)
    cell = atoms.cell.array
    mask = np.array([[a.fixed[0], a.fixed[1], a.fixed[2]] for a in frames[0].atoms], dtype=np.uint8)
    ids = np.array([a.atom_id for a in frames[0].atoms])
    rows = []
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for label, nf in (("one frame", 1), (f"{n_frames} frames", n_frames)):
            files = {}
            con = d / f"f{nf}.con"
            readcon.write_con(str(con), frames[:nf]); files["CON 3.1"] = con
            xyz = d / f"f{nf}.extxyz"
            ase.io.write(xyz, [atoms] * nf, format="extxyz"); files["extended XYZ (ASE)"] = xyz
            pos = np.repeat(atoms.positions[None], nf, axis=0)
            h1 = d / f"f{nf}_mda.h5md"; mda_write(h1, pos, cell, atoms.get_chemical_symbols())
            files["H5MD (MDAnalysis)"] = h1
            h2 = d / f"f{nf}_h5py.h5md"; h5py_write(h2, pos, cell, mask, ids)
            files["H5MD (h5py)"] = h2
            for fmt, p in files.items():
                raw = os.path.getsize(p); z = gz(p)
                rows.append((label, fmt, raw, z, raw / (n * nf), z / (n * nf)))
    with open(OUT, "w") as f:
        f.write("payload,format,bytes,gzip_bytes,bytes_per_atom,gzip_bytes_per_atom\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]:.2f},{r[5]:.2f}\n")
    print(open(OUT).read())




def table():
    import csv
    rows = list(csv.DictReader(open(OUT)))
    body = []
    fmts = list(dict.fromkeys(r["format"] for r in rows))
    pay = list(dict.fromkeys(r["payload"] for r in rows))
    for f in fmts:
        cells = []
        for p in pay:
            r = next(x for x in rows if x["format"] == f and x["payload"] == p)
            cells += [r["bytes_per_atom"], r["gzip_bytes_per_atom"]]
        body.append(f + " & " + " & ".join(cells) + r" \\")
    t = r"""\begin{table}[ht]
\centering
\small
\caption{Bytes per atom of the 218-atom frame, alone and repeated 10{,}000 times, raw and after gzip at level 6.
CON 3.1 is the default readcon-core writer, extended XYZ the ASE writer with the mask column, H5MD (MDAnalysis) its writer in single precision, and H5MD (h5py) binary64 positions with mask and id datasets.
The repeated file compresses better than any real trajectory would.}
\label{tab:sizes}
\begin{tabular}{lrrrr}
\toprule
& \multicolumn{2}{c}{One frame} & \multicolumn{2}{c}{10{,}000 frames} \\
Format & raw & gzip & raw & gzip \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    (ROOT / "src" / "figures" / "generated" / "sizes_table.tex").write_text(t)


if __name__ == "__main__":
    if "--table" not in sys.argv:
        main()
    table()
