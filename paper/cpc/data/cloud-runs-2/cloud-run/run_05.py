#!/usr/bin/env python3
"""Cross-binding, measured H5MD, and ASE-trajectory restart on one cloud-run driver.

Outputs go under paper/cpc/data/cloud-runs-2/05. The manuscript prose and the
existing data/failure tables are left untouched.
"""
from __future__ import annotations

import csv, json, os, re, shutil, subprocess, sys, tempfile, textwrap, tomllib, traceback
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)
import failure_matrix as fm
import restart_formats as rf

# READCON_CORE_ROOT is the readcon-core checkout whose library, headers,
# Fortran module and Julia package are under test.
CORE = Path(os.environ.get("READCON_CORE_ROOT", ROOT.parents[1]))
OUT = Path(os.environ.get("RUN05_OUT", HERE.parent / "05"))
LIB = Path(os.environ.get("READCON_CORE_LIB", CORE / "target" / "release" / "libreadcon_core.so"))
CAMP = Path(os.environ.get("RUN05_BUILD", Path(tempfile.gettempdir()) / "campaign"))
JULIA = os.environ.get("JULIA", "julia")
NAT = fm.NAT_FS

LANGS = ["Python", "C", "C++", "Fortran", "Julia"]

# Before 0.17.2 builder%add_atom has no velocity argument, and in 0.17.1 it
# passes the atom id where rkr_frame_add_atom_with_fixed_mask takes the mask.
# The version alone does not show the new_builder header argument, which
# arrived within 0.17.2 at 5c849d1, so the module is also compiled against a probe.
MIN_CORE = (0, 17, 2)
MIN_CORE_COMMIT = "5c849d1"
PROBE = """\
program probe
  use readcon
  use, intrinsic :: iso_fortran_env, only: real64, int64
  type(builder_t) :: b
  integer :: s
  b = new_builder([1.0_real64, 1.0_real64, 1.0_real64], [90.0_real64, 90.0_real64, 90.0_real64], &
       header="image 0")
  s = b%add_atom("H", 0.0_real64, 0.0_real64, 0.0_real64, 1_int64, 1.0_real64, &
       .false., .false., .false., velocity=[0.0_real64, 0.0_real64, 0.0_real64])
end program
"""


