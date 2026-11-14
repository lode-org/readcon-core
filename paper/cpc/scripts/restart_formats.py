#!/usr/bin/env python3
"""Interrupted climbing-image band, resumed through each format.

EMT Pt(100) slab (3x3x3, bottom layer held on every axis) with one adatom held
in z, hopping between neighbouring hollows. The band has five movable images
and uses the improved tangent with a climbing image. The optimiser is fixed-step
steepest descent on the projected NEB force. It stores no history, and every
force evaluation gets fresh EMT calculators, so a band's next step depends on
its positions alone: any difference after a resume comes from the file and from
nothing else, and a file that keeps every bit resumes to the uninterrupted band
bit for bit. The kernels are those of numeric_pins.

The uninterrupted band runs to a maximum NEB force of 0.01 eV/A. The
interrupted band stops at step K, writes every image with one writer, reads
the images back with the matching reader (constraints, if any, are whatever the
reader returns), and continues under the same rule.

Before the write every image gets the persistent ids atom_ids(n), which are not
the row order, in the carrier its route has for them. The kept column is what
the read returns of the per-axis mask, those ids and the periodic flags, and
the version the written file carries, read back from the file.

The cell is orthogonal, so FixScaled with the same mask is the same constraint
as the Cartesian z hold; the POSCAR route writes the hold as FixScaled.

A route is named H5MD only if every file it writes has the H5MD root group with
its version, and it says private when the files add a particle element H5MD
does not define (failure_matrix.h5md_layout).

Writes data/failure/restart_formats.csv, its record restart_formats.json,
data/failure/restart_bands.json and data/failure/bands/*.npz. A route that
fails, a missing module included, exits 1 before an output is touched.

    restart_formats.py --kernels NAME

reruns the uninterrupted band and every route on the kernel set NAME of
numeric_pins and writes only data/failure/restart_kernels/NAME.json, the steps
and the residues of every route at full precision.
"""

from __future__ import annotations
import csv
import io
import json
import os
import re
import shutil
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
KERNELS = (
    sys.argv[sys.argv.index("--kernels") + 1] if "--kernels" in sys.argv[1:-1] else None
)
if KERNELS is not None:
    os.environ["RC_KERNELS"] = KERNELS
import numeric_pins  # noqa: E402


_repo = next(
    _p for _p in Path(__file__).resolve().parents if (_p / "readcon_bench.py").is_file()
)
__import__("sys").path.insert(0, str(_repo))
_BENCH = __import__("readcon_bench")
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "failure"
# ASE 3.29.0 Optimizer.run defaults to fmax=0.05
# (ase/optimize/optimize.py). The band tolerance is that default divided
# by the five movable images, and the endpoint tolerance is the band
# tolerance divided by five again. Both quotients are exact in binary64.
# fcc100 leaves the slab periodic in x and y only. vacuum=None leaves a
# zero z edge, and the restart files need a three-dimensional cell, so the
# vacuum is the deposited 6.0 angstrom. The height 1.75 angstrom is the
# deposited hold. ALPHA is the fixed steepest-descent step in A^2/eV.
# The band has no line search. At FMAX the step moves an atom by ALPHA*FMAX.
# The interrupt is step 25 and the cap is 4000. The spring and the tangent
# are the ASE 3.29.0 NEB defaults (ase/mep/neb.py: k=0.1, method improvedtangent).
ASE_DEFAULT_FMAX = 0.05
N_IMG = 5
FMAX = 0.01
ENDPOINT_FMAX = FMAX / N_IMG
assert FMAX == ASE_DEFAULT_FMAX / N_IMG
assert ENDPOINT_FMAX == 0.002
ALPHA = 0.02
K = 25
NMAX = 4000
SPRING, METHOD, CLIMB = 0.1, "improvedtangent", True
VACUUM = 6.0
HEIGHT = 1.75
SITES = ((0, 0), (1, 0))


