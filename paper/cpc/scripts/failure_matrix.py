#!/usr/bin/env python3
"""Failure matrix: one restart frame through every writer/reader pair.

The fixture is the Pt(100) slab with one adatom used in the paper: the bottom
layer held on every axis, the adatom held in z only, persistent ids that are
not the row order, velocities in the natural unit, and coordinates that need
all 17 significant digits. Each route writes the frame with one library and
reads it with the same library or another; ``pairing`` says which, from the
libraries one map (LIBRARY) gives the writer and the reader. Each library
stores and returns every field through the mechanism its own documentation
gives for it. The grades are:

R1 per-axis mask, R2 persistent id, R3 a time unit written in the file, R4
binary64 coordinates, R5 the version the written file carries. ``dcell`` is the
largest change of a cell length, on the routes whose reader returns a cell.
R3 is declared only when the reader takes the velocity unit from a label in the
file and the values agree after converting with it; velocities that come back
from a file that names no time unit are "no unit", whatever unit the reader
assumes.

One rule separates the format from a convention. A returned field is fixed by
the format when the format's own specification defines the name and meaning of
the place it was stored in (SPEC). Otherwise it is a convention: only a
library's documented layout defines that place, so only a reader that shares
the layout gets the field back.

A format is named H5MD only if the written file has the H5MD root group with
its version, and its name says private when the file adds a particle element
H5MD does not define (h5md_layout); any other outcome exits before an output is
written.

Writes data/failure/matrix.csv and data/failure/matrix.json.
"""
from __future__ import annotations

import csv
import json
import struct
import sys
import tempfile
import traceback
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "failure"
sys.path.insert(0, str(Path(__file__).resolve().parent))
# (amu*angstrom^2/eV)^0.5 in fs, the value unit_conversion_factor returns
# for the CODATA 2018 constants (src/units.rs).
NAT_FS = 10.180505710759414


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


def to_ase(fx, ids_array=True, tags=False, scaled=False):
    from ase import Atoms
    from ase.constraints import FixAtoms, FixCartesian, FixScaled
    a = Atoms(fx["symbols"], positions=fx["pos"], cell=fx["cell"], pbc=fx["pbc"])
    full = [i for i, m in enumerate(fx["mask"]) if m.all()]
    cons = [FixAtoms(indices=full)] if full else []
    part = [(i, m) for i, m in enumerate(fx["mask"]) if m.any() and not m.all()]
    if scaled:
        # The cell is orthogonal and axis-aligned, so a scaled axis is a Cartesian axis.
        cons += [FixScaled(i, mask=tuple(map(bool, m)), cell=a.cell) for i, m in part]
    else:
        cons += [FixCartesian(i, mask=tuple(m)) for i, m in part]
    a.set_constraint(cons)
    a.set_velocities(fx["vel"])  # ASE internal velocity unit is the natural unit
    if ids_array:
        a.set_array("id", fx["ids"].astype(np.int64))
    if tags:
        a.set_tags(fx["ids"].astype(np.int64))
    return a


def time_unit_fs(label):
    """Femtoseconds in the time factor of a velocity unit label such as 'angstrom fs-1' (None if it has none)."""
    if label is None:
        return None
    label = label.decode() if isinstance(label, bytes) else str(label)
    factors = [f[:-2] for f in label.split() if f.endswith("-1")]
    return H5MD_TIME.get(factors[0]) if len(factors) == 1 else None


def ase_snapshot(a, ids_from="id"):
    """The fields of an ASE read. ASE's readers of these formats take no velocity unit from the file."""
    from ase.constraints import FixAtoms, FixCartesian, FixScaled
    mask = np.zeros((len(a), 3), bool)
    for c in a.constraints:
        if isinstance(c, FixAtoms):
            mask[c.index] = True
        elif isinstance(c, (FixCartesian, FixScaled)):
            mask[c.index] |= np.asarray(c.mask, bool)
    split = [f"move_mask_{j}" for j in range(3)]
    if not a.constraints and all(k in a.arrays for k in split):
        mask = ~np.stack([np.asarray(a.arrays[k], bool) for k in split], axis=1)
    ids = a.get_tags() if ids_from == "tags" else a.arrays.get("id")
    v = None
    if a.has("momenta"):
        v = a.get_velocities()
    elif "velo" in a.arrays:
        v = np.asarray(a.arrays["velo"], float)
    return dict(pos=a.get_positions(), mask=mask, ids=ids, vel=v, unit_label=None, vel_unit_fs=None,
                pbc=list(map(bool, a.pbc)), cell=a.cell.lengths())


