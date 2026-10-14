#!/usr/bin/env python3
"""Failure matrix: one restart frame through every writer/reader pair.

The fixture is the Pt(100) slab with one adatom used in the paper: the bottom
layer held on every axis, the adatom held in z only, persistent ids that are
not the row order, velocities in the natural unit, and coordinates that need
all 17 significant digits. Each route writes the frame with one library and
reads it with another, then grades the four restart fields:

R1 per-axis mask, R2 persistent id, R3 declared velocity unit, R4 binary64
coordinates. "convention" means the field came back only because writer and
reader share a library-specific column name that the format does not define.

Writes data/failure/matrix.csv and data/failure/matrix.json.
"""
from __future__ import annotations

import csv, json, os, sys, tempfile, traceback, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "failure"
NAT_FS = 10.180505671156723  # (amu*A^2/eV)^0.5 in fs, CODATA 2018


def fixture():
    from ase.build import fcc100, add_adsorbate
    s = fcc100("Pt", (2, 2, 2), vacuum=6.0)
    add_adsorbate(s, "Pt", 1.8, "hollow")
    rng = np.random.default_rng(20261014)
    pos = s.get_positions() + rng.uniform(-1, 1, (len(s), 3)) * 1e-3
    mask = np.zeros((len(s), 3), bool)
    mask[:4] = True                     # bottom layer frozen
    mask[8] = [False, False, True]      # adatom: height held only
    ids = np.array([17, 3, 11, 5, 23, 2, 13, 7, 41], dtype=np.uint64)
    vel = rng.normal(scale=4e-3, size=(len(s), 3))  # natural unit
    vel[mask] = 0.0
    return dict(symbols=s.get_chemical_symbols(), pos=pos, cell=s.cell.array.copy(),
                pbc=[True, True, False], mask=mask, ids=ids, vel=vel,
                masses=s.get_masses())


def to_ase(fx, ids_array=True):
    from ase import Atoms
    from ase.constraints import FixAtoms, FixCartesian
    a = Atoms(fx["symbols"], positions=fx["pos"], cell=fx["cell"], pbc=fx["pbc"])
    full = [i for i, m in enumerate(fx["mask"]) if m.all()]
    cons = [FixAtoms(indices=full)] if full else []
    cons += [FixCartesian(i, mask=tuple(m)) for i, m in enumerate(fx["mask"]) if m.any() and not m.all()]
    a.set_constraint(cons)
    a.set_velocities(fx["vel"])  # ASE internal velocity unit is the natural unit
    if ids_array:
        a.set_array("id", fx["ids"].astype(np.int64))
    return a


def ase_snapshot(a, vel_unit_fs):
    from ase.constraints import FixAtoms, FixCartesian
    mask = np.zeros((len(a), 3), bool)
    for c in a.constraints:
        if isinstance(c, FixAtoms):
            mask[c.index] = True
        elif isinstance(c, FixCartesian):
            mask[c.index] |= np.asarray(c.mask, bool)
    ids = a.arrays.get("id")
    v = a.get_velocities() if a.has("momenta") else None
    return dict(pos=a.get_positions(), mask=mask, ids=ids, vel=v, vel_unit_fs=vel_unit_fs, pbc=list(map(bool, a.pbc)))


# ---------------------------------------------------------------- writers
def w_readcon(fx, path):
    import readcon
    atoms = [readcon.Atom(s, *p, fixed=[bool(b) for b in m], atom_id=int(i), mass=float(ms),
                          vx=v[0], vy=v[1], vz=v[2])
             for s, p, m, i, ms, v in zip(fx["symbols"], fx["pos"], fx["mask"], fx["ids"], fx["masses"], fx["vel"])]
    c = fx["cell"]
    L = np.linalg.norm(c, axis=1)
    f = readcon.ConFrame(list(L), [90.0, 90.0, 90.0], atoms,
                         metadata={"pbc": fx["pbc"], "units": {"length": "angstrom", "energy": "eV", "mass": "amu", "time": "(amu*angstrom^2/eV)^0.5"}})
    readcon.write_con(str(path), [f])


def w_readcon_coords(fx, path):
    w_readcon(dict(fx, vel=np.zeros_like(fx["vel"])), path)
    import readcon
    f = readcon.read_con(str(path))
    txt = readcon.write_con_string(f)
    # keep the coordinate block only: the legacy reader stops at a velocity section
    path.write_text(txt.split("\n\nPt\nVelocities")[0] + "\n")


def w_ase(fmt):
    def w(fx, path):
        import ase.io
        ase.io.write(str(path), to_ase(fx), format=fmt)
    return w


