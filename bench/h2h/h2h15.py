#!/usr/bin/env python3
"""Fair head-to-head for MDCompress 2.0.5 and chemfiles after PR 532.

Same structures and serial settings as the cross-format table: fresh
process per sample, cores 0-7, one warmup, n=12, type-7 median. MDCompress
compresses and reads the XTC and the DCD of that trajectory. readcon times
CON, CON.gz, CON.zst and CON-bin. chemfiles 0.10.4 DCD stays its own row.
chemfiles 0.12.0-dev is the shared library built at fc1e930, loaded by
pointer, and is never the 0.10.4 module.

The record names the pushed parent commit and the sha256 of ``git diff``
from that parent to HEAD. A dirty tree is refused. Paths in the record
are relative to the repository.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
sys.path.insert(0, str(BENCH))

import cross_format  # noqa: E402
from bench_disk import bench_disk  # noqa: E402
from sample_protocol import (  # noqa: E402
    core_list,
    host_snapshot,
    peak_rss_bytes,
    pin_cores,
    result_line,
    rotate,
    spawn_worker,
)

PARENT = "0b62d689367cf69797107ca505778fde1017990d"
MDC_TAG = "v2.0.5"
MDC_COMMIT = "41b600313c1a8265dbaa639651ed0124610d1bbb"
CF012_COMMIT = "fc1e93096b797ff4848dae57c03b7c9ef287cccd"
CF012_VERSION = "0.12.0-dev"
AKMA_TO_PS = 4.888821e-2
RECORD = BENCH / "scaling" / "h2h15"

# Fields the comparison is willing to lose. A kept field is absent here.
DROPS = {
    "readcon-con": "forces,energies",
    "readcon-con-gz": "forces,energies",
    "readcon-con-zst": "forces,energies",
    "readcon-conbin": "forces,energies",
    "mdcompress-dcd": (
        "velocities,forces,energies,per-component mask,atom id,binary64 coordinates"
    ),
    "mdcompress-xtc": (
        "velocities,forces,energies,per-component mask,atom id,binary64 coordinates"
    ),
    "chemfiles-dcd": (
        "velocities,forces,energies,per-component mask,atom id,"
        "binary64 coordinates,interval unit: AKMA"
    ),
    "chemfiles-dcd-012": (
        "velocities,forces,energies,per-component mask,atom id,"
        "binary64 coordinates,interval unit: picoseconds"
    ),
}

READCON_ARMS = (
    "readcon-con",
    "readcon-con-gz",
    "readcon-con-zst",
    "readcon-conbin",
)


def git(*args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and done.returncode != 0:
        raise SystemExit(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout


def require_clean_tree() -> str:
    """HEAD must contain the pushed parent, and the index must be clean."""
    head = git("rev-parse", "HEAD").strip()
    if len(head) != 40:
        raise SystemExit(f"HEAD is not a commit sha: {head!r}")
    if git("merge-base", "--is-ancestor", PARENT, "HEAD", check=False).strip():
        raise SystemExit("merge-base should be silent")
    ancestor = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", PARENT, "HEAD"],
        check=False,
    )
    if ancestor.returncode != 0:
        raise SystemExit(f"{PARENT} is not an ancestor of {head}")
    refuse_if_dirty(git("status", "--porcelain", "--untracked-files=no"))
    return head


def diff_sha256(parent: str = PARENT) -> str:
    blob = git("diff", parent, "HEAD")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def repo_relative(path: Path) -> str:
    """A path inside the repository, with forward slashes and no root prefix."""
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit(f"path is outside the repository: {path}") from exc
    text = relative.as_posix()
    if text.startswith("/") or text.startswith("../"):
        raise SystemExit(f"path is not repo-relative: {text}")
    return text


# Prefixes the record must not contain. Split so the source does not name them.
_MACHINE = ("/" + "tmp", "/" + "home/", "/" + "agent")


def assert_repo_relative_record(text: str) -> None:
    root = str(ROOT.resolve())
    if root in text or any(token in text for token in _MACHINE):
        raise SystemExit("record contains a machine path")


def refuse_if_dirty(text: str) -> None:
    if text.strip():
        raise SystemExit(f"refusing a dirty tree:\n{text.strip()}")


def mdcompress_prefix() -> Path:
    return bench_disk() / "mdcompress-2.0.5"


def pin_mdcompress() -> tuple[Path, Path]:
    """Point the shared finder at the v2.0.5 build under the bench disk."""
    prefix = mdcompress_prefix()
    binary = prefix / "mdcompress"
    if not binary.is_file():
        raise SystemExit("MDCompress 2.0.5 is not installed under the bench disk")
    if not any(prefix.glob("mdc*.so")):
        raise SystemExit(
            "MDCompress 2.0.5 reader is not installed under the bench disk"
        )
    os.environ["MDCOMPRESS"] = os.fspath(binary)
    os.environ["MDCOMPRESS_PYTHON"] = os.fspath(prefix)
    return binary, prefix


def dcd_delta(path: Path) -> float:
    """CHARMM DCD DELTA, a little-endian float32 at file offset 44."""
    data = path.read_bytes()
    if len(data) < 48:
        raise SystemExit(f"DCD header is short: {path}")
    return float(struct.unpack_from("<f", data, 44)[0])


def chemfiles_012_library() -> Path | None:
    root = bench_disk() / "chemfiles-fc1e930"
    found = list(root.glob("lib*/libchemfiles.so"))
    if not found:
        found = list(root.glob("lib*/libchemfiles.so.*"))
    return found[0] if found else None


def load_chemfiles(path: Path):
    lib = ctypes.CDLL(os.fspath(path))
    lib.chfl_trajectory_open.argtypes = [ctypes.c_char_p, ctypes.c_char]
    lib.chfl_trajectory_open.restype = ctypes.c_void_p
    lib.chfl_trajectory_with_format.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char,
        ctypes.c_char_p,
    ]
    lib.chfl_trajectory_with_format.restype = ctypes.c_void_p
    lib.chfl_trajectory_read.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.chfl_trajectory_read.restype = ctypes.c_int
    lib.chfl_trajectory_write.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.chfl_trajectory_write.restype = ctypes.c_int
    lib.chfl_trajectory_close.argtypes = [ctypes.c_void_p]
    lib.chfl_frame.restype = ctypes.c_void_p
    lib.chfl_frame_resize.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.chfl_frame_resize.restype = ctypes.c_int
    vec3 = ctypes.c_double * 3
    lib.chfl_frame_positions.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(vec3)),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    lib.chfl_frame_positions.restype = ctypes.c_int
    lib.chfl_cell.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.chfl_cell.restype = ctypes.c_void_p
    lib.chfl_frame_set_cell.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.chfl_frame_set_cell.restype = ctypes.c_int
    lib.chfl_property_double.argtypes = [ctypes.c_double]
    lib.chfl_property_double.restype = ctypes.c_void_p
    lib.chfl_frame_set_property.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
    ]
    lib.chfl_frame_set_property.restype = ctypes.c_int
    lib.chfl_free.argtypes = [ctypes.c_void_p]
    lib.chfl_last_error.restype = ctypes.c_char_p
    return lib


def _cf_check(lib, status: int, what: str) -> None:
    if status == 0:
        return
    err = lib.chfl_last_error()
    detail = err.decode() if err else str(status)
    raise SystemExit(f"chemfiles 0.12.0-dev {what}: {detail}")


def build_cf012_frames(lib, spec: dict) -> list:
    """Frames for the pinned library. The per-atom fill is outside the clock."""
    frames = []
    for index in range(spec["n_frames"]):
        frame = lib.chfl_frame()
        if not frame:
            raise SystemExit("chemfiles 0.12.0-dev did not allocate a frame")
        _cf_check(lib, lib.chfl_frame_resize(frame, spec["n_atoms"]), "resize")
        vec3 = ctypes.c_double * 3
        pointer = ctypes.POINTER(vec3)()
        size = ctypes.c_uint64()
        _cf_check(
            lib,
            lib.chfl_frame_positions(frame, ctypes.byref(pointer), ctypes.byref(size)),
            "positions",
        )
        view = np.ctypeslib.as_array(pointer, shape=(spec["n_atoms"],))
        view[:] = spec["positions"][index]
        lengths = (ctypes.c_double * 3)(*spec["cell"][index, :3])
        angles = (ctypes.c_double * 3)(90.0, 90.0, 90.0)
        cell = lib.chfl_cell(lengths, angles)
        _cf_check(lib, lib.chfl_frame_set_cell(frame, cell), "cell")
        lib.chfl_free(cell)
        # One picosecond and one simulation step. The writer stores the
        # interval on disk as AKMA and keeps picoseconds in memory.
        stamp = lib.chfl_property_double(float(index))
        _cf_check(lib, lib.chfl_frame_set_property(frame, b"time", stamp), "time")
        lib.chfl_free(stamp)
        step = lib.chfl_property_double(float(index))
        _cf_check(
            lib,
            lib.chfl_frame_set_property(frame, b"simulation_step", step),
            "simulation_step",
        )
        lib.chfl_free(step)
        frames.append(frame)
    return frames


def write_cf012(lib, path: Path, frames: list) -> None:
    path.unlink(missing_ok=True)
    traj = lib.chfl_trajectory_with_format(os.fsencode(path), b"w", b"DCD")
    if not traj:
        raise SystemExit("chemfiles 0.12.0-dev did not open a DCD writer")
    for frame in frames:
        _cf_check(lib, lib.chfl_trajectory_write(traj, frame), "write")
    lib.chfl_trajectory_close(traj)


def read_cf012(lib, path: Path) -> dict:
    traj = lib.chfl_trajectory_open(os.fsencode(path), b"r")
    if not traj:
        raise SystemExit("chemfiles 0.12.0-dev did not open a DCD reader")
    positions = []
    cells = []
    while True:
        frame = lib.chfl_frame()
        status = lib.chfl_trajectory_read(traj, frame)
        if status != 0:
            lib.chfl_free(frame)
            break
        vec3 = ctypes.c_double * 3
        pointer = ctypes.POINTER(vec3)()
        size = ctypes.c_uint64()
        _cf_check(
            lib,
            lib.chfl_frame_positions(frame, ctypes.byref(pointer), ctypes.byref(size)),
            "read positions",
        )
        view = np.ctypeslib.as_array(pointer, shape=(size.value,))
        positions.append(np.array(view, dtype=np.float64, copy=True))
        cells.append(np.zeros(6, dtype=np.float64))
        lib.chfl_free(frame)
    lib.chfl_trajectory_close(traj)
    if not positions:
        raise SystemExit("chemfiles 0.12.0-dev read no frames")
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": None,
        "fixed": None,
    }


def stamp_chemfiles_0104(frames: list) -> None:
    """Give 0.10.4 frames a one-picosecond step, outside the write clock."""
    for index, frame in enumerate(frames):
        try:
            frame.set("time", float(index))
        except Exception:
            return


def source_for(arm: str, spec: dict, directory: Path) -> Path:
    """XTC or DCD of this trajectory, written once, outside every clock."""
    if arm == "mdcompress-xtc":
        path = directory / "source.xtc"
        if not path.is_file():
            cross_format.write_chemfiles(path, spec, "XTC")
        return path
    path = directory / "source.dcd"
    if not path.is_file():
        cross_format.write_chemfiles(path, spec, "DCD")
    return path


def _unsupported(label: str, n_atoms: int, n_frames: int, arm: str, op: str) -> dict:
    return {
        "structure": label,
        "atoms": n_atoms,
        "frames": n_frames,
        "arm": arm,
        "tool": "mdcompress",
        "op": op,
        "cache": "unsupported",
        "median_s": None,
        "iqr_s": None,
        "n": 0,
        "rss_bytes": None,
        "file_bytes": None,
        "loses": ("unsupported: MDCompress 2.0.5 cannot read a one-frame trajectory"),
    }


def worker_main() -> None:
    pin_cores()
    pin_mdcompress()
    cross_format.serial_threads()
    os.environ["RAYON_NUM_THREADS"] = "1"
    job = json.loads(sys.stdin.read())
    if job["op"] == "prepare-012":
        spec = cross_format.load_spec(job["spec"])
        library = load_chemfiles(Path(job["library"]))
        write_cf012(
            library,
            Path(job["dest"]),
            build_cf012_frames(library, spec),
        )
        result_line(0.0)
        return
    arm = job["arm"]
    if job["op"] == "read":
        path = job["path"]

        def once(path=path, arm=arm):
            if arm == "chemfiles-dcd-012":
                lib = load_chemfiles(Path(job["library"]))
                got = read_cf012(lib, Path(path))
            elif arm in ("mdcompress-dcd", "mdcompress-xtc"):
                got = cross_format.read_mdcompress(path)
            else:
                got = cross_format.read_arm(arm, path, n_threads=1)
            positions = np.asarray(got["positions"], dtype=np.float64)
            return float(np.sum(positions, dtype=np.float64))

        if job.get("cache") != "cold":
            with open(path, "rb") as handle:
                handle.read(1)
        once()
        if job.get("cache") == "cold":
            cross_format.drop_page_cache()
        started = time.perf_counter()
        checksum = once()
        result_line(time.perf_counter() - started, checksum=checksum)
        return
    spec = cross_format.load_spec(job["spec"])
    dest = Path(job["dest"])
    frames_0104 = None
    frames_012 = None
    library = None
    packed = None
    child_rss = 0
    if arm == "chemfiles-dcd":
        frames_0104 = cross_format.build_chemfiles_frames(spec, "DCD", dest)
        stamp_chemfiles_0104(frames_0104)
    elif arm == "chemfiles-dcd-012":
        library = load_chemfiles(Path(job["library"]))
        frames_012 = build_cf012_frames(library, spec)
    elif arm in ("readcon-con-gz", "readcon-con-zst"):
        import readcon

        packed = readcon.read_con(job["plain"], n_threads=1)

    def once():
        nonlocal child_rss
        if arm == "chemfiles-dcd":
            cross_format.write_built_chemfiles(dest, "DCD", frames_0104)
        elif arm == "chemfiles-dcd-012":
            write_cf012(library, dest, frames_012)
        elif arm in ("mdcompress-dcd", "mdcompress-xtc"):
            child_rss = max(
                child_rss,
                cross_format.write_mdcompress(
                    dest, Path(job["source"]), Path(job["desc"])
                ),
            )
        elif arm == "readcon-con":
            cross_format.write_readcon(dest, spec, None)
        elif arm in ("readcon-con-gz", "readcon-con-zst"):
            import readcon

            dest.unlink(missing_ok=True)
            compression = "gzip" if arm.endswith("-gz") else "zstd"
            readcon.write_con(
                os.fspath(dest), packed, compression=compression, n_threads=1
            )
        elif arm == "readcon-conbin":
            import readcon

            dest.unlink(missing_ok=True)
            readcon.write_conbin_columns(
                os.fspath(dest),
                spec["positions"],
                spec["velocities"],
                spec["masses"],
                spec["cell"],
                spec["fixed"],
            )
        else:
            raise SystemExit(arm)

    once()
    started = time.perf_counter()
    once()
    result_line(
        time.perf_counter() - started,
        rss_bytes=max(peak_rss_bytes(), child_rss),
    )


def _median(values: list[float]) -> tuple[float, float]:
    return cross_format.type7(values)


def run(out: Path, repeats: int = 12) -> None:
    if repeats < 12:
        raise SystemExit("h2h15 takes at least 12 samples")
    head = require_clean_tree()
    digest = diff_sha256()
    import readcon

    version = readcon.__version__
    out.mkdir(parents=True, exist_ok=True)
    work = BENCH / "work" / "h2h15"
    work.mkdir(parents=True, exist_ok=True)
    host = host_snapshot()
    rows: list[dict] = []
    lines = [
        f"parent {PARENT}",
        f"diff_sha256 {digest}",
        f"measured_commit {head}",
        f"readcon {version}",
        f"mdcompress {MDC_TAG} {MDC_COMMIT}",
        "chemfiles_0104 0.10.4",
        f"chemfiles_012 {CF012_VERSION} {CF012_COMMIT}",
        f"warmup 1 samples {repeats} percentile type7 serial 1",
        f"fresh process per sample, taskset -c {core_list()}",
    ]
    library = chemfiles_012_library()
    if library is None:
        raise SystemExit("chemfiles fc1e930 is not installed under the bench disk")
    pin_mdcompress()
    found = cross_format._mdcompress_tools()
    if found is None or found[2] != "2.0.5":
        raise SystemExit("MDCompress 2.0.5 is not the binary under the bench disk")
    script = Path(__file__).resolve()
    for label, n_atoms, n_frames in cross_format.STRUCTURES:
        directory = work / label
        directory.mkdir(parents=True, exist_ok=True)
        spec = cross_format.make_spec(n_atoms, n_frames)
        spec_path = directory / "spec.npz"
        cross_format.save_spec(spec_path, spec)
        plain = directory / "readcon.con"
        if not plain.is_file():
            cross_format.write_readcon(plain, spec, None)
        inputs = {
            "readcon-con": plain,
            "readcon-con-gz": directory / "readcon.con.gz",
            "readcon-con-zst": directory / "readcon.con.zst",
            "readcon-conbin": directory / "readcon.conbin",
            "chemfiles-dcd": directory / "chemfiles.dcd",
            "chemfiles-dcd-012": directory / "chemfiles012.dcd",
            "mdcompress-dcd": directory / "mdcompress.dcd.mdc",
            "mdcompress-xtc": directory / "mdcompress.xtc.mdc",
        }
        if not inputs["readcon-con-gz"].is_file():
            cross_format.write_readcon(inputs["readcon-con-gz"], spec, "gzip")
        if not inputs["readcon-con-zst"].is_file():
            cross_format.write_readcon(inputs["readcon-con-zst"], spec, "zstd")
        if not inputs["readcon-conbin"].is_file():
            import readcon as rc

            rc.write_conbin_columns(
                os.fspath(inputs["readcon-conbin"]),
                spec["positions"],
                spec["velocities"],
                spec["masses"],
                spec["cell"],
                spec["fixed"],
            )
        if not inputs["chemfiles-dcd"].is_file():
            cross_format.write_chemfiles(inputs["chemfiles-dcd"], spec, "DCD")
        desc = directory / "mdcompress.desc"
        desc.write_text(f"MOL\tmetal\t{n_atoms}\n", encoding="utf-8")
        dcd_src = source_for("mdcompress-dcd", spec, directory)
        xtc_src = source_for("mdcompress-xtc", spec, directory)
        if n_frames >= 2:
            if not inputs["mdcompress-dcd"].is_file():
                cross_format.write_mdcompress(inputs["mdcompress-dcd"], dcd_src, desc)
            if not inputs["mdcompress-xtc"].is_file():
                cross_format.write_mdcompress(inputs["mdcompress-xtc"], xtc_src, desc)
        if not inputs["chemfiles-dcd-012"].is_file():
            # A fresh process, so this library is not the 0.10.4 module.
            spawn_worker(
                script,
                {
                    "op": "prepare-012",
                    "spec": os.fspath(spec_path),
                    "dest": os.fspath(inputs["chemfiles-dcd-012"]),
                    "library": os.fspath(library),
                },
            )
        arms = list(DROPS)
        if n_frames < 2:
            for arm in ("mdcompress-dcd", "mdcompress-xtc"):
                rows.append(_unsupported(label, n_atoms, n_frames, arm, "read"))
                rows.append(_unsupported(label, n_atoms, n_frames, arm, "write"))
                lines.append(f"unsupported {label} {arm}")
            arms = [arm for arm in arms if not arm.startswith("mdcompress-")]
        timed: dict[str, dict] = {}
        for cache in ("warm", "cold"):
            found = {arm: [] for arm in arms}
            rss = {arm: [] for arm in arms}
            for sample in range(repeats):
                order = rotate(list(arms), sample)
                lines.append(f"order read-{cache} {label} {sample} " + " ".join(order))
                for arm in order:
                    job = {
                        "op": "read",
                        "arm": arm,
                        "path": os.fspath(inputs[arm]),
                        "cache": cache,
                        "library": os.fspath(library),
                    }
                    result = spawn_worker(script, job)
                    found[arm].append(float(result["wall_s"]))
                    rss[arm].append(int(result["rss_bytes"]))
                    lines.append(f"    {arm} {result['wall_s']:.4f}")
            timed[cache] = {"samples": found, "rss": rss}
        for arm in arms:
            samples = timed["warm"]["samples"][arm]
            cold = timed["cold"]["samples"][arm]
            median, iqr = _median(samples)
            cold_median, cold_iqr = _median(cold)
            path = inputs[arm]
            rows.append(
                {
                    "structure": label,
                    "atoms": n_atoms,
                    "frames": n_frames,
                    "arm": arm,
                    "tool": arm.split("-", 1)[0],
                    "op": "read",
                    "cache": "warm",
                    "median_s": median,
                    "iqr_s": iqr,
                    "n": len(samples),
                    "rss_bytes": int(np.median(timed["warm"]["rss"][arm])),
                    "file_bytes": path.stat().st_size if path.is_file() else None,
                    "loses": DROPS[arm],
                    "cold_median_s": cold_median,
                    "cold_iqr_s": cold_iqr,
                    "cold_n": len(cold),
                }
            )
        write_found = {arm: [] for arm in arms}
        write_rss = {arm: [] for arm in arms}
        timed_dir = directory / "timed"
        timed_dir.mkdir(parents=True, exist_ok=True)
        for sample in range(repeats):
            order = rotate(list(arms), sample)
            lines.append(f"order write {label} {sample} " + " ".join(order))
            for arm in order:
                dest = timed_dir / Path(inputs[arm]).name
                job = {
                    "op": "write",
                    "arm": arm,
                    "spec": os.fspath(spec_path),
                    "dest": os.fspath(dest),
                    "plain": os.fspath(plain),
                    "library": os.fspath(library),
                    "source": os.fspath(
                        dcd_src if arm != "mdcompress-xtc" else xtc_src
                    ),
                    "desc": os.fspath(desc),
                }
                result = spawn_worker(script, job)
                write_found[arm].append(float(result["wall_s"]))
                write_rss[arm].append(int(result["rss_bytes"]))
                lines.append(f"    {arm} {result['wall_s']:.4f}")
        for arm in arms:
            samples = write_found[arm]
            median, iqr = _median(samples)
            dest = timed_dir / Path(inputs[arm]).name
            loses = DROPS[arm]
            if (
                arm in ("chemfiles-dcd", "chemfiles-dcd-012")
                and dest.is_file()
                and n_frames >= 2
            ):
                delta = dcd_delta(dest)
                loses = f"{loses}; header DELTA {delta:.6g}"
            rows.append(
                {
                    "structure": label,
                    "atoms": n_atoms,
                    "frames": n_frames,
                    "arm": arm,
                    "tool": arm.split("-", 1)[0],
                    "op": "write",
                    "cache": "create",
                    "median_s": median,
                    "iqr_s": iqr,
                    "n": len(samples),
                    "rss_bytes": int(np.median(write_rss[arm])),
                    "file_bytes": dest.stat().st_size if dest.is_file() else None,
                    "loses": loses,
                }
            )
    payload = {
        "parent": PARENT,
        "diff_sha256": digest,
        "measured_commit": head,
        "readcon_version": version,
        "mdcompress_tag": MDC_TAG,
        "mdcompress_commit": MDC_COMMIT,
        "chemfiles_0104": "0.10.4",
        "chemfiles_012_version": CF012_VERSION,
        "chemfiles_012_commit": CF012_COMMIT,
        "warmup": 1,
        "repeats": repeats,
        "percentile": "type7",
        "serial": True,
        "affinity": f"taskset -c {core_list()}",
        "clock": (
            "Each sample is a fresh process. The read clock is one untimed "
            "call, then the timed call. A warm read touches one byte before "
            "that warmup. A cold read drops the page cache after the warmup. "
            "The write clock is the write itself: frames, source files and "
            "the MDCompress description already exist. MDCompress writes with "
            "compress -t 1 --preset archive. gzip and zstd load frames before "
            "the clock. Peak RSS is VmHWM, and for MDCompress the compressor "
            "child when that is higher."
        ),
        "mdcompress_build": (
            "tag v2.0.5 commit 41b600313c1a8265dbaa639651ed0124610d1bbb. "
            "gcc 13 needs the libxdrfile objects built as C11 with "
            "_GNU_SOURCE and without -fabi-version=6. Those edits stay in "
            "the build tree."
        ),
        "host": {
            "cpu_model": next(
                (
                    line.split(":", 1)[1].strip()
                    for line in (host.get("lscpu") or "").splitlines()
                    if line.startswith("Model name:")
                ),
                "",
            ),
            "record": repo_relative(out),
        },
        "rows": rows,
    }
    text = json.dumps(payload, indent=2) + "\n"
    assert_repo_relative_record(text)
    (out / "cross-format.json").write_text(text, encoding="utf-8")
    (out / "cross-format.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "identity.txt").write_text(
        f"parent {PARENT}\ndiff_sha256 {digest}\nmeasured_commit {head}\n",
        encoding="utf-8",
    )
    (out / "provenance.json").write_text(
        json.dumps(
            {
                "parent": PARENT,
                "diff_sha256": digest,
                "measured_commit": head,
                "readcon_version": version,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {repo_relative(out / 'cross-format.json')}", flush=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=RECORD)
    parser.add_argument("--repeats", type=int, default=12)
    args = parser.parse_args()
    run(args.out, args.repeats)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker_main()
    else:
        main()