# ---------------------------------------------------------------- writers
def w_readcon(fx, path):
    import readcon
    atoms = [readcon.Atom(s, *p, fixed=[bool(b) for b in m], atom_id=int(i), mass=float(ms),
                          vx=v[0], vy=v[1], vz=v[2])
             for s, p, m, i, ms, v in zip(fx["symbols"], fx["pos"], fx["mask"], fx["ids"], fx["masses"], fx["vel"])]
    c = fx["cell"]
    L = np.linalg.norm(c, axis=1)
    # The rows are CON 3.1; a frame given no minor gets the library's own (2 from readcon-core 0.17.4).
    f = readcon.ConFrame(list(L), [90.0, 90.0, 90.0], atoms,
                         metadata={"con_spec_version": 3, "con_spec_minor": 1, "pbc": fx["pbc"],
                                   "units": {"length": "angstrom", "energy": "eV", "mass": "amu", "time": "(amu*angstrom^2/eV)^0.5"}})
    readcon.write_con(str(path), [f])


def w_ase(fmt, **kw):
    def w(fx, path):
        import ase.io
        ase.io.write(str(path), to_ase(fx, **kw), format=fmt)
    w.atoms = lambda fx: to_ase(fx, **kw)
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


def w_h5py_h5md(fx, path):
    """H5MD 1.1 standard elements; the mask has no standard element, so it is a custom dataset."""
    import h5py
    from ase.data import atomic_numbers
    with h5py.File(str(path), "w") as h:
        meta = h.create_group("h5md")
        meta.attrs["version"] = np.array([1, 1], np.int32)
        meta.create_group("author").attrs["name"] = "failure_matrix.py"
        creator = meta.create_group("creator")
        creator.attrs["name"] = "h5py"
        creator.attrs["version"] = h5py.__version__
        meta.create_group("modules/units").attrs["version"] = np.array([1, 0], np.int32)
        part = h.create_group("particles/slab")
        box = part.create_group("box")
        box.attrs["dimension"] = np.int32(3)
        box.attrs["boundary"] = np.array([b"periodic" if b else b"none" for b in fx["pbc"]], dtype="S8")
        box.create_dataset("edges", data=np.linalg.norm(fx["cell"], axis=1)).attrs["unit"] = "angstrom"
        for name, data, unit in (("position", fx["pos"], "angstrom"),
                                 ("velocity", fx["vel"] / NAT_FS, "angstrom fs-1")):
            el = part.create_group(name)
            el.create_dataset("step", data=np.array([0], np.int64))
            el.create_dataset("time", data=np.array([0.0])).attrs["unit"] = "fs"
            el.create_dataset("value", data=data[None].astype(np.float64)).attrs["unit"] = unit
        part.create_dataset("id", data=fx["ids"].astype(np.int64))
        part.create_dataset("species", data=np.array([atomic_numbers[s] for s in fx["symbols"]], np.int32))
        part.create_dataset("mass", data=fx["masses"]).attrs["unit"] = "u"
        part.create_dataset("fixed_mask", data=fx["mask"].astype(np.int8))


def w_chemfiles_xyz(fx, path):
    import chemfiles as cf
    fr = cf.Frame()
    for s, p in zip(fx["symbols"], fx["pos"]):
        fr.add_atom(cf.Atom(s), list(p))
    fr.cell = cf.UnitCell(list(np.linalg.norm(fx["cell"], axis=1)))
    fr.add_velocities()
    v = fr.velocities
    v[:] = fx["vel"]
    # Per-atom and per-frame properties are chemfiles' documented carrier for extra
    # data; the XYZ writer turns them into extended XYZ columns and comment keys.
    for k, (i, m) in enumerate(zip(fx["ids"], fx["mask"])):
        fr.atoms[k]["id"] = float(i)
        for j in range(3):
            fr.atoms[k][f"move_mask_{j}"] = not bool(m[j])
    fr["pbc"] = " ".join("T" if b else "F" for b in fx["pbc"])
    with cf.Trajectory(str(path), "w", "XYZ") as t:
        t.write(fr)


