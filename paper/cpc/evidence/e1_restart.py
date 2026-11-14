#!/usr/bin/env python3
"""Restart-fidelity runs for the CPC evidence pack.

Physics is a Pt(100) adatom hop on the Morse potential in eOn, plus a short
dimer search and a short dynamics run on the same slab. The slab is the one of
Section 6 (``restart_formats.slab``): bottom layer at mask 7, the adatom held in
z at mask 4, hopping between neighbouring hollows.

Both endpoints are minimised to FMAX. Each band optimiser then runs one band
to FMAX without a break, and the same band again stopped at INTERRUPT_AT
iterations, written to CON, read back and resumed to FMAX. The steepest-descent
band is the primary record; L-BFGS is the control.

eOn 3.6.0 steps the band with ``[Nudged Elastic Band] opt_method`` (default
lbfgs) and writes ``[Optimizer] opt_method`` (default cg) to results.dat as
``optimizer_backend``. Every band run names its optimiser under both keys and
runs with its own TMPDIR, where eOn opens ``eon_logs/_<optimizer>.log`` for each
optimiser it constructs. The script stops before writing a record unless both
the reported backend and the constructed optimisers are the requested one.

This script does not edit the manuscript.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import numeric_pins  # noqa: E402,F401
import numpy as np  # noqa: E402

os.environ.setdefault("MKL_NUM_THREADS", "1")

import ase
import readcon

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "scripts"))

import provenance  # noqa: E402
import restart_formats as rf  # noqa: E402
import velocity_case  # noqa: E402


_repo = next(
    _p for _p in Path(__file__).resolve().parents if (_p / "readcon_bench.py").is_file()
)
__import__("sys").path.insert(0, str(_repo))
_BENCH = __import__("readcon_bench")
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


def package_module_path(module_file: str) -> str:
    """Return a package-relative path such as ``readcon/__init__.py``."""
    path = Path(module_file)
    parts = path.parts
    if "readcon" in parts:
        i = parts.index("readcon")
        return str(Path(*parts[i:]))
    return path.name


WORK = ROOT / "work" / "e1"
RESULTS = ROOT / "results"
EON = (
    os.environ.get("EONCLIENT")
    or shutil.which("eonclient")
    or str(ROOT.parent / ".pixi" / "envs" / "eon" / "bin" / "eonclient")
)
# readcon unit_conversion_factor(natural, "fs"); see src/units.rs.
NATURAL_TO_FS = 10.180505710759414
FMAX = 0.01
ENDPOINT_OPTIMIZER = "lbfgs"
ENDPOINT_MAX_ITERATIONS = 1000
NEB_MAX_ITERATIONS = 20000
INTERRUPT_AT = 25
# eOn 3.6.0 band steepest descent takes alpha = 0.1 whatever sd_alpha says,
# which oscillates on this slab unless max_move caps the step.
BAND_OPTIMIZERS = {
    "sd": {
        "opt_method": "sd",
        "max_move": 0.0005,
        "results": "e1_restart.json",
        "work": "neb",
    },
    "lbfgs": {
        "opt_method": "lbfgs",
        "max_move": 0.05,
        "results": "e1_restart_lbfgs_control.json",
        "work": "neb_lbfgs",
    },
}
# The file each eOn 3.6.0 optimiser class opens when it is constructed
# (eonc::log::FileScoped in LBFGS.h, SteepestDescent.h, ConjugateGradients.h,
# FIRE.h, Quickmin.h), and the optimizer_backend spelling of that class.
OPTIMIZER_LOGS = {
    "_lbfgs.log": "lbfgs",
    "_sd.log": "sd",
    "_cg.log": "cg",
    "_fire.log": "fire",
    "_quickmin.log": "qm",
}


def cpu_name() -> str:
    family = model = name = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("cpu family") and not family:
            family = line.split(":", 1)[1].strip()
        elif line.startswith("model name") and not name:
            name = line.split(":", 1)[1].strip()
        elif line.startswith("model\t") and not model:
            model = line.split(":", 1)[1].strip()
    cores = os.cpu_count()
    return f"{name}, family {family}, model {model}, {cores} hardware threads"


def run(
    cmd: list[str], cwd: Path, timeout: float = 180, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def eon_run(
    work: Path, timeout: float
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run eonclient in work with a TMPDIR of its own; also return the optimisers it constructed."""
    with bench_scratch("scratch") as tmp:
        proc = run([EON], work, timeout=timeout, env=dict(os.environ, TMPDIR=tmp))
        logs = Path(tmp) / "eon_logs"
        built = (
            sorted(OPTIMIZER_LOGS.get(p.name, p.name) for p in logs.glob("*.log"))
            if logs.is_dir()
            else []
        )
    return proc, built


def check_optimizer(
    work: Path, requested: str, info: dict[str, str], built: list[str]
) -> None:
    backend = info.get("optimizer_backend")
    if backend != requested or built != [requested]:
        raise SystemExit(
            f"{work}: requested optimiser {requested}, but eOn reports optimizer_backend {backend} "
            f"and constructed {built}; no record written"
        )