def w_mda_h5md(fx, path):
    import MDAnalysis as mda
    from MDAnalysis.coordinates.H5MD import H5MDWriter
    n = len(fx["symbols"])
    u = mda.Universe.empty(n, trajectory=True, velocities=True)
    u.add_TopologyAttr("names", fx["symbols"])
    u.add_TopologyAttr("ids", [int(i) for i in fx["ids"]])
    u.atoms.positions = fx["pos"]
    u.atoms.velocities = fx["vel"] / NAT_FS * 1000.0  # A/ps, MDAnalysis base unit
    u.dimensions = list(np.linalg.norm(fx["cell"], axis=1)) + [90, 90, 90]
    u.trajectory.units = {"time": "ps", "length": "Angstrom", "velocity": "Angstrom/ps"}
    with H5MDWriter(str(path), n, velocities=True, positions=True) as W:
        W.write(u)


def w_chemfiles_xyz(fx, path):
    import chemfiles as cf
    fr = cf.Frame()
    for s, p in zip(fx["symbols"], fx["pos"]):
        fr.add_atom(cf.Atom(s), list(p))
    fr.cell = cf.UnitCell(list(np.linalg.norm(fx["cell"], axis=1)))
    fr.add_velocities()
    v = fr.velocities
    v[:] = fx["vel"]
    with cf.Trajectory(str(path), "w", "XYZ") as t:
        t.write(fr)


# ---------------------------------------------------------------- readers
def r_readcon(path):
    import readcon
    f = readcon.read_con(str(path))[0]
    md = json.loads(readcon.write_con_string([f]).splitlines()[1] or "{}")
    unit = md.get("units", {}).get("time")
    return dict(pbc=md.get("pbc", [True, True, True]), pos=np.asarray(f.coords_array()), mask=np.array([a.fixed for a in f.atoms]),
                ids=np.asarray(f.atom_ids_array()),
                vel=np.asarray(f.velocities_array()) if f.has_velocities else None,
                vel_unit_fs=NAT_FS if unit and "amu" in unit else None,
                version=md.get("con_spec_version"))


def r_ase(fmt, unit_fs=NAT_FS):
    def r(path):
        import ase.io
        return ase_snapshot(ase.io.read(str(path), format=fmt), unit_fs)
    return r


def r_chemfiles(fmt):
    def r(path):
        import chemfiles as cf
        with cf.Trajectory(str(path), "r", fmt) as t:
            fr = t.read()
        v = np.array(fr.velocities) if fr.has_velocities() else None
        ids = None
        try:
            ids = np.array([fr.atoms[i]["id"] for i in range(len(fr.atoms))])
        except BaseException:
            pass
        return dict(pos=np.array(fr.positions), mask=None, ids=ids, vel=v, vel_unit_fs=None)
    return r


def r_mda(fmt):
    def r(path):
        import MDAnalysis as mda
        u = mda.Universe(str(path), format=fmt) if fmt != "H5MD" else mda.Universe(str(path))
        ts = u.trajectory.ts
        v = ts.velocities.copy() if ts.has_velocities else None
        ids = u.atoms.ids.copy() if hasattr(u.atoms, "ids") else None
        pbc = None
        if fmt == "H5MD":
            import h5py
            with h5py.File(str(path)) as h:
                b = h["particles/trajectory/box"].attrs["boundary"]
                pbc = [str(x) == "periodic" for x in b]
        return dict(pos=u.atoms.positions.astype(float), mask=None, ids=ids, vel=v, pbc=pbc,
                    vel_unit_fs=1000.0 if v is not None else None)
    return r


# Fields a route returns only because writer and reader share one library's
# convention, not because the format defines them.
CONVENTION = {
    ("extended XYZ", "ASE", "ASE"): {"R1", "R2", "R3"},   # move_mask, custom id column, ASE time unit
    ("extended XYZ", "ASE", "chemfiles"): {"R2"},
    ("ASE trajectory", "ASE", "ASE"): {"R3"},             # ASE internal unit, not declared in the file
}
# Fields whose unit the format itself fixes (VASP defines POSCAR velocities in A/fs).
FORMAT_FIXED = {("POSCAR", "ASE", "ASE"): {"R3"}}