def roundoff_host():
    """CPU, kernel and numerical stack of this process: the residues at roundoff scale depend on them."""
    import platform
    import threadpoolctl

    np.linalg.eigh(np.eye(2))  # threadpoolctl lists a BLAS only once it is loaded
    cpu = {}
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        key, _, value = line.partition(":")
        cpu.setdefault(key.strip(), value.strip())
    conda = {}
    for meta in sorted((Path(sys.prefix) / "conda-meta").glob("*.json")):
        pkg = json.loads(meta.read_text())
        if pkg.get("name") in ("numpy", "libblas", "liblapack", "libopenblas", "mkl"):
            conda[pkg["name"]] = f"{pkg['version']} {pkg['build']}"
    blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
    return {
        "cpu_model": __import__("provenance").normalize_cpu(
            cpu.get("model name") or ""
        ),
        "family": cpu.get("cpu family"),
        "model": cpu.get("model"),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "numpy_blas_build": f"{blas['name']} {blas['version']}",
        "conda_packages": conda,
        "blas_runtime": [
            f"{i['internal_api']} {i['version']}, {i.get('threading_layer')}, {i.get('architecture')} kernels"
            for i in threadpoolctl.threadpool_info()
            if i["user_api"] == "blas"
        ],
        "numeric_pins": numeric_pins.in_effect(),
    }


def host_label(cpu_model, family, model):
    """TeX name of a recorded CPU: the model name as the host prints it, in typewriter type, then its family
    and model."""
    name = re.sub(r"([&%$#_{}])", r"\\\1", cpu_model)
    return f"\\texttt{{{name}}}, family~{family}, model~{model}"


def slab(site=(0, 0), height=HEIGHT, hold=True):
    from ase.build import fcc100, add_adsorbate
    from ase.constraints import FixAtoms, FixCartesian

    s = fcc100("Pt", (3, 3, 3), vacuum=VACUUM)
    a0 = s.cell[0, 0] / 3
    add_adsorbate(
        s, "Pt", height, position=((0.5 + site[0]) * a0, (0.5 + site[1]) * a0)
    )
    n = len(s)
    bottom = [i for i, t in enumerate(s.get_tags()) if t == 3]
    held = [FixCartesian(n - 1, mask=(False, False, True))] if hold else []
    s.set_constraint([FixAtoms(indices=bottom)] + held)
    return s


def endpoints(height=HEIGHT, hold=True):
    from ase.calculators.emt import EMT
    from ase.optimize import BFGS

    eps = []
    for site in SITES:
        s = slab(site, height, hold)
        s.calc = EMT()
        BFGS(s, logfile=None).run(fmax=ENDPOINT_FMAX)
        eps.append(s)
    return eps


def make_band(eps, nimg=5):
    from ase.mep import NEB
    from ase.calculators.emt import EMT

    imgs = [eps[0].copy()] + [eps[0].copy() for _ in range(nimg)] + [eps[1].copy()]
    for im in imgs:
        im.calc = EMT()
    neb = NEB(imgs, k=SPRING, climb=CLIMB, method=METHOD)
    neb.interpolate(apply_constraint=True)
    return imgs


def run(imgs, start=0, stop=None):
    from ase.mep import NEB
    from ase.calculators.emt import EMT

    neb = NEB(imgs, k=SPRING, climb=CLIMB, method=METHOD)
    step, calls = start, 0
    while True:
        # An EMT neighbour list built at an earlier step orders the sums differently from one built now.
        for im in imgs:
            im.calc = EMT()
        f = neb.get_forces()
        calls += 1
        fmax = float(np.sqrt((f**2).sum(axis=1)).max())
        if fmax < FMAX or step >= NMAX or (stop is not None and step >= stop):
            break
        neb.set_positions(neb.get_positions() + ALPHA * f)
        step += 1
    e = np.array([im.get_potential_energy() for im in imgs])
    frc = [im.get_forces(apply_constraint=False).copy() for im in imgs]
    return dict(
        step=step,
        calls=calls,
        fmax=fmax,
        barrier=float(e.max() - e[0]),
        converged=bool(fmax < FMAX),
        pos=[im.get_positions().copy() for im in imgs],
        energies=e.tolist(),
        forces=frc,
        fixed=np.array([fixed_mask(im) for im in imgs]),
        numbers=imgs[0].numbers.copy(),
        cell=imgs[0].cell.array.copy(),
        pbc=imgs[0].pbc.copy(),
    )