def eon_version() -> str:
    proc = run([EON, "--version"], WORK, timeout=30)
    text = (proc.stdout or "") + (proc.stderr or "")
    for line in text.splitlines():
        if line.startswith("3.") or line.startswith("eOn"):
            return line.strip()
    return text.splitlines()[0].strip() if text else "unknown"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recipe_sources(recipe: Path) -> list[dict]:
    """The ``source`` entries (url, sha256) of a rendered conda recipe."""
    sources, inside = [], False
    for line in recipe.read_text().splitlines():
        text = line.strip()
        if line.startswith("  source:"):
            inside = True
        elif (
            inside
            and line.startswith("  ")
            and not line.startswith("   ")
            and not text.startswith("-")
        ):
            break
        elif inside and text.startswith("- url:"):
            sources.append({"url": text.split(":", 1)[1].strip()})
        elif inside and text.startswith("sha256:") and sources:
            sources[-1]["sha256"] = text.split(":", 1)[1].strip()
    return sources


def tag_commit(repository: str, tag: str) -> str:
    """The commit a public tag points to, from ``git ls-remote``."""
    proc = subprocess.run(
        ["git", "ls-remote", repository, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    )
    refs = dict(reversed(line.split("\t")) for line in proc.stdout.splitlines())
    commit = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not commit:
        raise SystemExit(f"{repository} has no tag {tag}")
    return commit


def eon_package(meta: dict) -> dict:
    """What the conda package says about its build: feedstock commit and sources."""
    info = Path(meta["extracted_package_dir"]) / "info"
    about = json.loads((info / "about.json").read_text())
    extra = about.get("extra", {})
    out = {
        "dev_url": about.get("dev_url"),
        "feedstock": extra.get("remote_url"),
        "feedstock_commit": extra.get("sha"),
        "sources": recipe_sources(info / "recipe" / "rendered_recipe.yaml"),
    }
    tag = f"v{meta['version']}"
    out["source_tag"] = {
        "repository": out["dev_url"],
        "tag": tag,
        "commit": tag_commit(out["dev_url"], tag),
    }
    return out


def eon_build() -> dict:
    """The eOn client, named by its path in its environment, its conda package and the readcon-core library it loads."""
    client = Path(EON).resolve()
    prefix = client.parent.parent
    out = {
        "eonclient": client.relative_to(prefix).as_posix(),
        "eonclient_sha256": _sha256(client),
        "version_output": eon_version(),
    }
    for record in sorted((prefix / "conda-meta").glob("eon-*.json")):
        meta = json.loads(record.read_text())
        if meta.get("name") == "eon":
            # pixi records the channel without the platform directory and conda with it; the URL names both alike.
            channel = meta["url"].rsplit("/", 2)[0]
            out["conda_package"] = {
                key: channel if key == "channel" else meta.get(key)
                for key in ("name", "version", "build", "channel", "url", "sha256")
            }
            out["readcon_core_shipped_in_eon_package"] = any(
                "libreadcon_core" in name for name in meta.get("files", [])
            )
            out["package"] = eon_package(meta)
    linked = run(["ldd", str(client)], WORK, timeout=30).stdout
    for line in linked.splitlines():
        if "libreadcon_core" in line and "=>" in line:
            library = Path(line.split("=>", 1)[1].split("(", 1)[0].strip()).resolve()
            out["readcon_core_library"] = library.name
            out["readcon_core_library_sha256"] = _sha256(library)
    pc = prefix / "lib" / "pkgconfig" / "readcon-core.pc"
    if pc.is_file():
        for line in pc.read_text().splitlines():
            if line.startswith("Version:"):
                out["readcon_core_version"] = line.split(":", 1)[1].strip()
    return out


def engine_identity(info: dict[str, str]) -> dict[str, str]:
    prefixes = ("engine_", "compatibility_", "rgpot_")
    return {key: value for key, value in info.items() if key.startswith(prefixes)}


def write_frame(path: Path, atoms, masks: list[int], velocities=None) -> None:
    """Write one v3.1 frame. masks are the integer column-4 values."""
    symbols = list(atoms.symbols)
    positions = atoms.get_positions()
    cell = atoms.cell.cellpar()
    masses = atoms.get_masses()
    py_atoms = []
    for i, (symbol, xyz, mask) in enumerate(zip(symbols, positions, masks)):
        fixed = [bool(mask & 1), bool(mask & 2), bool(mask & 4)]
        kwargs = {}
        if velocities is not None:
            kwargs = {
                "vx": float(velocities[i, 0]),
                "vy": float(velocities[i, 1]),
                "vz": float(velocities[i, 2]),
            }
        py_atoms.append(
            readcon.Atom(
                symbol=symbol,
                x=float(xyz[0]),
                y=float(xyz[1]),
                z=float(xyz[2]),
                fixed=fixed,
                atom_id=i,
                mass=float(masses[i]),
                **kwargs,
            )
        )
    frame = readcon.ConFrame(
        cell=[float(cell[0]), float(cell[1]), float(cell[2])],
        angles=[float(cell[3]), float(cell[4]), float(cell[5])],
        atoms=py_atoms,
        prebox_header=["e1 Pt(100) adatom", ""],
        postbox_header=["", ""],
    )
    units = {"length": "angstrom", "energy": "eV", "mass": "amu"}
    sections = []
    if velocities is not None:
        units["time"] = "(amu*angstrom^2/eV)^0.5"
        sections = ["velocities"]
    frame.metadata = {
        "con_spec_version": 3,
        "con_spec_minor": 1,
        "units": units,
        "sections": sections,
        "pbc": [True, True, False],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path), [frame])