def _version(text):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def require_fixed_core():
    import ctypes
    need = ".".join(map(str, MIN_CORE))
    problems = []
    manifest = CORE / "Cargo.toml"
    try:
        src = tomllib.loads(manifest.read_text())["package"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
        src = None
        problems.append(f"cannot read the version from {manifest}: {e}")
    if src is not None and (_version(src) or (0,)) < MIN_CORE:
        problems.append(f"{manifest} is readcon-core {src}")
    try:
        lib = ctypes.CDLL(str(LIB))
        lib.rkr_library_version.restype = ctypes.c_char_p
        built = lib.rkr_library_version().decode()
    except (OSError, AttributeError) as e:
        built = None
        problems.append(f"cannot load rkr_library_version from {LIB}: {e}")
    if built is not None and (_version(built) or (0,)) < MIN_CORE:
        problems.append(f"{LIB} reports readcon-core {built}")
    module = CORE / "fortran" / "ReadCon" / "src" / "readcon.f90"
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.f90"
        probe.write_text(PROBE)
        try:
            p = subprocess.run(["gfortran", "-fsyntax-only", "-ffree-line-length-none", "-J", tmp,
                                str(module), str(probe)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if p.returncode != 0:
                errors = [line for line in p.stderr.splitlines() if line.startswith("Error")]
                problems.append(f"{module} lacks new_builder(header=) or add_atom(velocity=)\n    "
                                + "\n    ".join(errors or [p.stderr[-800:]]))
        except OSError as e:
            problems.append(f"cannot run gfortran on {module}: {e}")
    if problems:
        sys.exit(
            f"run_05: the Fortran column needs readcon-core {need} at {MIN_CORE_COMMIT} or later.\n  "
            + "\n  ".join(problems)
            + "\nSet READCON_CORE_ROOT to such a checkout and READCON_CORE_LIB to its library."
        )
    return src, built


def meta_of(pbc):
    return json.dumps({
        "pbc": [bool(x) for x in pbc],
        "units": {"length": "angstrom", "energy": "eV", "mass": "amu",
                  "time": "(amu*angstrom^2/eV)^0.5"},
    }, separators=(",", ":"))


def dump_band(path, frames):
    lines = [f"NFRAMES {len(frames)}"]
    for fr in frames:
        lines.append("FRAME")
        lines.append(f"NATOMS {len(fr['symbols'])}")
        cell = fr["cell"]
        ang = fr["angles"]
        lines.append("CELL " + " ".join(f"{x:.17e}" for x in cell))
        lines.append("ANGLES " + " ".join(f"{x:.17e}" for x in ang))
        pbc = fr["pbc"]
        lines.append("PBC " + " ".join("1" if b else "0" for b in pbc))
        lines.append("META " + fr["meta"])
        lines.append("ATOMS")
        for i, sym in enumerate(fr["symbols"]):
            m = fr["mask"][i]
            v = fr["vel"][i] if fr["vel"] is not None else (0, 0, 0)
            hv = 0 if fr["vel"] is None else 1
            lines.append(
                f"{sym} {fr['pos'][i,0]:.17e} {fr['pos'][i,1]:.17e} {fr['pos'][i,2]:.17e} "
                f"{int(fr['ids'][i])} {fr['masses'][i]:.17e} {int(m[0])} {int(m[1])} {int(m[2])} "
                f"{v[0]:.17e} {v[1]:.17e} {v[2]:.17e} {hv}"
            )
        lines.append("ENDFRAME")
    Path(path).write_text("\n".join(lines) + "\n")


def load_band(path):
    lines = Path(path).read_text().splitlines()
    i = 0
    n = int(lines[i].split()[1]); i += 1
    frames = []
    for _ in range(n):
        assert lines[i] == "FRAME"; i += 1
        nat = int(lines[i].split()[1]); i += 1
        cell = np.array([float(x) for x in lines[i].split()[1:]], float); i += 1
        angles = np.array([float(x) for x in lines[i].split()[1:]], float); i += 1
        pbc_i = [int(x) for x in lines[i].split()[1:]]; i += 1
        meta = lines[i][5:] if lines[i].startswith("META ") else lines[i]; i += 1
        assert lines[i] == "ATOMS"; i += 1
        syms, pos, ids, mass, mask, vel, has = [], [], [], [], [], [], []
        for _a in range(nat):
            t = lines[i].split(); i += 1
            syms.append(t[0])
            pos.append([float(t[1]), float(t[2]), float(t[3])])
            ids.append(int(t[4])); mass.append(float(t[5]))
            mask.append([t[6] != "0", t[7] != "0", t[8] != "0"])
            vel.append([float(t[9]), float(t[10]), float(t[11])])
            has.append(t[12] != "0")
        assert lines[i] == "ENDFRAME"; i += 1
        pbc = None if any(x < 0 for x in pbc_i) else [bool(x) for x in pbc_i]
        use_v = any(has)
        frames.append(dict(
            symbols=syms, pos=np.array(pos, float), cell=cell, angles=angles,
            mask=np.array(mask, bool), ids=np.array(ids, np.int64),
            masses=np.array(mass, float),
            vel=np.array(vel, float) if use_v else None,
            pbc=pbc, meta=meta,
        ))
    return frames


def frame_from_fixture(fx):
    lengths = np.linalg.norm(fx["cell"], axis=1)
    return dict(symbols=list(fx["symbols"]), pos=np.array(fx["pos"], float),
                cell=lengths, angles=np.array([90.0, 90.0, 90.0]),
                mask=np.array(fx["mask"], bool), ids=np.array(fx["ids"], np.int64),
                masses=np.array(fx["masses"], float), vel=np.array(fx["vel"], float),
                pbc=list(fx["pbc"]), meta=meta_of(fx["pbc"]))


def frame_from_atoms(atoms, index):
    lengths = np.linalg.norm(np.array(atoms.cell), axis=1)
    mask = np.zeros((len(atoms), 3), bool)
    from ase.constraints import FixAtoms, FixCartesian
    for c in atoms.constraints:
        if isinstance(c, FixAtoms):
            mask[c.index] = True
        elif isinstance(c, FixCartesian):
            mask[c.index] |= np.asarray(c.mask, bool)
    ids = atoms.arrays.get("id")
    if ids is None:
        ids = np.arange(1, len(atoms) + 1, dtype=np.int64)
    vel = atoms.get_velocities() if atoms.has("momenta") else None
    return dict(symbols=list(atoms.get_chemical_symbols()), pos=atoms.get_positions().copy(),
                cell=lengths, angles=np.array([90.0, 90.0, 90.0]),
                mask=mask, ids=np.array(ids, np.int64), masses=atoms.get_masses().copy(),
                vel=None if vel is None else np.array(vel, float),
                pbc=list(map(bool, atoms.pbc)), meta=meta_of(atoms.pbc))


class CAbi:
    def __init__(self, path):
        import ctypes
        self.ct = ctypes
        lib = ctypes.CDLL(str(path))
        self.lib = lib

        class CAtom(ctypes.Structure):
            _fields_ = [
                ("atomic_number", ctypes.c_uint64),
                ("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double),
                ("atom_id", ctypes.c_uint64), ("mass", ctypes.c_double),
                ("is_fixed", ctypes.c_bool), ("fixed_x", ctypes.c_bool),
                ("fixed_y", ctypes.c_bool), ("fixed_z", ctypes.c_bool),
                ("_p1", ctypes.c_char * 4),
                ("vx", ctypes.c_double), ("vy", ctypes.c_double), ("vz", ctypes.c_double),
                ("has_velocity", ctypes.c_bool), ("_p2", ctypes.c_char * 7),
                ("fx", ctypes.c_double), ("fy", ctypes.c_double), ("fz", ctypes.c_double),
                ("has_forces", ctypes.c_bool), ("_p3", ctypes.c_char * 7),
                ("energy", ctypes.c_double), ("has_energy", ctypes.c_bool),
                ("_p4", ctypes.c_char * 7),
            ]
        class CFrame(ctypes.Structure):
            _fields_ = [
                ("atoms", ctypes.POINTER(CAtom)),
                ("num_atoms", ctypes.c_size_t),
                ("cell", ctypes.c_double * 3),
                ("angles", ctypes.c_double * 3),
                ("has_velocities", ctypes.c_bool),
                ("has_forces", ctypes.c_bool),
                ("has_energies", ctypes.c_bool),
                ("_p", ctypes.c_char * 5),
            ]
        assert ctypes.sizeof(CAtom) == 136, ctypes.sizeof(CAtom)
        assert ctypes.sizeof(CFrame) == 72, ctypes.sizeof(CFrame)
        self.CFrame = CFrame
        lib.rkr_frame_new.restype = ctypes.c_void_p
        lib.rkr_frame_new.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                                      ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.rkr_frame_builder_set_metadata_json.restype = ctypes.c_int
        lib.rkr_frame_builder_set_metadata_json.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.rkr_frame_add_atom_with_velocity_fixed_mask.restype = ctypes.c_int
        lib.rkr_frame_add_atom_with_velocity_fixed_mask.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_double,
            ctypes.c_bool, ctypes.c_bool, ctypes.c_bool, ctypes.c_uint64, ctypes.c_double,
            ctypes.c_double, ctypes.c_double, ctypes.c_double]
        lib.rkr_frame_add_atom_with_fixed_mask.restype = ctypes.c_int
        lib.rkr_frame_add_atom_with_fixed_mask.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_double,
            ctypes.c_bool, ctypes.c_bool, ctypes.c_bool, ctypes.c_uint64, ctypes.c_double]
        lib.rkr_frame_builder_build.restype = ctypes.c_void_p
        lib.rkr_frame_builder_build.argtypes = [ctypes.c_void_p]
        lib.free_rkr_frame_builder.argtypes = [ctypes.c_void_p]
        lib.create_writer_from_path_c.restype = ctypes.c_void_p
        lib.create_writer_from_path_c.argtypes = [ctypes.c_char_p]
        lib.rkr_writer_extend.restype = ctypes.c_int
        lib.rkr_writer_extend.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        lib.rkr_writer_flush.restype = ctypes.c_int
        lib.rkr_writer_flush.argtypes = [ctypes.c_void_p]
        lib.free_rkr_writer.argtypes = [ctypes.c_void_p]
        lib.free_rkr_frame.argtypes = [ctypes.c_void_p]
        lib.rkr_read_all_frames.restype = ctypes.POINTER(ctypes.c_void_p)
        lib.rkr_read_all_frames.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t)]
        lib.rkr_frame_to_c_frame.restype = ctypes.POINTER(CFrame)
        lib.rkr_frame_to_c_frame.argtypes = [ctypes.c_void_p]
        lib.free_c_frame.argtypes = [ctypes.POINTER(CFrame)]
        lib.free_rkr_frame_array.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        lib.rkr_frame_metadata_json.restype = ctypes.c_void_p
        lib.rkr_frame_metadata_json.argtypes = [ctypes.c_void_p]
        lib.rkr_free_string.argtypes = [ctypes.c_void_p]
        lib.rkr_z_to_symbol.restype = ctypes.c_char_p
        lib.rkr_z_to_symbol.argtypes = [ctypes.c_uint64]

    def _check(self, status, what):
        if status != 0:
            raise RuntimeError(f"{what} status {status}")

    def write(self, frames, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "manifest.txt").write_text(f"{len(frames)}\n")
        ct = self.ct
        for i, fr in enumerate(frames):
            cell = (ct.c_double * 3)(*fr["cell"])
            ang = (ct.c_double * 3)(*fr["angles"])
            b = self.lib.rkr_frame_new(cell, ang, f"image {i}".encode(), b"", b"", b"")
            if not b:
                raise RuntimeError("rkr_frame_new failed")
            self._check(self.lib.rkr_frame_builder_set_metadata_json(b, fr["meta"].encode()), "metadata")
            for a in range(len(fr["symbols"])):
                sym = fr["symbols"][a].encode()
                m = fr["mask"][a]
                if fr["vel"] is None:
                    st = self.lib.rkr_frame_add_atom_with_fixed_mask(
                        b, sym, fr["pos"][a, 0], fr["pos"][a, 1], fr["pos"][a, 2],
                        bool(m[0]), bool(m[1]), bool(m[2]), int(fr["ids"][a]), float(fr["masses"][a]))
                else:
                    v = fr["vel"][a]
                    st = self.lib.rkr_frame_add_atom_with_velocity_fixed_mask(
                        b, sym, fr["pos"][a, 0], fr["pos"][a, 1], fr["pos"][a, 2],
                        bool(m[0]), bool(m[1]), bool(m[2]), int(fr["ids"][a]), float(fr["masses"][a]),
                        float(v[0]), float(v[1]), float(v[2]))
                self._check(st, "add_atom")
            handle = self.lib.rkr_frame_builder_build(b)
            if not handle:
                raise RuntimeError("build failed")
            path = str(directory / f"frame_{i:03d}.con").encode()
            w = self.lib.create_writer_from_path_c(path)
            if not w:
                raise RuntimeError("writer failed")
            arr = (ct.c_void_p * 1)(handle)
            self._check(self.lib.rkr_writer_extend(w, arr, 1), "extend")
            self._check(self.lib.rkr_writer_flush(w), "flush")
            self.lib.free_rkr_writer(w)
            self.lib.free_rkr_frame(handle)

    def read(self, directory):
        directory = Path(directory)
        n = int((directory / "manifest.txt").read_text().split()[0])
        ct = self.ct
        out = []
        for i in range(n):
            count = ct.c_size_t()
            arr = self.lib.rkr_read_all_frames(str(directory / f"frame_{i:03d}.con").encode(), ct.byref(count))
            if not arr or count.value != 1:
                raise RuntimeError(f"C read frame {i} count {count.value}")
            handle = arr[0]
            cf = self.lib.rkr_frame_to_c_frame(handle)
            raw = self.lib.rkr_frame_metadata_json(handle)
            meta = ct.cast(raw, ct.c_char_p).value.decode() if raw else ""
            if raw:
                self.lib.rkr_free_string(raw)
            nat = cf.contents.num_atoms
            syms, pos, ids, mass, mask, vel = [], [], [], [], [], []
            anyv = False
            for a in range(nat):
                at = cf.contents.atoms[a]
                sym = self.lib.rkr_z_to_symbol(at.atomic_number).decode()
                syms.append(sym)
                pos.append([at.x, at.y, at.z])
                ids.append(at.atom_id)
                mass.append(at.mass)
                mask.append([bool(at.fixed_x), bool(at.fixed_y), bool(at.fixed_z)])
                vel.append([at.vx, at.vy, at.vz])
                anyv = anyv or bool(at.has_velocity)
            pbc = pbc_from_meta(meta)
            out.append(dict(
                symbols=syms, pos=np.array(pos, float),
                cell=np.array(list(cf.contents.cell), float),
                angles=np.array(list(cf.contents.angles), float),
                mask=np.array(mask, bool), ids=np.array(ids, np.int64),
                masses=np.array(mass, float),
                vel=np.array(vel, float) if anyv else None,
                pbc=pbc, meta=meta,
            ))
            self.lib.free_c_frame(cf)
            self.lib.free_rkr_frame_array(arr, count)
        return out