def fixed_mask(atoms):
    """Per-atom, per-axis True where the constraints hold the coordinate."""
    from ase.constraints import FixAtoms, FixCartesian, FixScaled

    m = np.zeros((len(atoms), 3), bool)
    for c in atoms.constraints:
        if isinstance(c, FixAtoms):
            m[c.index] = True
        elif isinstance(c, FixCartesian):
            m[c.index] |= np.asarray(c.mask, bool)
        elif isinstance(c, FixScaled):
            cell = atoms.cell.array
            if np.count_nonzero(cell - np.diag(np.diag(cell))):
                raise ValueError(
                    "FixScaled axes are not the Cartesian axes in this cell"
                )
            m[c.index] |= np.asarray(c.mask, bool)
        else:
            raise ValueError(f"unhandled constraint {c!r}")
    return m


def free_modes(atoms):
    return int((~fixed_mask(atoms)).sum())


def largest_shift(a, b):
    """Largest |b - a|, the coordinate of a it hit, and that change in ULPs of the coordinate."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = np.abs(b - a)
    k = np.unravel_index(int(d.argmax()), d.shape)
    if d[k] == 0.0:
        return 0.0, "", ""
    x = float(a[k])
    return float(d[k]), f"{x:.6g}", f"{d[k] / np.spacing(abs(x)):.3g}"


def atom_ids(n):
    return 17 + 3 * np.arange(n)


def with_ids(imgs):
    """The images with the persistent ids atom_ids(n) as the ASE id array, set in place."""
    for im in imgs:
        im.set_array("id", atom_ids(len(im)))
    return imgs


def con_atoms(im):
    """A copy readcon's from_ase gives the id array as column 5 (row order without one)."""
    a = im.copy()
    a.set_tags(0)  # slab tags are layer numbers
    if "id" in a.arrays:
        a.set_array("atom_id", a.arrays["id"].astype(np.uint64))
    return a


def con_frame(readcon, im):
    """The CON 3.1 frame of an image; from_ase stamps the library's own minor (2 from readcon-core 0.17.4)."""
    f = readcon.ConFrame.from_ase(con_atoms(im))
    f.metadata = dict(f.metadata, con_spec_version=3, con_spec_minor=1)
    return f


def _frame(readcon, im, i):
    f = con_frame(readcon, im)
    # A non-empty first line: readcon-core 0.17.0 cannot re-read a multi-frame
    # file whose frames start with an empty line (reported separately).
    return readcon.ConFrame(
        f.cell,
        f.angles,
        f.atoms,
        prebox_header=[f"NEB image {i}", ""],
        metadata=dict(f.metadata),
    )


# writer/reader pairs; each returns a list of ASE Atoms
def via_readcon(imgs, d):
    import readcon

    frames = [_frame(readcon, im, i) for i, im in enumerate(imgs)]
    p = d / "band.con"
    readcon.write_con(str(p), frames)
    return [f.to_ase() for f in readcon.read_con(str(p))]


def via_readcon_6dp(imgs, d):
    import readcon

    frames = [_frame(readcon, im, i) for i, im in enumerate(imgs)]
    p = d / "band6.con"
    readcon.write_con(str(p), frames, precision=6)
    return [f.to_ase() for f in readcon.read_con(str(p))]