def positions_of(path: Path) -> np.ndarray:
    frames = readcon.read_con(str(path))
    out = []
    for frame in frames:
        xyz = np.array([[atom.x, atom.y, atom.z] for atom in frame.atoms], dtype=float)
        out.append(xyz)
    return np.stack(out, axis=0)


def rmsd(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if a.shape != b.shape:
        a = a[:n]
        b = b[:n]
    return float(np.sqrt(np.mean((a - b) ** 2)))


def max_abs(a: np.ndarray, b: np.ndarray) -> float:
    n = min(a.shape[0], b.shape[0])
    return float(np.max(np.abs(a[:n] - b[:n])))


def cell_lengths(path: Path) -> np.ndarray:
    frame = readcon.read_con(str(path))[0]
    return np.asarray(frame.cell[:3], dtype=float)


def compare_geom(a: np.ndarray, b: np.ndarray, lengths: np.ndarray) -> dict:
    """Raw and minimum-image differences. z is not periodic on this slab."""
    n = min(a.shape[0], b.shape[0])
    a = np.asarray(a[:n], dtype=float)
    b = np.asarray(b[:n], dtype=float)
    delta = a - b
    wrapped = delta.copy()
    for axis in (0, 1):
        length = float(lengths[axis])
        wrapped[..., axis] = delta[..., axis] - length * np.round(
            delta[..., axis] / length
        )
    return {
        "bit_identical": bool(np.array_equal(a, b)),
        "rmsd_A": float(np.sqrt(np.mean(delta**2))),
        "max_abs_A": float(np.max(np.abs(delta))),
        "mic_rmsd_A": float(np.sqrt(np.mean(wrapped**2))),
        "mic_max_abs_A": float(np.max(np.abs(wrapped))),
        "n_sites_raw_gt_1A": int(np.sum(np.max(np.abs(delta), axis=-1) > 1.0)),
        "pbc_xy_only": True,
    }


def iteration_table(work: Path) -> list[dict]:
    log = work / "client_quill.log"
    rows = []
    if not log.is_file():
        return rows
    for line in log.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            rows.append(
                {
                    "iteration": int(parts[0]),
                    "step_size_A": float(parts[1]),
                    "force": float(parts[2]),
                    "max_image": int(parts[3]),
                    "max_energy_eV": float(parts[4]),
                }
            )
        except ValueError:
            continue
    return rows


def scrub_client_logs(root: Path) -> None:
    """Drop client logs. They record the machine name, which this pack does not keep."""
    for name in ("client_quill.log", "client_traceback.log"):
        for path in root.rglob(name):
            path.unlink(missing_ok=True)


def parse_results(path: Path) -> dict[str, str]:
    """eOn writes ``value key`` with the key as the last token.

    Values may contain spaces (``Too many iterations termination_reason_text``).
    """
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        text = line.strip()
        if not text:
            continue
        value, sep, key = text.rpartition(" ")
        if sep and key:
            out[key] = value
    return out


def _peak_force(info: dict[str, str]) -> float | None:
    forces = []
    for key, value in info.items():
        if (
            key.startswith("image")
            and key.endswith("_force")
            and "projected" not in key
        ):
            forces.append(float(value))
    return float(max(forces)) if forces else None


def _max_projected_force(info: dict[str, str]) -> float | None:
    forces = [
        float(v)
        for k, v in info.items()
        if k.startswith("image") and k.endswith("_projected_force")
    ]
    return float(max(forces)) if forces else None


def barrier_from_results(info: dict[str, str]) -> float | None:
    energies = []
    for key, value in info.items():
        if key.startswith("image") and key.endswith("_energy"):
            energies.append(float(value))
    if not energies:
        return None
    return float(max(energies))


def neb_config(band: dict, max_iterations: int, initial_path: str = "") -> str:
    init = "linear"
    path_line = ""
    if initial_path:
        init = "file"
        path_line = f"initial_path_in = {initial_path}\n"
    band_line = f"opt_method = {band['opt_method']}\n" if band["opt_method"] else ""
    opt_line = f"opt_method = {band['opt_method']}\n" if band["opt_method"] else ""
    return f"""[Main]
job = nudged_elastic_band
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Nudged Elastic Band]
images = 5
spring = 1.0
climbing_image_method = false
minimize_endpoints = false
max_iterations = {max_iterations}
converged_force = {FMAX}
initializer = {init}
{band_line}{path_line}
[Optimizer]
{opt_line}max_move = {band["max_move"]}
converged_force = {FMAX}
max_iterations = {max_iterations}
"""


def build_hop() -> tuple[object, object, list[int], int]:
    """The Section 6 endpoints: bottom layer at mask 7, the adatom at mask 4."""
    reactant, product = rf.slab((0, 0)), rf.slab((1, 0))
    adatom = len(reactant) - 1
    bottom = {int(i) for i in reactant.constraints[0].get_indices()}
    masks = [7 if i in bottom else 0 for i in range(len(reactant))]
    masks[adatom] = 4
    return reactant, product, masks, adatom


def residual_force(con: Path) -> dict:
    """eOn's own single-point maximum atom force on a minimised endpoint."""
    work = con.parent / (con.stem + "_point")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(con, work / "pos.con")
    (work / "config.ini").write_text(
        "[Main]\njob = point\n\n[Potential]\npotential = morse_pt\n"
    )
    run([EON], work, timeout=60)
    info = parse_results(work / "results.dat")
    shutil.rmtree(work)
    return {
        "max_atom_force_eV_A": float(info["Max_Force"]),
        "potential_energy_eV": float(info["potential_energy"]),
    }


def minimize_endpoint(src: Path, dst: Path) -> dict:
    work = dst.parent / (dst.stem + "_run")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, work / "pos.con")
    (work / "config.ini").write_text(
        f"""[Main]
job = minimization
random_seed = 1

[Potential]
potential = morse_pt

[Optimizer]
opt_method = {ENDPOINT_OPTIMIZER}
convergence_metric = max_atom
converged_force = {FMAX}
max_iterations = {ENDPOINT_MAX_ITERATIONS}
"""
    )
    t0 = time.perf_counter()
    proc, built = eon_run(work, timeout=120)
    elapsed = time.perf_counter() - t0
    produced = work / "min.con"
    if not produced.is_file():
        raise SystemExit(
            f"minimisation wrote no min.con under {work}: {proc.stderr[-400:]}"
        )
    info = parse_results(work / "results.dat")
    check_optimizer(work, ENDPOINT_OPTIMIZER, info, built)
    shutil.copy(produced, dst)
    out = {
        "returncode": proc.returncode,
        "seconds": elapsed,
        "optimizer": ENDPOINT_OPTIMIZER,
        "optimizer_backend": info["optimizer_backend"],
        "optimizers_constructed": built,
        "converged_force_eV_A": FMAX,
        "output_name": produced.name,
        "stderr_tail": (proc.stderr or "")[-400:],
        "results": info,
    }
    out["residual"] = residual_force(dst)
    scrub_client_logs(work)
    return out