def w_ovito_xyz(fx, path):
    from ovito.data import DataCollection
    from ovito.io import export_file
    dc = DataCollection()
    dc.create_cell(fx["cell"], pbc=tuple(fx["pbc"]))
    p = dc.create_particles(count=len(fx["symbols"]))
    p.create_property("Position", data=fx["pos"])
    types = p.create_property("Particle Type")
    tid = {s: types.add_type_name(s, p).id for s in dict.fromkeys(fx["symbols"])}
    types[...] = [tid[s] for s in fx["symbols"]]
    p.create_property("Particle Identifier", data=fx["ids"].astype(np.int64))
    p.create_property("Velocity", data=fx["vel"])
    p.create_property("move_mask", dtype=int, components=["X", "Y", "Z"], data=(~fx["mask"]).astype(int))
    cols = ["Particle Type", "Position.X", "Position.Y", "Position.Z", "Particle Identifier",
            "Velocity.X", "Velocity.Y", "Velocity.Z", "move_mask.X", "move_mask.Y", "move_mask.Z"]
    export_file(dc, str(path), "xyz", columns=cols, precision=17)


def w_openbabel(fmt):
    def w(fx, path):
        from openbabel import openbabel as ob, pybel
        ob.obErrorLog.SetOutputLevel(0)
        mol = ob.OBMol()
        mol.BeginModify()
        for s, p, i in zip(fx["symbols"], fx["pos"], fx["ids"]):
            a = mol.NewAtom()
            a.SetAtomicNum(ob.GetAtomicNum(s))
            a.SetVector(*map(float, p))
            label = ob.OBPairData()
            label.SetAttribute("_atom_site_label")
            label.SetValue(f"{s}{int(i)}")
            a.CloneData(label)
        mol.EndModify()
        c = fx["cell"]
        uc = ob.OBUnitCell()
        uc.SetData(ob.vector3(*c[0]), ob.vector3(*c[1]), ob.vector3(*c[2]))
        uc.SetSpaceGroup("P 1")
        mol.CloneData(uc)
        pybel.Molecule(mol).write(fmt, str(path), overwrite=True)
    return w


# ---------------------------------------------------------------- readers
def r_readcon(path):
    import readcon
    f = readcon.read_con(str(path))[0]
    md = json.loads(readcon.write_con_string([f]).splitlines()[1] or "{}")
    unit = md.get("units", {}).get("time")
    return dict(pbc=md.get("pbc", [True, True, True]), pos=np.asarray(f.coords_array()), mask=np.array([a.fixed for a in f.atoms]),
                ids=np.asarray(f.atom_ids_array()),
                vel=np.asarray(f.velocities_array()) if f.has_velocities else None,
                unit_label=unit, vel_unit_fs=NAT_FS if unit and "amu" in unit else None,
                version=md.get("con_spec_version"), cell=np.asarray(f.cell, float))


def r_ase(fmt, ids_from="id"):
    def r(path):
        import ase.io
        return ase_snapshot(ase.io.read(str(path), format=fmt), ids_from)
    return r


def r_chemfiles(fmt):
    def r(path):
        import chemfiles as cf
        with cf.Trajectory(str(path), "r", fmt) as t:
            fr = t.read()
        n = len(fr.atoms)
        props = set(fr.atoms[0].list_properties()) if n else set()
        v = np.array(fr.velocities) if fr.has_velocities() else None
        ids = np.array([fr.atoms[i]["id"] for i in range(n)]) if "id" in props else None
        mask = None
        if {"move_mask_0", "move_mask_1", "move_mask_2"} <= props:
            mask = ~np.array([[bool(fr.atoms[i][f"move_mask_{j}"]) for j in range(3)] for i in range(n)])
        mom = np.array([fr.atoms[i]["momenta"] for i in range(n)]) if "momenta" in props else None
        pbc = None
        if "pbc" in fr.list_properties():
            pbc = [x.upper().startswith("T") for x in str(fr["pbc"]).split()]
        return dict(pos=np.array(fr.positions), mask=mask, ids=ids, vel=v, mom=mom, unit_label=None, vel_unit_fs=None,
                    pbc=pbc, cell=np.asarray(fr.cell.lengths, float))
    return r