def pbc_from_meta(meta):
    try:
        d = json.loads(meta) if meta.strip().startswith("{") else {}
    except json.JSONDecodeError:
        d = {}
    p = d.get("pbc")
    if not isinstance(p, list) or len(p) != 3:
        return None
    return [bool(x) for x in p]


def py_write(frames, directory):
    import readcon
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.txt").write_text(f"{len(frames)}\n")
    for i, fr in enumerate(frames):
        atoms = []
        for s, p, m, ident, ms, v in zip(fr["symbols"], fr["pos"], fr["mask"], fr["ids"], fr["masses"],
                                         fr["vel"] if fr["vel"] is not None else [None] * len(fr["symbols"])):
            kw = {}
            if v is not None:
                kw = dict(vx=float(v[0]), vy=float(v[1]), vz=float(v[2]))
            atoms.append(readcon.Atom(s, float(p[0]), float(p[1]), float(p[2]),
                                      fixed=[bool(b) for b in m], atom_id=int(ident), mass=float(ms), **kw))
        md = json.loads(fr["meta"])
        frame = readcon.ConFrame(list(map(float, fr["cell"])), list(map(float, fr["angles"])), atoms,
                                 prebox_header=[f"image {i}", ""], metadata=md)
        readcon.write_con(str(directory / f"frame_{i:03d}.con"), [frame])