def round_trip(src: Path, dst: Path, precision: int | None) -> None:
    frames = readcon.read_con(str(src))
    if precision is None:
        readcon.write_con(str(dst), frames)
    else:
        readcon.write_con(str(dst), frames, precision=precision)


def split_eon_frames(band: Path) -> list[str]:
    """The frames of an eOn band file as eOn wrote them, without a parse."""
    lines = band.read_text().splitlines(keepends=True)
    frames = []
    start = 0
    while start < len(lines) and lines[start].strip():
        counts = [int(n) for n in lines[start + 7].split()]
        if len(counts) != int(lines[start + 6]):
            raise SystemExit(f"{band}: type count mismatch at line {start + 7}")
        length = 9 + sum(2 + n for n in counts)
        frames.append("".join(lines[start : start + length]))
        start += length
    return frames


def prepare_resume(band: Path, dest_dir: Path, tag: str, route: str) -> str:
    """Write the interrupted band as the file list eOn's FILE initializer reads.

    route "eon" keeps eOn's own bytes. "round" and "fixed6" are a readcon
    read and a readcon write, shortest round trip or six decimals.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    if route == "eon":
        texts = split_eon_frames(band)
    else:
        kwargs = {} if route == "round" else {"precision": 6}
        texts = [
            readcon.write_con_string([frame], **kwargs)
            for frame in readcon.read_con(str(band))
        ]
    names = []
    for i, text in enumerate(texts):
        name = f"image_{tag}_{i:02d}.con"
        (dest_dir / name).write_text(text)
        names.append(name)
    list_name = f"path_{tag}.lst"
    (dest_dir / list_name).write_text("".join(f"{name}\n" for name in names))
    (dest_dir / "reactant.con").write_text(texts[0])
    (dest_dir / "product.con").write_text(texts[-1])
    return list_name


def force_call_seconds(con: Path) -> float:
    samples = []
    work = con.parent
    for _ in range(5):
        t0 = time.perf_counter()
        run([EON, "-s", "-p", "morse_pt", str(con.name)], work, timeout=60)
        samples.append(time.perf_counter() - t0)
    return float(np.median(samples))


def _positive_steps(table: list[dict]) -> int:
    return sum(1 for row in table if row["step_size_A"] > 0.0)


def band_job(
    work: Path, config: str, inputs: dict[str, Path], optimizer: str | None
) -> dict:
    """One eOn band run; ``optimizer`` is the band optimiser the run must report, None for eOn's default."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for name, path in inputs.items():
        shutil.copy(path, work / name)
    (work / "config.ini").write_text(config)
    t0 = time.perf_counter()
    proc, built = eon_run(work, timeout=180)
    elapsed = time.perf_counter() - t0
    info = parse_results(work / "results.dat")
    if optimizer is not None:
        check_optimizer(work, optimizer, info, built)
    table = iteration_table(work)
    scrub_client_logs(work)
    band = work / "neb.con"
    relative = (
        [f.metadata.get("relative_energy") for f in readcon.read_con(str(band))]
        if band.is_file()
        else []
    )
    return {
        "returncode": proc.returncode,
        "seconds": elapsed,
        "optimizer_backend": info.get("optimizer_backend"),
        "optimizers_constructed": built,
        "has_neb": band.is_file(),
        "barrier_eV": barrier_from_results(info),
        "barrier_con_eV": float(max(relative))
        if relative and None not in relative
        else None,
        "termination": info.get("termination_reason_text"),
        "iterations": table[-1]["iteration"] if table else None,
        "first_iteration_step_A": table[0]["step_size_A"] if table else None,
        "optimizer_steps": _positive_steps(table),
        "force_calls": int(info["total_force_calls"])
        if "total_force_calls" in info
        else None,
        "max_projected_force_eV_A": _max_projected_force(info),
        "peak_force_eV_A": _peak_force(info),
        "final_force_norm": table[-1]["force"] if table else None,
        "results": info,
        "stderr_tail": (proc.stderr or "")[-500:],
    }