def r_mda(fmt):
    def r(path):
        import MDAnalysis as mda
        u = mda.Universe(str(path), format=fmt) if fmt != "H5MD" else mda.Universe(str(path))
        ts = u.trajectory.ts
        v = ts.velocities.copy() if ts.has_velocities else None
        ids = u.atoms.ids.copy() if hasattr(u.atoms, "ids") else None
        # Only the H5MD reader fills trajectory.units from the file (the unit attribute of velocity/value);
        # MDAnalysis returns no periodicity flags.
        label = u.trajectory.units.get("velocity") if fmt == "H5MD" else None
        dims = ts.dimensions
        # MDAnalysis returns velocities in its base unit, A/ps, after converting from the file's label.
        return dict(pos=u.atoms.positions.astype(float), mask=None, ids=ids, vel=v, pbc=None,
                    unit_label=label, vel_unit_fs=1000.0 if label is not None else None,
                    cell=None if dims is None else np.asarray(dims[:3], float))
    return r


H5MD_TIME = {"fs": 1.0, "ps": 1000.0}
# Particle elements H5MD 1.1 defines (evidence/results/e4_cells.csv, Particles group).
H5MD_ELEMENTS = {"box", "position", "image", "velocity", "force", "mass", "species", "id", "charge"}


def h5md_layout(path):
    """The version of the file's H5MD root group (None without one) and the particle elements H5MD does not define."""
    import h5py
    with h5py.File(str(path)) as h:
        root = h.get("h5md")
        version = None
        if root is not None and "version" in root.attrs:
            version = ".".join(str(int(x)) for x in root.attrs["version"])
        groups = h["particles"].values() if "particles" in h else []
        private = sorted({name for g in groups for name in g if name not in H5MD_ELEMENTS})
    return version, private


def r_h5py_h5md(path):
    import h5py
    with h5py.File(str(path)) as h:
        part = h["particles/slab"]
        unit = part["velocity/value"].attrs.get("unit")
        unit = unit.decode() if isinstance(unit, bytes) else unit
        fs = time_unit_fs(unit) if (unit or "").split()[:1] == ["angstrom"] else None
        return dict(pos=part["position/value"][0], vel=part["velocity/value"][0], unit_label=unit, vel_unit_fs=fs,
                    ids=part["id"][()],
                    mask=part["fixed_mask"][()].astype(bool) if "fixed_mask" in part else None,
                    pbc=[(x.decode() if isinstance(x, bytes) else str(x)) == "periodic" for x in part["box"].attrs["boundary"]],
                    cell=np.asarray(part["box/edges"][()], float))


def r_ovito(path):
    from ovito.io import import_file
    d = import_file(str(path)).compute()
    P = d.particles
    keys = set(P.keys())
    return dict(pos=np.asarray(P.positions, float),
                mask=~np.asarray(P["move_mask"], bool) if "move_mask" in keys else None,
                ids=np.asarray(P["Particle Identifier"]) if "Particle Identifier" in keys else None,
                vel=np.asarray(P["Velocity"], float) if "Velocity" in keys else None,
                mom=np.asarray(P["momenta"], float) if "momenta" in keys else None,
                unit_label=None, vel_unit_fs=None, pbc=list(map(bool, d.cell.pbc)) if d.cell is not None else None,
                cell=np.linalg.norm(np.asarray(d.cell)[:, :3], axis=0) if d.cell is not None else None)


def r_openbabel(fmt):
    def r(path):
        from openbabel import openbabel as ob, pybel
        ob.obErrorLog.SetOutputLevel(0)
        m = next(pybel.readfile(fmt, str(path))).OBMol
        atoms = list(ob.OBMolAtomIter(m))
        data = [a.GetData("_atom_site_label") for a in atoms]
        uc = ob.toUnitCell(m.GetData(ob.UnitCell)) if m.HasData(ob.UnitCell) else None
        return dict(pos=np.array([[a.GetX(), a.GetY(), a.GetZ()] for a in atoms]),
                    labels=[d.GetValue() for d in data] if all(data) else None,
                    pbc=[True, True, True] if uc is not None else None,
                    cell=None if uc is None else np.array([uc.GetA(), uc.GetB(), uc.GetC()]))
    return r