def via_ase(fmt, ext):
    def go(imgs, d):
        import ase.io

        out = []
        for i, im in enumerate(imgs):
            p = d / f"img{i}.{ext}"
            ase.io.write(str(p), im, format=fmt)
            out.append(ase.io.read(str(p), format=fmt))
        return out

    return go


def with_tag_ids(im):
    a = im.copy()
    a.set_tags(atom_ids(len(a)))
    return a


def via_traj_tags(imgs, d):
    return via_ase("traj", "traj")([with_tag_ids(im) for im in imgs], d)


def fix_scaled(im):
    from ase.constraints import FixCartesian, FixScaled

    a = im.copy()
    a.set_constraint(
        [
            FixScaled(c.index, c.mask) if isinstance(c, FixCartesian) else c
            for c in a.constraints
        ]
    )
    return a


def via_poscar_scaled(imgs, d):
    return via_ase("vasp", "vasp")([fix_scaled(im) for im in imgs], d)


def via_h5md_private_mask(imgs, d):
    sys.path.insert(0, str(ROOT / "data" / "cloud-runs-2" / "cloud-run"))
    import run_05

    def write(fx, path):
        run_05.w_h5py(fx, path)
        shutil.copy(path, d / path.name)  # the round trip runs in its own directory

    return run_05.h5_roundtrip(write, run_05.r_h5py, imgs)


def poscar_flags(convert):
    """Selective-dynamics flags the ASE writer emits for the adatom (the last row)."""

    def go(imgs, back, d):
        import ase.io

        buf = io.StringIO()
        ase.io.write(buf, convert(imgs[0]), format="vasp")
        return "adatom written " + " ".join(
            buf.getvalue().splitlines()[-1].split()[3:6]
        )

    return go


def h5md_private(imgs, back, d):
    import failure_matrix as fm

    private = sorted({k for p in d.glob("*.h5md") for k in fm.h5md_layout(p)[1]})
    return f"{', '.join(private)} is not an H5MD element, so only a reader that knows this layout gets the mask back"


def file_version(d):
    """The version the first file of the route carries, read back from the file ("none" without one)."""
    import failure_matrix as fm

    path = min(d.iterdir())
    return fm.version_carried(
        {".con": "CON", ".traj": "ASE trajectory", ".h5md": "H5MD"}.get(
            path.suffix, ""
        ),
        path,
    )


def kept(imgs, back):
    """Which of the per-axis mask, the persistent ids and the periodic flags the read returns for every image."""
    ids = atom_ids(len(imgs[0]))

    def carriers(b):
        return (b.arrays.get("atom_id"), b.arrays.get("id"), b.get_tags())

    got = {
        "mask": all(
            np.array_equal(fixed_mask(a), fixed_mask(b)) for a, b in zip(imgs, back)
        ),
        "ids": all(
            any(
                c is not None and np.array_equal(np.asarray(c), ids)
                for c in carriers(b)
            )
            for b in back
        ),
        "pbc": all(np.array_equal(a.pbc, b.pbc) for a, b in zip(imgs, back)),
    }
    return " ".join(k for k, v in got.items() if v)


def h5md_named(name, d):
    """Raise unless the route says H5MD exactly when it wrote H5MD files, and private exactly when they add an element."""
    import failure_matrix as fm

    files = sorted(d.glob("*.h5md"))
    if ("H5MD" in name) != bool(files):
        raise ValueError(
            f"{name}: the name says H5MD but the route wrote {len(files)} .h5md files"
        )
    for p in files:
        version, private = fm.h5md_layout(p)
        if version is None:
            raise ValueError(f"{name}: {p.name} has no H5MD root group with a version")
        if bool(private) != ("private" in name):
            raise ValueError(f"{name}: {p.name} holds the private elements {private}")