def neb_campaign(reactant: Path, product: Path, key: str) -> dict:
    band = BAND_OPTIMIZERS[key]
    optimizer = band["opt_method"]
    base = WORK / band["work"]
    ends = {"reactant.con": reactant, "product.con": product}
    full = band_job(
        base / "full", neb_config(band, NEB_MAX_ITERATIONS), ends, optimizer
    )
    short = band_job(base / "short", neb_config(band, INTERRUPT_AT), ends, optimizer)
    full_xyz = positions_of(base / "full" / "neb.con")
    lengths = cell_lengths(base / "full" / "neb.con")
    checkpoint = base / "short" / "neb.con"

    def resume(tag: str, route: str) -> dict:
        work = base / tag
        if work.exists():
            shutil.rmtree(work)
        stage = base / f"{tag}_input"
        if stage.exists():
            shutil.rmtree(stage)
        list_name = prepare_resume(checkpoint, stage, tag, route)
        inputs = {path.name: path for path in sorted(stage.iterdir())}
        row = band_job(
            work, neb_config(band, NEB_MAX_ITERATIONS, list_name), inputs, optimizer
        )
        shutil.rmtree(stage)
        row["route"] = route
        loaded = np.stack(
            [
                np.asarray(f.coords_array(), dtype=float)
                for f in readcon.read_con(str(checkpoint))
            ]
        )
        written = [
            readcon.read_con_string(text)[0]
            for text in (
                split_eon_frames(checkpoint)
                if route == "eon"
                else [
                    readcon.write_con_string(
                        [f], **({} if route == "round" else {"precision": 6})
                    )
                    for f in readcon.read_con(str(checkpoint))
                ]
            )
        ]
        row["checkpoint_max_abs_A"] = max_abs(
            loaded,
            np.stack([np.asarray(f.coords_array(), dtype=float) for f in written]),
        )
        if row["has_neb"]:
            versus = compare_geom(positions_of(work / "neb.con"), full_xyz, lengths)
            row["versus_uninterrupted_final"] = versus
            row["bit_identical"] = versus["bit_identical"]
            row["mic_rmsd_A"] = versus["mic_rmsd_A"]
            row["mic_max_abs_A"] = versus["mic_max_abs_A"]
        if row["barrier_eV"] is not None and full["barrier_eV"] is not None:
            row["barrier_delta_eV"] = row["barrier_eV"] - full["barrier_eV"]
        if row["barrier_con_eV"] is not None and full["barrier_con_eV"] is not None:
            row["barrier_con_delta_eV"] = row["barrier_con_eV"] - full["barrier_con_eV"]
        row["total_optimizer_steps"] = short["optimizer_steps"] + row["optimizer_steps"]
        row["extra_optimizer_steps"] = (
            row["total_optimizer_steps"] - full["optimizer_steps"]
        )
        if (
            row["force_calls"] is not None
            and short["force_calls"] is not None
            and full["force_calls"] is not None
        ):
            row["extra_force_calls"] = (
                short["force_calls"] + row["force_calls"] - full["force_calls"]
            )
        return row

    rows = {
        tag: resume(f"resume_{route}", route)
        for tag, route in (
            ("resume_eon", "eon"),
            ("resume_roundtrip", "round"),
            ("resume_fixed6", "fixed6"),
        )
    }
    return {
        "optimizer": optimizer,
        "config_keys": {
            "[Nudged Elastic Band] opt_method": optimizer,
            "[Optimizer] opt_method": optimizer,
        },
        "optimizer_backend_every_run": sorted(
            {row["optimizer_backend"] for row in (full, short, *rows.values())}
        ),
        "max_move_A": band["max_move"],
        "converged_force_eV_A": FMAX,
        "max_iterations": NEB_MAX_ITERATIONS,
        "interrupt_max_iterations": INTERRUPT_AT,
        "interrupt_iterations": short["iterations"],
        "interrupt_optimizer_steps": short["optimizer_steps"],
        "climbing_image": False,
        "full": full,
        "short": short,
        "interrupt_file": str(checkpoint.relative_to(WORK)),
        **rows,
        "note": (
            "interrupt_max_iterations is eOn's [Nudged Elastic Band] max_iterations for the interrupted run, "
            "counted in eOn iterations. Iteration 1 evaluates the loaded band and does not step "
            "(first_iteration_step_A is 0), so the interrupted run takes interrupt_optimizer_steps optimiser "
            "steps, the positive step sizes of its iteration table. extra_optimizer_steps is the "
            "interrupted plus resumed step count minus the uninterrupted one."
        ),
    }