def py_read(directory):
    import readcon
    directory = Path(directory)
    n = int((directory / "manifest.txt").read_text().split()[0])
    out = []
    for i in range(n):
        f = readcon.read_con(str(directory / f"frame_{i:03d}.con"))[0]
        md = dict(f.metadata) if f.metadata is not None else {}
        mask = np.array([a.fixed for a in f.atoms], bool)
        ids = np.asarray(f.atom_ids_array())
        vel = np.asarray(f.velocities_array()) if f.has_velocities else None
        out.append(dict(
            symbols=[a.symbol for a in f.atoms],
            pos=np.asarray(f.coords_array(), float),
            cell=np.array(list(f.cell), float),
            angles=np.array(list(f.angles), float),
            mask=mask, ids=np.asarray(ids, np.int64),
            masses=np.array([float(a.mass) if a.mass is not None else np.nan for a in f.atoms], float),
            vel=vel, pbc=md.get("pbc"), meta=json.dumps(md),
        ))
    return out


def tool_call(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{p.stdout[-400:]}\n{p.stderr[-800:]}")


def external_write(cmd, frames, directory):
    directory = Path(directory)
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    band = directory / "_in.txt"
    dump_band(band, frames)
    tool_call(cmd + [str(band), str(directory)])


def external_read(cmd, directory):
    out = Path(directory) / "_out.txt"
    tool_call(cmd + [str(directory), str(out)])
    return load_band(out)


class Bridge:
    def __init__(self, available):
        self.available = available
        self.c = CAbi(LIB) if "C" in available else None

    def write(self, lang, frames, directory):
        if lang not in self.available:
            raise RuntimeError(self.available.get(lang + "_error", f"{lang} unavailable"))
        if lang == "Python":
            py_write(frames, directory)
        elif lang == "C":
            self.c.write(frames, directory)
        elif lang == "C++":
            external_write([str(CAMP / "cpp_io"), "write"], frames, directory)
        elif lang == "Fortran":
            external_write([str(CAMP / "fortran_io"), "write"], frames, directory)
        elif lang == "Julia":
            env = os.environ.copy()
            env["READCON_CORE_LIB"] = str(LIB)
            directory = Path(directory)
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True)
            band = directory / "_in.txt"
            dump_band(band, frames)
            p = subprocess.run([JULIA, f"--project={CORE / 'julia' / 'ReadCon'}",
                                str(HERE / "julia_io.jl"), "write", str(band), str(directory)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            if p.returncode != 0:
                raise RuntimeError(p.stderr[-1000:] or p.stdout[-1000:])
        else:
            raise RuntimeError(lang)

    def read(self, lang, directory):
        if lang == "Python":
            return py_read(directory)
        if lang == "C":
            return self.c.read(directory)
        if lang == "C++":
            return external_read([str(CAMP / "cpp_io"), "read"], directory)
        if lang == "Fortran":
            return external_read([str(CAMP / "fortran_io"), "read"], directory)
        if lang == "Julia":
            env = os.environ.copy()
            env["READCON_CORE_LIB"] = str(LIB)
            out = Path(directory) / "_out.txt"
            p = subprocess.run([JULIA, f"--project={CORE / 'julia' / 'ReadCon'}",
                                str(HERE / "julia_io.jl"), "read", str(directory), str(out)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            if p.returncode != 0:
                raise RuntimeError(p.stderr[-1000:] or p.stdout[-1000:])
            return load_band(out)
        raise RuntimeError(lang)


def got_for_grade(fr):
    unit = None
    try:
        d = json.loads(fr["meta"]) if fr["meta"] else {}
    except json.JSONDecodeError:
        d = {}
    time = (d.get("units") or {}).get("time") if isinstance(d, dict) else None
    if time and "amu" in str(time):
        unit = NAT
    return dict(pos=fr["pos"], mask=fr["mask"], ids=fr["ids"], vel=fr["vel"],
                vel_unit_fs=unit, pbc=fr["pbc"])


def orthogonal_cell(lengths, template):
    cell = np.array(template, float).copy()
    # Keep the template orientation when the lengths match; otherwise a diagonal cell.
    if np.allclose(np.linalg.norm(cell, axis=1), lengths, rtol=0, atol=1e-8):
        return cell
    return np.diag(lengths)


def ase_from_frame(fr, template_atoms):
    from ase import Atoms
    from ase.constraints import FixAtoms, FixCartesian
    cell = orthogonal_cell(fr["cell"], template_atoms.cell.array)
    pbc = fr["pbc"] if fr["pbc"] is not None else list(map(bool, template_atoms.pbc))
    symbols = fr["symbols"] if fr["symbols"] else list(template_atoms.get_chemical_symbols())
    a = Atoms(symbols, positions=fr["pos"], cell=cell, pbc=pbc)
    mask = fr["mask"]
    if mask is not None and np.any(mask):
        full = [i for i, m in enumerate(mask) if np.all(m)]
        cons = [FixAtoms(indices=full)] if full else []
        cons += [FixCartesian(i, mask=tuple(bool(x) for x in m))
                 for i, m in enumerate(mask) if np.any(m) and not np.all(m)]
        a.set_constraint(cons)
    if fr["vel"] is not None:
        a.set_velocities(fr["vel"])
    if fr["ids"] is not None:
        a.set_array("id", fr["ids"].astype(np.int64))
    return a


def attach_h5md(path, fx):
    import h5py
    with h5py.File(path, "a") as h:
        g = h["particles/trajectory"]
        if "fixed" in g:
            del g["fixed"]
        g.create_dataset("fixed", data=np.asarray(fx["mask"], dtype=bool))
        if "id" in g:
            del g["id"]
        g.create_dataset("id", data=np.asarray(fx["ids"], dtype=np.int64))
        g["box"].attrs["boundary"] = np.array(["periodic", "periodic", "none"], dtype=object)
        if "velocity" in g and "value" in g["velocity"]:
            g["velocity/value"].attrs["unit"] = "Angstrom ps-1"


def w_mda_convention(fx, path):
    fm.w_mda_h5md(fx, path)
    attach_h5md(path, fx)


def w_h5py(fx, path, dtype=np.float64):
    import h5py
    n = len(fx["symbols"])
    pos = np.asarray(fx["pos"], dtype=dtype)[None, :, :]
    vel = (np.asarray(fx["vel"], dtype=dtype) / NAT * 1000.0)[None, :, :]
    cell = np.asarray(fx["cell"], dtype=dtype)
    edges = np.zeros((1, 3, 3), dtype=dtype)
    edges[0] = cell
    with h5py.File(path, "w") as h:
        root = h.create_group("h5md")
        root.attrs["version"] = np.array([1, 1], dtype=np.int32)
        author = root.create_group("author")
        author.attrs["name"] = "readcon-cloud-run"
        creator = root.create_group("creator")
        creator.attrs["name"] = "h5py"
        creator.attrs["version"] = h5py.version.version
        g = h.create_group("particles/trajectory")
        box = g.create_group("box")
        box.attrs["dimension"] = np.int64(3)
        box.attrs["boundary"] = np.array(["periodic", "periodic", "none"], dtype=object)
        eg = box.create_group("edges")
        eg.create_dataset("step", data=np.array([0], dtype=np.int32))
        t = eg.create_dataset("time", data=np.array([0], dtype=dtype)); t.attrs["unit"] = "ps"
        v = eg.create_dataset("value", data=edges); v.attrs["unit"] = "Angstrom"
        for name, data, unit in (("position", pos, "Angstrom"), ("velocity", vel, "Angstrom ps-1")):
            gg = g.create_group(name)
            gg.create_dataset("step", data=np.array([0], dtype=np.int32))
            tt = gg.create_dataset("time", data=np.array([0], dtype=dtype)); tt.attrs["unit"] = "ps"
            dd = gg.create_dataset("value", data=data); dd.attrs["unit"] = unit
        g.create_dataset("fixed", data=np.asarray(fx["mask"], dtype=bool))
        g.create_dataset("id", data=np.asarray(fx["ids"], dtype=np.int64))


def r_h5py(path):
    import h5py
    with h5py.File(path) as h:
        g = h["particles/trajectory"]
        pos = np.array(g["position/value"][0], float)
        vel = np.array(g["velocity/value"][0], float) if "velocity" in g else None
        unit = str(g["velocity/value"].attrs.get("unit", "")) if vel is not None else ""
        mask = np.array(g["fixed"]) if "fixed" in g else None
        ids = np.array(g["id"]) if "id" in g else None
        b = g["box"].attrs["boundary"]
        pbc = [str(x) == "periodic" for x in b]
    vel_unit = 1000.0 if "ps" in unit else None
    return dict(pos=pos, mask=mask, ids=ids, vel=vel, vel_unit_fs=vel_unit, pbc=pbc)


def mark_h5md(row):
    # `fixed` is not an H5MD element. `id`, the velocity `unit` attribute, and
    # `boundary` are in the H5MD specification.
    if row.get("R1") == "kept":
        row["R1"] = "by convention"
    return row


def compile_bindings():
    notes = []
    available = {"Python": True}
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(LIB.parent) + ":" + env.get("LD_LIBRARY_PATH", "")
    try:
        CAbi(LIB)
        available["C"] = True
    except Exception as e:
        notes.append(f"C ABI: {type(e).__name__}: {e}")
    CAMP.mkdir(parents=True, exist_ok=True)
    cpp = CAMP / "cpp_io"
    p = subprocess.run(["g++", "-std=c++17", "-O2", "-Wno-deprecated-declarations",
                        "-I", str(CORE / "include"),
                        str(HERE / "cpp_io.cpp"), "-L", str(LIB.parent), "-lreadcon_core",
                        "-Wl,-rpath," + str(LIB.parent), "-o", str(cpp)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode == 0:
        available["C++"] = True
    else:
        notes.append("C++ build failed:\n" + p.stderr[-2000:])
    fort = CAMP / "fortran_io"
    p = subprocess.run(["gfortran", "-O2", "-ffree-line-length-none", "-J", str(CAMP),
                        str(CORE / "fortran" / "ReadCon" / "src" / "readcon.f90"),
                        str(HERE / "fortran_io.f90"), "-L", str(LIB.parent), "-lreadcon_core",
                        "-Wl,-rpath," + str(LIB.parent), "-o", str(fort)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode == 0:
        available["Fortran"] = True
        notes.append("Fortran writer calls builder%add_atom with its optional velocity argument.")
    else:
        sys.exit(f"run_05: fortran_io did not compile against {CORE}.\n" + p.stderr[-2000:])
    envj = env.copy()
    envj["READCON_CORE_LIB"] = str(LIB)
    p = subprocess.run([JULIA, f"--project={CORE / 'julia' / 'ReadCon'}", "-e",
                        "using ReadCon; println(ReadCon.read_con)"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=envj)
    if p.returncode == 0:
        available["Julia"] = True
    else:
        notes.append("Julia load failed:\n" + (p.stderr or p.stdout)[-2000:])
    return available, notes, env


def fx_of_atoms(atoms):
    """Failure-matrix fixture shape from one ASE image, for H5MD resume writers."""
    mask = np.zeros((len(atoms), 3), bool)
    from ase.constraints import FixAtoms, FixCartesian
    for c in atoms.constraints:
        if isinstance(c, FixAtoms):
            mask[c.index] = True
        elif isinstance(c, FixCartesian):
            mask[c.index] |= np.asarray(c.mask, bool)
    ids = atoms.arrays.get("id")
    if ids is None:
        ids = np.arange(len(atoms), dtype=np.int64)
    return dict(symbols=list(atoms.get_chemical_symbols()), pos=atoms.get_positions().copy(),
                cell=np.array(atoms.cell.array, float), pbc=list(map(bool, atoms.pbc)),
                mask=mask, ids=np.array(ids, np.int64), vel=atoms.get_velocities().copy(),
                masses=atoms.get_masses().copy())


def h5_roundtrip(writer, reader, images):
    back = []
    with tempfile.TemporaryDirectory() as td:
        for i, im in enumerate(images):
            path = Path(td) / f"img{i}.h5md"
            writer(fx_of_atoms(im), path)
            got = reader(path)
            # H5MD does not store the element symbols in these files.
            fr = dict(symbols=list(im.get_chemical_symbols()), pos=got["pos"],
                      cell=np.linalg.norm(np.array(im.cell), axis=1),
                      angles=np.array([90.0, 90.0, 90.0]),
                      mask=got.get("mask"), ids=got.get("ids"),
                      masses=im.get_masses(), vel=None, pbc=got.get("pbc"), meta="")
            if got.get("vel") is not None and got.get("vel_unit_fs"):
                fr["vel"] = np.asarray(got["vel"]) * NAT / got["vel_unit_fs"]
            back.append(ase_from_frame(fr, im))
    return back


def main():
    src, built = require_fixed_core()
    print(f"readcon-core source {src}, library {built}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "logs").mkdir(exist_ok=True)
    available, notes, env = compile_bindings()
    os.environ["LD_LIBRARY_PATH"] = env.get("LD_LIBRARY_PATH", "")
    (OUT / "build.txt").write_text("\n\n".join(notes) if notes else "all five bindings built\n")
    print("bindings", sorted(k for k, v in available.items() if v is True), flush=True)
    for n in notes:
        print(n[:500], flush=True)
    bridge = Bridge(available)

    # --- failure matrix: original routes, then cross-binding, then measured H5MD ---
    fx = fm.fixture()
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for k, (fmt, wr, rd, ext, w, r) in enumerate(fm.ROUTES):
            path = Path(td) / f"route{k}.{ext}"
            row = dict(format=fmt, writer=wr, reader=rd, notes="")
            try:
                w(fx, path)
                row.update(fm.grade(fx, r(path)))
                for key in fm.CONVENTION.get((fmt, wr, rd), ()):
                    if row[key] in ("kept", "declared"):
                        row[key] = "convention"
                for key in fm.FORMAT_FIXED.get((fmt, wr, rd), ()):
                    if row[key] in ("kept", "declared"):
                        row[key] = "fixed by format"
                row["error"] = ""
            except BaseException as e:
                row.update(R1="error", R2="error", R3="error", R4="error", pbc="", dpos="",
                           error=f"{type(e).__name__}: {e}"[:300])
            rows.append(row)
            print(f"matrix {fmt} {wr}->{rd} {row.get('R1')} {row.get('error','')[:80]}", flush=True)

        langs = [L for L in LANGS if available.get(L) is True]
        one = [frame_from_fixture(fx)]
        for wr in langs:
            for rd in langs:
                row = dict(format="CON 3.1", writer=wr, reader=rd, notes="cross-binding")
                d = Path(td) / f"x-{wr}-{rd}"
                try:
                    bridge.write(wr, one, d)
                    got = bridge.read(rd, d)[0]
                    # Grade against the original fixture positions. Masses may be
                    # canonicalised by the writer; the grade uses the fixture masses.
                    row.update(fm.grade(fx, got_for_grade(got)))
                    row["error"] = ""
                    if wr == "Fortran":
                        row["notes"] = "Fortran writes through builder%add_atom"
                except BaseException as e:
                    row.update(R1="error", R2="error", R3="error", R4="error", pbc="", dpos="",
                               error=f"{type(e).__name__}: {e}"[:300])
                rows.append(row)
                print(f"cross {wr}->{rd} R1={row.get('R1')} R3={row.get('R3')} {row.get('error','')[:80]}", flush=True)

        h5_routes = [
            ("H5MD", "MDAnalysis", "MDAnalysis", w_mda_convention, fm.r_mda("H5MD")),
            ("H5MD", "MDAnalysis", "h5py", w_mda_convention, r_h5py),
            ("H5MD", "h5py", "h5py", w_h5py, r_h5py),
            ("H5MD", "h5py", "MDAnalysis", w_h5py, fm.r_mda("H5MD")),
        ]
        for fmt, wr, rd, w, r in h5_routes:
            path = Path(td) / f"{wr}-{rd}.h5md"
            row = dict(format=fmt, writer=wr, reader=rd,
                       notes="measured; fixed is by convention; id, unit and boundary are H5MD names")
            try:
                w(fx, path)
                row.update(fm.grade(fx, r(path)))
                mark_h5md(row)
                row["error"] = ""
            except BaseException as e:
                row.update(R1="error", R2="error", R3="error", R4="error", pbc="", dpos="",
                           error=f"{type(e).__name__}: {e}"[:300])
            rows.append(row)
            print(f"h5 {wr}->{rd} {row.get('R1')} {row.get('R4')} {row.get('error','')[:100]}", flush=True)

    import ase, chemfiles, MDAnalysis, h5py, readcon
    meta = dict(ase=ase.__version__, chemfiles=chemfiles.__version__,
                MDAnalysis=MDAnalysis.__version__, h5py=h5py.__version__,
                readcon_spec=readcon.CON_SPEC_VERSION, numpy=np.__version__)
    fields = ["format", "writer", "reader", "R1", "R2", "R3", "R4", "pbc", "dpos", "error", "notes"]
    with (OUT / "matrix.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    (OUT / "matrix.json").write_text(json.dumps(dict(meta=meta, rows=rows), indent=1, default=str))

    # --- restart ---
    print("building endpoints", flush=True)
    eps = rf.endpoints()
    ref = rf.run(rf.make_band(eps))
    print(f"uninterrupted steps={ref['step']} barrier={ref['barrier']:.9f}", flush=True)
    rows_r = [dict(route="uninterrupted", steps=ref["step"], converged=ref["converged"],
                   barrier_eV=f"{ref['barrier']:.9f}", d_barrier_eV="0", max_disp_A="0",
                   file_dpos_A="", free_modes_mid=rf.free_modes(rf.make_band(eps)[3]), error="", notes="")]
    bands_dir = OUT / "bands"
    bands_dir.mkdir(exist_ok=True)

    def dump(slug, res):
        np.savez(bands_dir / f"{slug}.npz", pos=np.array(res["pos"]), energies=np.array(res["energies"]),
                 forces=np.array(res["forces"]), numbers=eps[0].numbers, cell=eps[0].cell.array)

    def slug(name):
        return "".join(c if c.isalnum() else "_" for c in name).strip("_")

    dump("uninterrupted", ref)
    bands = {"uninterrupted": ref["energies"]}

    def add_route(name, fn, notes=""):
        imgs = rf.make_band(eps)
        part = rf.run(imgs, stop=rf.K)
        row = dict(route=name, notes=notes)
        try:
            with tempfile.TemporaryDirectory() as td:
                back = fn(imgs, Path(td))
            fm_ = rf.free_modes(back[3])
            fdp = max(float(np.abs(b.get_positions() - a.get_positions()).max()) for a, b in zip(imgs, back))
            res = rf.run(back, start=part["step"])
            disp = max(float(np.abs(a - b).max()) for a, b in zip(res["pos"], ref["pos"]))
            row.update(steps=res["step"], converged=res["converged"], barrier_eV=f"{res['barrier']:.9f}",
                       d_barrier_eV=f"{res['barrier'] - ref['barrier']:.2e}", max_disp_A=f"{disp:.2e}",
                       file_dpos_A=f"{fdp:.1e}", free_modes_mid=fm_, error="")
            bands[name] = res["energies"]
            dump(slug(name), res)
        except BaseException as e:
            row.update(steps="", converged="", barrier_eV="", d_barrier_eV="", max_disp_A="",
                       file_dpos_A="", free_modes_mid="", error=f"{type(e).__name__}: {e}"[:300])
        rows_r.append(row)
        print(row["route"], row.get("barrier_eV"), row.get("error", "")[:120], flush=True)

    for name, fn in rf.ROUTES:
        add_route(name, fn)

    def with_ids(imgs):
        out = []
        for im in imgs:
            a = im.copy()
            a.set_array("id", np.array([17 + 3 * i for i in range(len(a))], dtype=np.int64))
            out.append(a)
        return out

    def traj_ids(imgs, d):
        import ase.io
        tagged = with_ids(imgs)
        out = []
        survived = []
        for i, im in enumerate(tagged):
            p = d / f"img{i}.traj"
            ase.io.write(str(p), im, format="traj")
            back = ase.io.read(str(p), format="traj")
            got = back.arrays.get("id")
            survived.append(got is not None and np.array_equal(np.asarray(got), im.arrays["id"]))
            out.append(back)
        traj_ids.survived = all(survived)
        return out

    add_route("ASE trajectory, id array", traj_ids,
              notes="id survived" if False else "")
    # fill the note from the closure after the call
    if rows_r[-1]["route"] == "ASE trajectory, id array" and not rows_r[-1]["error"]:
        rows_r[-1]["notes"] = "id array survived the traj round trip" if getattr(traj_ids, "survived", False) else "id array did not survive the traj round trip; FixCartesian is whatever free_modes_mid shows"

    def cross(wr, rd):
        def go(imgs, d):
            frames = [frame_from_atoms(im, i) for i, im in enumerate(imgs)]
            bridge.write(wr, frames, d)
            got = bridge.read(rd, d)
            return [ase_from_frame(fr, im) for fr, im in zip(got, imgs)]
        return go

    for wr in langs:
        for rdn in langs:
            add_route(f"CON 3.1 {wr} to {rdn}", cross(wr, rdn),
                      notes=("Fortran writes through builder%add_atom"
                             if wr == "Fortran" else "cross-binding"))

    def h5_route(writer, reader):
        def go(imgs, d):
            return h5_roundtrip(writer, reader, imgs)
        return go

    add_route("H5MD MDAnalysis to MDAnalysis", h5_route(w_mda_convention, fm.r_mda("H5MD")),
              notes="writer then h5py attaches fixed, id, and boundary; MDAnalysis reader ignores fixed and id")
    add_route("H5MD MDAnalysis to h5py", h5_route(w_mda_convention, r_h5py),
              notes="fixed is by convention")
    add_route("H5MD h5py to h5py", h5_route(w_h5py, r_h5py),
              notes="fixed is by convention; id, unit and boundary follow H5MD")
    add_route("H5MD h5py to MDAnalysis", h5_route(w_h5py, fm.r_mda("H5MD")),
              notes="MDAnalysis reader ignores fixed and id")

    rfields = ["route", "steps", "converged", "barrier_eV", "d_barrier_eV", "max_disp_A",
               "file_dpos_A", "free_modes_mid", "error", "notes"]
    with (OUT / "restart_formats.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rfields); w.writeheader()
        for r in rows_r:
            w.writerow({k: r.get(k, "") for k in rfields})
    (OUT / "restart_bands.json").write_text(json.dumps(bands, indent=1))

    # Regenerated tables and figure, written only under cloud-runs-2.
    import gen_failure_tables as g
    g.D = OUT
    g.OUT = OUT / "tables"
    g.OUT.mkdir(exist_ok=True)
    # survey() reads matrix.csv from D. Our matrix has a notes column; DictReader is fine.
    # R5 lookup misses nothing for CON 3.1 / H5MD / ASE trajectory.
    try:
        g.survey()
        g.restart()
    except Exception as e:
        (OUT / "tables" / "error.txt").write_text(traceback.format_exc())
        print("table generation failed", e, flush=True)
    try:
        import plot_restart_formats as prf
        import plot_figures as pf
        prf.BANDS = bands_dir
        pf.OUT = OUT / "figures"
        pf.OUT.mkdir(exist_ok=True)
        prf.main()
    except Exception as e:
        (OUT / "figures_error.txt").write_text(traceback.format_exc())
        print("figure failed", e, flush=True)
    print("spec 05 done", flush=True)


if __name__ == "__main__":
    main()