# Carriers that each format's own specification names and defines
# (evidence/results/e4_cells.csv quotes the clause for each one). R4 is graded
# on the numbers alone.
SPEC = {
    "CON 3.1": {"R1", "R2", "R3", "pbc"},
    "extended XYZ": {"pbc"},          # Lattice, pbc, species, pos, velo (no unit); no id or mask
    "ASE trajectory": set(),          # ULM layout written down only by ASE
    "POSCAR": {"R1"},                 # selective dynamics; the velocity block has no time-unit label
    "H5MD": {"R2", "R3", "pbc"},      # particles/<group>/id, units module, box/boundary
    "H5MD, private mask dataset": {"R2", "R3", "pbc"},  # the same places; H5MD defines no mask element
    "XYZ": set(),
    "CIF": {"R2", "pbc"},             # _atom_site_label is a unique site label; the cell is periodic
}
RETURNED = {"R1": {"kept", "convention"}, "R2": {"kept", "convention", "label"},
            "R3": {"declared", "convention"}, "R4": {"bit-exact"}, "pbc": {"kept", "convention"}}

ROUTES = [
    ("CON 3.1", "readcon-core", "readcon-core", "con", w_readcon, r_readcon),
    ("extended XYZ", "ASE", "ASE", "xyz", w_ase("extxyz"), r_ase("extxyz")),
    ("extended XYZ", "ASE", "chemfiles", "xyz", w_ase("extxyz"), r_chemfiles("XYZ")),
    ("extended XYZ", "ASE", "OVITO", "xyz", w_ase("extxyz"), r_ovito),
    ("extended XYZ", "ASE", "MDAnalysis", "xyz", w_ase("extxyz"), r_mda("XYZ")),
    ("extended XYZ", "chemfiles", "chemfiles", "xyz", w_chemfiles_xyz, r_chemfiles("XYZ")),
    ("extended XYZ", "chemfiles", "ASE", "xyz", w_chemfiles_xyz, r_ase("extxyz")),
    ("extended XYZ", "OVITO", "OVITO", "xyz", w_ovito_xyz, r_ovito),
    ("extended XYZ", "OVITO", "ASE", "xyz", w_ovito_xyz, r_ase("extxyz")),
    ("ASE trajectory", "ASE", "ASE", "traj", w_ase("traj", tags=True), r_ase("traj", ids_from="tags")),
    ("POSCAR", "ASE, FixScaled", "ASE", "vasp", w_ase("vasp", scaled=True), r_ase("vasp")),
    ("H5MD", "MDAnalysis", "MDAnalysis", "h5md", w_mda_h5md, r_mda("H5MD")),
    ("H5MD, private mask dataset", "h5py", "h5py", "h5md", w_h5py_h5md, r_h5py_h5md),
    ("XYZ", "Open Babel", "Open Babel", "xyz", w_openbabel("xyz"), r_openbabel("xyz")),
    ("CIF", "Open Babel", "Open Babel", "cif", w_openbabel("cif"), r_openbabel("cif")),
]

# The library behind every writer and reader name of ROUTES; a route's pairing compares the two.
LIBRARY = {"readcon-core": "readcon-core", "ASE": "ASE", "ASE, FixScaled": "ASE", "chemfiles": "chemfiles",
           "OVITO": "OVITO",
           "MDAnalysis": "MDAnalysis", "h5py": "h5py", "Open Babel": "Open Babel"}

# Where each route stores the ids and the mask, for the supplement.
CARRIER = {
    ("extended XYZ", "ASE", "chemfiles"): "move_mask_0..2, id and momenta atom properties, pbc frame property string",
    ("extended XYZ", "ASE", "OVITO"): "move_mask and momenta user properties, id as Particle Identifier",
    ("ASE trajectory", "ASE", "ASE"): "ids as ASE tags",
    ("extended XYZ", "chemfiles", "chemfiles"): "id and move_mask_0..2 atom properties, pbc frame property",
    ("extended XYZ", "chemfiles", "ASE"): "id and move_mask_0..2 atom properties, pbc frame property",
    ("extended XYZ", "OVITO", "OVITO"): "Particle Identifier, Velocity, integer move_mask property, precision=17",
    ("extended XYZ", "OVITO", "ASE"): "Particle Identifier, Velocity, integer move_mask property, precision=17",
    ("POSCAR", "ASE, FixScaled", "ASE"): "adatom held by FixScaled(z)",
    ("H5MD, private mask dataset", "h5py", "h5py"): "particles/slab/id, velocity unit angstrom fs-1, box boundary, "
                                                    "private fixed_mask dataset",
    ("CIF", "Open Babel", "Open Babel"): "ids as _atom_site_label",
}