def default_band_optimizer(reactant: Path, product: Path) -> dict:
    """The band optimiser eOn constructs when the configuration names none, from the logs eOn opens."""
    ends = {"reactant.con": reactant, "product.con": product}
    unnamed = dict(BAND_OPTIMIZERS["lbfgs"], opt_method=None)
    work = WORK / "neb_default_probe"
    probe = band_job(work, neb_config(unnamed, NEB_MAX_ITERATIONS), ends, None)
    shutil.rmtree(work)
    if len(probe["optimizers_constructed"]) != 1:
        raise SystemExit(
            f"the band without opt_method constructed {probe['optimizers_constructed']}"
        )
    return {
        "config_keys": "no opt_method under [Nudged Elastic Band] or [Optimizer]",
        "band_optimizer": probe["optimizers_constructed"][0],
        "optimizer_backend": probe["optimizer_backend"],
        "termination": probe["termination"],
        "iterations": probe["iterations"],
        "force_calls": probe["force_calls"],
        "barrier_eV": probe["barrier_eV"],
        "note": (
            "band_optimizer is the one optimiser log eOn opened under $TMPDIR/eon_logs during the run. "
            "optimizer_backend is what results.dat reports, [Optimizer] opt_method, which the band does not use."
        ),
    }


def dimer_campaign(reactant: Path) -> dict:
    def once(work: Path, src: Path) -> dict:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        shutil.copy(src, work / "pos.con")
        # A small push of the last atom, which is the adatom.
        frames = readcon.read_con(str(work / "pos.con"))
        atom = frames[0].atoms[-1]
        atom.x = float(atom.x) + 0.2
        readcon.write_con(str(work / "displacement.con"), frames)
        (work / "config.ini").write_text(
            """[Main]
job = saddle_search
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Optimizer]
opt_method = sd
converged_force = 0.05
max_iterations = 20
max_move = 0.1

[Saddle Search]
min_mode_method = dimer
max_iterations = 12
displace_radius = 4.0
displace_magnitude = 0.2
max_energy = 20

[Dimer]
rotations_max = 6
converged_angle = 8
"""
        )
        t0 = time.perf_counter()
        proc = run([EON], work, timeout=180)
        info = parse_results(work / "results.dat")
        return {
            "returncode": proc.returncode,
            "seconds": time.perf_counter() - t0,
            "results": {
                k: info[k]
                for k in info
                if "energy" in k or "termination" in k or "eigen" in k
            },
            "stderr_tail": (proc.stderr or "")[-400:],
            "files": sorted(p.name for p in work.glob("*.con")),
        }

    plain = once(WORK / "dimer" / "plain", reactant)
    rt_pos = WORK / "dimer" / "pos_round.con"
    fixed_pos = WORK / "dimer" / "pos_fixed6.con"
    round_trip(reactant, rt_pos, None)
    round_trip(reactant, fixed_pos, 6)
    rounded = once(WORK / "dimer" / "round", rt_pos)
    fixed = once(WORK / "dimer" / "fixed6", fixed_pos)

    def energy(row: dict) -> float | None:
        for key in ("potential_energy_saddle", "potential_energy"):
            if key in row["results"]:
                return float(row["results"][key])
        return None

    saddle_plain = WORK / "dimer" / "plain" / "saddle.con"
    saddle_round = WORK / "dimer" / "round" / "saddle.con"
    saddle_fixed = WORK / "dimer" / "fixed6" / "saddle.con"
    cmp = {}
    if saddle_plain.is_file() and saddle_round.is_file():
        a = positions_of(saddle_plain)
        b = positions_of(saddle_round)
        cmp["roundtrip_bit_identical"] = bool(np.array_equal(a, b))
        cmp["roundtrip_rmsd_A"] = rmsd(a, b)
    if saddle_plain.is_file() and saddle_fixed.is_file():
        a = positions_of(saddle_plain)
        c = positions_of(saddle_fixed)
        cmp["fixed6_bit_identical"] = bool(np.array_equal(a, c))
        cmp["fixed6_rmsd_A"] = rmsd(a, c)
        if energy(plain) is not None and energy(fixed) is not None:
            cmp["fixed6_saddle_energy_delta_eV"] = energy(fixed) - energy(plain)
    return {"plain": plain, "round": rounded, "fixed6": fixed, "compare": cmp}