ROUTES = [
    ("CON 3.1", "readcon-core", "readcon-core", "con", w_readcon, r_readcon),
    ("CON 3.1", "readcon-core", "ASE eon reader", "con", w_readcon, r_ase("eon")),
    ("CON 3.1, coordinates only", "readcon-core", "ASE eon reader", "con", w_readcon_coords, r_ase("eon")),
    ("legacy CON", "ASE eon writer", "readcon-core", "con", w_ase("eon"), r_readcon),
    ("extended XYZ", "ASE", "ASE", "xyz", w_ase("extxyz"), r_ase("extxyz")),
    ("extended XYZ", "ASE", "chemfiles", "xyz", w_ase("extxyz"), r_chemfiles("XYZ")),
    ("extended XYZ", "ASE", "MDAnalysis", "xyz", w_ase("extxyz"), r_mda("XYZ")),
    ("extended XYZ", "chemfiles", "ASE", "xyz", w_chemfiles_xyz, r_ase("extxyz")),
    ("ASE trajectory", "ASE", "ASE", "traj", w_ase("traj"), r_ase("traj")),
    ("POSCAR", "ASE", "ASE", "vasp", w_ase("vasp"), r_ase("vasp")),
    ("H5MD", "MDAnalysis", "MDAnalysis", "h5md", w_mda_h5md, r_mda("H5MD")),
]


def grade(fx, got):
    g = {}
    m = got.get("mask")
    if m is None or not np.any(m):
        g["R1"] = "lost"
    else:
        m = np.asarray(m, bool)
        g["R1"] = "kept" if m.shape == fx["mask"].shape and (m == fx["mask"]).all() else (
            "full freeze" if (m.all(axis=1) == fx["mask"].any(axis=1)).all() else "changed")
    ids = got.get("ids")
    g["R2"] = "kept" if ids is not None and len(ids) == len(fx["ids"]) and (np.asarray(ids, np.int64) == fx["ids"].astype(np.int64)).all() else "lost"
    v = got.get("vel")
    if v is None or not np.any(v):
        g["R3"] = "lost"
    else:
        unit = got.get("vel_unit_fs")
        ke_true = 0.5 * (fx["masses"][:, None] * fx["vel"] ** 2).sum()
        if unit is None:
            # numbers survive but carry no unit: a reader that assumes A/fs
            ratio = (0.5 * (fx["masses"][:, None] * (np.asarray(v) * NAT_FS) ** 2).sum()) / ke_true
            g["R3"] = f"no unit (x{ratio:.2f} if read as A/fs)"
        else:
            vn = np.asarray(v) * NAT_FS / unit  # back to natural unit
            ok = np.allclose(vn, fx["vel"], rtol=1e-6, atol=1e-12)
            g["R3"] = "declared" if ok else "wrong values"
    p = np.asarray(got["pos"], float)
    d = float(np.abs(p - fx["pos"]).max()) if p.shape == fx["pos"].shape else float("nan")
    g["R4"] = "bit-exact" if d == 0.0 else f"{d:.1e} A"
    g["dpos"] = d
    pb = got.get("pbc")
    g["pbc"] = "-" if pb is None else ("kept" if list(map(bool, pb)) == fx["pbc"] else "".join("T" if b else "F" for b in pb))
    return g


def main():
    fx = fixture()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for k, (fmt, wr, rd, ext, w, r) in enumerate(ROUTES):
            path = Path(td) / f"route{k}.{ext}"
            row = dict(format=fmt, writer=wr, reader=rd)
            try:
                w(fx, path)
            except BaseException as e:
                row.update(R1="writer error", R2="writer error", R3="writer error", R4="writer error", pbc="",
                           dpos="", error=f"{type(e).__name__}: {e}"[:160])
                rows.append(row); continue
            try:
                row.update(grade(fx, r(path)))
                for key in CONVENTION.get((fmt, wr, rd), ()):
                    if row[key] in ("kept", "declared"):
                        row[key] = "convention"
                for key in FORMAT_FIXED.get((fmt, wr, rd), ()):
                    if row[key] in ("kept", "declared"):
                        row[key] = "fixed by format"
                row["error"] = ""
            except BaseException as e:
                row.update(R1="reader error", R2="reader error", R3="reader error", R4="reader error", pbc="",
                           dpos="", error=f"{type(e).__name__}: {e}"[:160])
            rows.append(row)
    import ase, chemfiles, MDAnalysis, readcon
    meta = dict(ase=ase.__version__, chemfiles=chemfiles.__version__, MDAnalysis=MDAnalysis.__version__,
                readcon_spec=readcon.CON_SPEC_VERSION)
    with open(OUT / "matrix.csv", "w", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=["format", "writer", "reader", "R1", "R2", "R3", "R4", "pbc", "dpos", "error"])
        wtr.writeheader(); wtr.writerows(rows)
    (OUT / "matrix.json").write_text(json.dumps(dict(meta=meta, rows=rows), indent=1, default=str))
    for r in rows:
        print(f"{r['format']:15s} {r['writer']:15s} -> {r['reader']:15s} | {r['R1']:12s} | {r['R2']:6s} | {r['R3']:30s} | {r['R4']:10s} {r['error']}")


if __name__ == "__main__":
    main()