FAILS_AS = {}
ROUTES = [
    ("CON 3.1, shortest round trip", via_readcon),
    ("CON 3.1, six decimals", via_readcon_6dp),
    ("extended XYZ (ASE)", via_ase("extxyz", "xyz")),
    ("ASE trajectory, ids in tags", via_traj_tags),
    ("POSCAR (ASE), FixScaled z", via_poscar_scaled),
    ("H5MD (h5py), private mask dataset", via_h5md_private_mask),
]
NOTES = {
    "POSCAR (ASE), FixScaled z": poscar_flags(fix_scaled),
    "H5MD (h5py), private mask dataset": h5md_private,
}
FIELDS = [
    "route",
    "steps",
    "converged",
    "barrier_eV",
    "d_barrier_eV",
    "d_barrier_ulp",
    "max_disp_A",
    "max_disp_coord_A",
    "max_disp_ulp",
    "file_dpos_A",
    "file_dpos_coord_A",
    "file_dpos_ulp",
    "free_modes_mid",
    "force_calls",
    "kept",
    "file_version",
    "error",
    "notes",
]
COLUMNS = {
    "barrier_eV": "highest image energy minus the first image energy of the final band",
    "d_barrier_eV": "barrier_eV minus the uninterrupted barrier_eV",
    "d_barrier_ulp": "d_barrier_eV in ULPs of the uninterrupted highest image energy",
    "max_disp_A": "largest coordinate difference between the final band and the uninterrupted final band",
    "max_disp_coord_A": "the uninterrupted coordinate at that largest difference",
    "max_disp_ulp": "max_disp_A in ULPs of that coordinate",
    "file_dpos_A": "largest coordinate change across the write and the read at step K",
    "file_dpos_coord_A": "the written coordinate at that largest change",
    "file_dpos_ulp": "file_dpos_A in ULPs of that coordinate",
    "free_modes_mid": "free Cartesian degrees of freedom of the middle image after the read",
    "force_calls": "NEB get_forces evaluations of the resumed leg (of the whole band when uninterrupted)",
    "kept": "of mask (per-axis constraints), ids (atom_ids, through the route's carrier) and pbc, those the read "
    "returns equal on every image",
    "file_version": "the version the route's first written file carries, read back from the file",
}


def resume(name, fn, eps, ref):
    """Interrupt at K, round-trip through fn, resume; the row fields and the resumed band."""
    imgs = make_band(eps)
    part = run(imgs, stop=K)
    with bench_scratch("scratch") as td:
        d = Path(td)
        back = fn(with_ids(imgs), d)
        h5md_named(name, d)
        version = file_version(d)
        note = NOTES.get(name, lambda i, b, d: "")(imgs, back, d)
    dpos, coord, ulp = largest_shift(
        [im.get_positions() for im in imgs], [im.get_positions() for im in back]
    )
    fm = free_modes(back[3])
    keeps = kept(imgs, back)
    res = run(back, start=part["step"])
    disp, dcoord, dulp = largest_shift(ref["pos"], res["pos"])
    de = res["barrier"] - ref["barrier"]
    res["full"] = {"file_dpos_A": dpos, "d_barrier_eV": float(de), "max_disp_A": disp}
    row = dict(
        route=name,
        steps=res["step"],
        converged=res["converged"],
        barrier_eV=f"{res['barrier']:.9f}",
        d_barrier_eV=f"{de:.2e}",
        d_barrier_ulp=f"{de / np.spacing(max(ref['energies'])):.3g}",
        max_disp_A=f"{disp:.2e}",
        max_disp_coord_A=dcoord,
        max_disp_ulp=dulp,
        file_dpos_A=f"{dpos:.2e}",
        file_dpos_coord_A=coord,
        file_dpos_ulp=ulp,
        free_modes_mid=fm,
        force_calls=res["calls"],
        kept=keeps,
        file_version=version,
        error="",
        notes=note,
    )
    return row, res


def unexpected(rows):
    """Rows that end with an error."""
    return [f"{r['route']}: {r['error']}" for r in rows if r["error"]]