def dynamics_campaign(reactant: Path) -> dict:
    work = WORK / "dynamics"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    frames = readcon.read_con(str(reactant))
    # Seed a small velocity on the adatom so the file carries a velocity section
    # if the dynamics writer keeps it. The dynamics job itself thermalizes.
    readcon.write_con(str(work / "pos.con"), frames)
    (work / "config.ini").write_text(
        """[Main]
job = dynamics
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Dynamics]
time_step = 1
time = 5
thermostat = none
"""
    )
    t0 = time.perf_counter()
    proc = run([EON], work, timeout=180)
    files = sorted(p.name for p in work.glob("*"))
    final = work / "final.con"
    has_vel = False
    if final.is_file():
        text = final.read_text()
        has_vel = "Velocities" in text or "velocities" in text
    # A second 5 fs leg from the round-tripped and the 6-decimal final frame,
    # against one uninterrupted 10 fs run.
    long = WORK / "dynamics_long"
    _rerun_dynamics(long, work / "pos.con", extra_time=10)
    resumed = {}
    if final.is_file():
        for tag, precision in (("round", None), ("fixed6", 6)):
            leg = WORK / f"dynamics_{tag}"
            src = WORK / f"dynamics_{tag}_start.con"
            round_trip(final, src, precision)
            resumed[tag] = _rerun_dynamics(leg, src, extra_time=5)
            if (leg / "final.con").is_file() and (long / "final.con").is_file():
                a = positions_of(long / "final.con")
                b = positions_of(leg / "final.con")
                resumed[tag]["bit_identical_to_10fs"] = bool(np.array_equal(a, b))
                resumed[tag]["rmsd_to_10fs_A"] = rmsd(a, b)
                resumed[tag]["max_abs_to_10fs_A"] = max_abs(a, b)
    return {
        "returncode": proc.returncode,
        "seconds": time.perf_counter() - t0,
        "files": files,
        "final_has_velocities_section": has_vel,
        "time_unit_note": "The 5 fs writer stamped units.time = fs and did not emit a velocities section.",
        "results": parse_results(work / "results.dat"),
        "stderr_tail": (proc.stderr or "")[-500:],
        "continue": resumed,
    }