def version_carried(fmt, path):
    """The version the written file itself carries."""
    if not path.exists():
        return "no file"
    if fmt.startswith("CON"):
        try:
            md = json.loads(path.read_text().splitlines()[1])
        except (ValueError, IndexError):
            return "none"
        return f"{md['con_spec_version']}.{md.get('con_spec_minor', 0)}" if "con_spec_version" in md else "none"
    if fmt == "ASE trajectory":
        from ase.io import ulm
        head = path.read_bytes()[:32]
        tag = head[8:24].decode().strip()
        (file_version,) = struct.unpack("<q", head[24:32])
        r = ulm.open(str(path))
        try:
            return f"{tag}, ULM {file_version}, version {r.version}, ASE {r.ase_version}"
        finally:
            r.close()
    if fmt.startswith("H5MD"):
        return h5md_layout(path)[0] or "none"
    if fmt == "CIF":
        first = path.read_text().splitlines()[0]
        return first.split("_", 1)[1] if first.startswith("#\\#CIF_") else "none"
    return "none"


def shift(fx, p):
    """Largest coordinate change, the written coordinate where it occurs, and both in ULPs."""
    p = np.asarray(p, float)
    if p.shape != fx["pos"].shape:
        return dict(dpos=float("nan"), dpos_coord="", dpos_ulp="", ulp_max="")
    d = np.abs(p - fx["pos"])
    k = np.unravel_index(np.argmax(d), d.shape)
    x = fx["pos"][k]
    ulps = d / np.spacing(np.abs(fx["pos"]))
    return dict(dpos=float(d[k]), dpos_coord=float(x), dpos_ulp=float(d[k] / np.spacing(abs(x))),
                ulp_max=float(ulps.max()))


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
    labels = got.get("labels")
    if labels is not None and list(labels) == [f"{s}{int(i)}" for s, i in zip(fx["symbols"], fx["ids"])]:
        g["R2"] = "label"
    else:
        g["R2"] = "kept" if ids is not None and len(ids) == len(fx["ids"]) and (np.asarray(ids, np.int64) == fx["ids"].astype(np.int64)).all() else "lost"
    v = got.get("vel")
    if v is None and got.get("mom") is not None:
        v = np.asarray(got["mom"], float) / fx["masses"][:, None]
    if v is None or not np.any(v):
        g["R3"] = "lost"
    elif got.get("unit_label") is None:
        g["R3"] = "no unit"
    else:
        unit = got.get("vel_unit_fs")
        ok = unit is not None and np.allclose(np.asarray(v) * NAT_FS / unit, fx["vel"], rtol=1e-6, atol=1e-12)
        g["R3"] = "declared" if ok else "wrong values"
    s = shift(fx, got["pos"])
    d = s["dpos"]
    g["R4"] = "bit-exact" if d == 0.0 else f"{d:.1e} A"
    g.update(s)
    c = got.get("cell")
    g["dcell"] = "" if c is None else float(np.abs(np.asarray(c, float) - np.linalg.norm(fx["cell"], axis=1)).max())
    pb = got.get("pbc")
    g["pbc"] = "-" if pb is None else ("kept" if list(map(bool, pb)) == fx["pbc"] else "".join("T" if b else "F" for b in pb))
    return g


def apply_rule(fmt, row):
    for key in ("R1", "R2", "R3", "pbc"):
        if row[key] in ("kept", "declared", "label") and key not in SPEC.get(fmt, ()):
            row[key] = "convention"


def where(e):
    """File and line, relative to site-packages, of the innermost library frame of a traceback."""
    frames = [f for f in traceback.extract_tb(e.__traceback__) if "site-packages" in f.filename]
    if not frames:
        return ""
    f = frames[-1]
    return f"{f.filename.split('site-packages/', 1)[1]}:{f.lineno}"