def main():
    sys.path.insert(0, str(ROOT / "scripts"))
    import provenance

    OUT.mkdir(parents=True, exist_ok=True)
    eps = endpoints()
    ref = run(make_band(eps))
    print(
        f"uninterrupted: steps={ref['step']} barrier={ref['barrier']:.9f} fmax={ref['fmax']:.4f}"
    )
    rows = [
        {
            **{k: "" for k in FIELDS},
            "route": "uninterrupted",
            "steps": ref["step"],
            "converged": ref["converged"],
            "barrier_eV": f"{ref['barrier']:.9f}",
            "d_barrier_eV": "0",
            "max_disp_A": "0",
            "free_modes_mid": free_modes(make_band(eps)[3]),
            "force_calls": ref["calls"],
        }
    ]
    results = {"uninterrupted": ref}
    for name, fn in ROUTES:
        try:
            row, res = resume(name, fn, eps, ref)
            rows.append(row)
            results[name] = res
        except BaseException as e:
            rows.append(
                {
                    **{k: "" for k in FIELDS},
                    "route": name,
                    "error": f"{type(e).__name__}: {e}"[:120],
                }
            )
        print(rows[-1])
    bad = unexpected(rows)
    if bad:
        print(
            "routes ended with an error; no output written:",
            *bad,
            sep="\n  ",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if KERNELS is not None:
        (OUT / "restart_kernels").mkdir(exist_ok=True)
        (OUT / "restart_kernels" / f"{KERNELS}.json").write_text(
            json.dumps(
                {
                    "script": "paper/cpc/scripts/restart_formats.py",
                    "kernel_set": KERNELS,
                    "uninterrupted": {
                        "steps": ref["step"],
                        "converged": ref["converged"],
                        "barrier_eV": ref["barrier"],
                    },
                    "routes": {
                        name: {
                            "steps": results[name]["step"],
                            "converged": results[name]["converged"],
                            "barrier_eV": results[name]["barrier"],
                            **results[name]["full"],
                        }
                        for name, _ in ROUTES
                    },
                    "roundoff_host": roundoff_host(),
                    "provenance": provenance.record(),
                },
                indent=1,
            )
        )
        return
    BANDS = OUT / "bands"
    BANDS.mkdir(exist_ok=True)
    for old in BANDS.glob("*.npz"):
        old.unlink()
    for name, res in results.items():
        np.savez(
            BANDS
            / f"{''.join(c if c.isalnum() else '_' for c in name).strip('_')}.npz",
            pos=np.array(res["pos"]),
            energies=np.array(res["energies"]),
            forces=np.array(res["forces"]),
            numbers=eps[0].numbers,
            cell=eps[0].cell.array,
        )
    bands = {name: res["energies"] for name, res in results.items()}
    tmp = OUT / "restart_formats.csv.tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, OUT / "restart_formats.csv")
    record = provenance.record()
    host = roundoff_host()
    (OUT / "restart_bands.json").write_text(
        json.dumps(
            {"energies_eV": bands, "roundoff_host": host, "provenance": record},
            indent=1,
        )
    )
    (OUT / "restart_formats.json").write_text(
        json.dumps(
            {
                "script": "paper/cpc/scripts/restart_formats.py",
                "outputs": [
                    "data/failure/restart_formats.csv",
                    "data/failure/restart_bands.json",
                    "data/failure/bands",
                ],
                "parameters": dict(
                    fmax_eV_A=FMAX,
                    alpha_A2_eV=ALPHA,
                    interrupt_step=K,
                    step_cap=NMAX,
                    vacuum_A=VACUUM,
                    held_height_A=HEIGHT,
                    endpoint_fmax_eV_A=ENDPOINT_FMAX,
                    movable_images=N_IMG,
                    spring_eV_A2=SPRING,
                    sites=SITES,
                    neb_method=METHOD,
                    climbing_image=CLIMB,
                ),
                "atom_ids": atom_ids(len(eps[0])).tolist(),
                "columns": COLUMNS,
                "roundoff_host": host,
                "provenance": record,
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