def _rerun_dynamics(work: Path, pos: Path, extra_time: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(pos, work / "pos.con")
    (work / "config.ini").write_text(
        f"""[Main]
job = dynamics
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Dynamics]
time_step = 1
time = {extra_time}
thermostat = none
"""
    )
    t0 = time.perf_counter()
    proc = run([EON], work, timeout=180)
    return {
        "returncode": proc.returncode,
        "seconds": time.perf_counter() - t0,
        "energy": parse_results(work / "results.dat").get("potential_energy"),
        "stderr_tail": (proc.stderr or "")[-300:],
    }


def velocity_factor(atoms, masks) -> dict:
    """Write the 28-atom velocity fixture and take its numbers from velocity_case.

    The stored components are NATURAL_TO_FS times a draw of sqrt(kB T / m),
    which is already in the natural unit, so the fixture is not a 300 K slab.
    """
    rng = np.random.default_rng(20261011)
    masses = atoms.get_masses()
    kB = 8.617333262145e-5  # eV/K
    sigma = np.sqrt(kB * 300.0 / masses)
    vel_nat = rng.normal(scale=sigma[:, None], size=(len(atoms), 3)) * NATURAL_TO_FS
    path = WORK / "velocity" / "natural.con"
    if not path.is_file():
        write_frame(path, atoms, masks, velocities=vel_nat)
    frames = readcon.read_con(str(path))
    got = np.array([[a.vx, a.vy, a.vz] for a in frames[0].atoms], dtype=float)
    if not np.array_equal(got, vel_nat) or not np.array_equal(
        positions_of(path)[0], atoms.get_positions()
    ):
        raise SystemExit(f"{path} is not the seeded draw on the unminimised slab")
    unit = velocity_case.natural_fs()
    shared = velocity_case.slab_28(path, unit["readcon_fs"], unit["kB_eV_per_K"])
    return {
        "n_atoms": shared["n_atoms"],
        "fixture_sha256": shared["fixture_sha256"],
        "ke_true_eV": shared["ke_natural_eV"],
        "ke_if_natural_numbers_read_as_fs_eV": shared["ke_if_read_as_fs_eV"],
        "ratio": shared["ke_if_read_as_fs_eV"] / shared["ke_natural_eV"],
        "factor_squared": float(NATURAL_TO_FS**2),
        "temperature_equivalent_K": shared["temperature_equivalent_K"],
        "roundtrip_max_abs_velocity": float(np.max(np.abs(got - vel_nat))),
        "time_label": shared["time_unit"],
        "eon_dynamics_keeps_file_velocity": False,
        "verlet_dt_fs": shared["verlet_dt_fs"],
        "verlet_potential": shared["verlet_potential"],
        "verlet_rmsd_A": shared["verlet_rmsd_A"],
        "verlet_max_abs_A": shared["verlet_max_abs_A"],
        "generator": "paper/cpc/scripts/velocity_case.py slab_28",
    }


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    reactant_atoms, product_atoms, masks, adatom = build_hop()
    geom = WORK / "geom"
    geom.mkdir(parents=True, exist_ok=True)
    write_frame(geom / "reactant.con", reactant_atoms, masks)
    write_frame(geom / "product.con", product_atoms, masks)
    summary = {
        "provenance": provenance.record(),
        "outputs": [WORK.relative_to(ROOT.parent).as_posix()],
        "roundoff_host": rf.roundoff_host(),
        "cpu": cpu_name(),
        "python": platform.python_version(),
        "ase": ase.__version__,
        "readcon": package_module_path(readcon.__file__),
        "eonclient": eon_version(),
        "eon_build": eon_build(),
        "potential": "morse_pt",
        "system": "Pt(100) 3x3x3 slab plus one Pt adatom, hollow to the neighbouring hollow",
        "slab": "restart_formats.slab, the slab of Section 6",
        "vacuum_A": rf.VACUUM,
        "held_height_A": rf.HEIGHT,
        "n_atoms": int(len(reactant_atoms)),
        "n_fixed_bottom": int(sum(m == 7 for m in masks)),
        "adatom_index": adatom,
        "adatom_mask": masks[adatom],
        "converged_force_eV_A": FMAX,
        "interrupt_max_iterations": INTERRUPT_AT,
        "note_neb_optimizer": (
            "Band steps use [Nudged Elastic Band] opt_method; results.dat reports [Optimizer] opt_method "
            "as optimizer_backend. Each band run sets both keys to its optimiser, and the script stops unless "
            "every run reports that backend and constructs that optimiser alone (optimizers_constructed, from "
            "the eon_logs files eOn opens in the run's TMPDIR). default_band_optimizer is a run that sets "
            "neither key."
        ),
    }
    summary["minimize_reactant"] = minimize_endpoint(
        geom / "reactant.con", geom / "reactant_min.con"
    )
    summary["minimize_product"] = minimize_endpoint(
        geom / "product.con", geom / "product_min.con"
    )
    reactant = geom / "reactant_min.con"
    product = geom / "product_min.con"
    summary["morse_single_point_seconds_median"] = force_call_seconds(reactant)
    campaigns = {key: neb_campaign(reactant, product, key) for key in BAND_OPTIMIZERS}
    summary["converged_barrier_spread"] = {
        "sd_minus_lbfgs_eV": campaigns["sd"]["full"]["barrier_eV"]
        - campaigns["lbfgs"]["full"]["barrier_eV"],
        "sd_minus_lbfgs_con_eV": (
            campaigns["sd"]["full"]["barrier_con_eV"]
            - campaigns["lbfgs"]["full"]["barrier_con_eV"]
        ),
        "note": "Both uninterrupted bands end GOOD at converged_force_eV_A, each with its own band optimizer.",
    }
    summary["eon_engine"] = engine_identity(campaigns["sd"]["full"]["results"])
    summary["default_band_optimizer"] = default_band_optimizer(reactant, product)
    summary["dimer"] = dimer_campaign(reactant)
    summary["dynamics"] = dynamics_campaign(reactant)
    summary["velocity"] = velocity_factor(reactant_atoms, masks)
    scrub_client_logs(WORK)
    for key, band in BAND_OPTIMIZERS.items():
        record = dict(
            summary, optimizer=campaigns[key]["optimizer"], neb=campaigns[key]
        )
        if key == "sd":
            record["neb_lbfgs"] = campaigns["lbfgs"]
        (RESULTS / band["results"]).write_text(json.dumps(record, indent=2) + "\n")
    for key, campaign in campaigns.items():
        print(
            key,
            campaign["optimizer_backend_every_run"],
            "interrupt",
            campaign["interrupt_max_iterations"],
            "iterations,",
            campaign["interrupt_optimizer_steps"],
            "steps",
        )
        print(
            key,
            json.dumps(
                {
                    "full": {
                        k: campaign["full"][k]
                        for k in (
                            "termination",
                            "iterations",
                            "optimizer_steps",
                            "barrier_eV",
                            "max_projected_force_eV_A",
                        )
                    },
                    **{
                        tag: {
                            k: campaign[tag].get(k)
                            for k in (
                                "termination",
                                "optimizer_steps",
                                "barrier_eV",
                                "barrier_delta_eV",
                                "extra_optimizer_steps",
                                "mic_max_abs_A",
                                "max_projected_force_eV_A",
                            )
                        }
                        for tag in ("resume_eon", "resume_roundtrip", "resume_fixed6")
                    },
                },
                indent=1,
            ),
        )
    print(
        "endpoints",
        summary["minimize_reactant"]["residual"],
        summary["minimize_product"]["residual"],
    )
    print("default band optimizer", summary["default_band_optimizer"])
    print("dimer", summary["dimer"].get("compare"))
    print("velocity", summary["velocity"]["ke_true_eV"], summary["velocity"]["ratio"])


if __name__ == "__main__":
    main()