def summary(rows):
    """Routes by pairing, routes that return every field, ids on completed cross-library routes, and the extreme
    coordinate shifts."""
    name = lambda r: f"{r['format']}: {r['writer']} -> {r['reader']}"
    every = [r for r in rows if all(r[k] in v for k, v in RETURNED.items()) and r["R5"] != "none"]
    by_spec = [r for r in every if "convention" not in (r["R1"], r["R2"], r["R3"], r["pbc"])]
    pairs = [r for r in rows if r["pairing"] == "cross-library"]
    cross = [r for r in pairs if r["dpos"] != ""]
    ids = [r for r in cross if r["R2"] in RETURNED["R2"]]
    moved = [r for r in rows if r["dpos"] not in ("", 0.0)]
    at = lambda r: dict(route=name(r), dpos=r["dpos"], dpos_coord=r["dpos_coord"], dpos_ulp=r["dpos_ulp"])
    return dict(returned={k: sorted(v) for k, v in RETURNED.items()},
                routes=len(rows),
                same_library_routes=sum(r["pairing"] == "same library" for r in rows),
                cross_library_routes=len(pairs),
                routes_returning_every_field_and_a_version=[name(r) for r in every],
                routes_returning_every_field_fixed_by_format=[name(r) for r in by_spec],
                formats_with_a_route_returning_every_field=sorted({r["format"] for r in every}),
                completed_cross_library_routes=len(cross),
                completed_cross_library_routes_returning_ids=len(ids),
                cross_library_routes_returning_ids=[name(r) for r in ids],
                cross_library_routes_losing_ids=[name(r) for r in cross if r not in ids],
                smallest_nonzero_shift=at(min(moved, key=lambda r: r["dpos"])),
                largest_shift=at(max(moved, key=lambda r: r["dpos"])))


def main():
    import provenance
    fx = fixture()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for k, (fmt, wr, rd, ext, w, r) in enumerate(ROUTES):
            path = Path(td) / f"route{k}.{ext}"
            key = (fmt, wr, rd)
            held = w.atoms(fx).constraints if hasattr(w, "atoms") else []
            row = dict(format=fmt, writer=wr, reader=rd,
                       constraint=", ".join(dict.fromkeys(type(c).__name__ for c in held)),
                       writer_library=LIBRARY[wr], reader_library=LIBRARY[rd],
                       pairing="same library" if LIBRARY[wr] == LIBRARY[rd] else "cross-library",
                       carrier=CARRIER.get(key, ""))
            try:
                w(fx, path)
                if fmt.startswith("H5MD"):
                    version, private = h5md_layout(path)
                    if version is None or bool(private) != ("private" in fmt):
                        raise SystemExit(f"{fmt} ({wr}): H5MD root version {version}, private elements {private}; "
                                         "the format name does not say what the file is")
            except Exception as e:
                label = "writer error"
                row.update(R1=label, R2=label, R3=label, R4=label, pbc=label, R5=label,
                           dpos="", dpos_coord="", dpos_ulp="", ulp_max="", dcell="",
                           error=f"{type(e).__name__}: {e}"[:160], error_at=where(e))
                rows.append(row); continue
            try:
                row.update(grade(fx, r(path)))
                apply_rule(fmt, row)
                row["R5"] = version_carried(fmt, path)
                row.setdefault("error", "")
            except BaseException as e:
                row.update(R1="reader error", R2="reader error", R3="reader error", R4="reader error", pbc="reader error",
                           R5=version_carried(fmt, path), dpos="", dpos_coord="", dpos_ulp="", ulp_max="", dcell="",
                           error=f"{type(e).__name__}: {e}"[:160], error_at=where(e))
            rows.append(row)
    import readcon
    record = provenance.record()
    meta = {**{k: record["peers"][k] for k in ("ase", "chemfiles", "MDAnalysis", "h5py", "ovito", "openbabel")},
            "readcon_spec": readcon.CON_SPEC_VERSION}
    fields = ["format", "writer", "reader", "constraint", "writer_library", "reader_library", "pairing",
              "R1", "R2", "R3", "R4", "pbc", "R5", "dpos", "dpos_coord", "dpos_ulp",
              "ulp_max", "dcell", "carrier", "error", "error_at"]
    with open(OUT / "matrix.csv", "w", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=fields, restval="")
        wtr.writeheader(); wtr.writerows(rows)
    (OUT / "matrix.json").write_text(json.dumps(dict(meta=meta, spec=SPEC, provenance=record,
                                                     summary=summary(rows), rows=rows),
                                                indent=1, default=lambda o: sorted(o) if isinstance(o, set) else str(o)))
    for r in rows:
        print(f"{r['format']:26s} {r['writer']:18s} -> {r['reader']:15s} | {r['R1']:12s} | {r['R2']:10s} | {r['R3']:30s} | "
              f"{r['R4']:10s} | {r['pbc']:10s} | {r['R5']} {r.get('error', '')}")


if __name__ == "__main__":
    main()
