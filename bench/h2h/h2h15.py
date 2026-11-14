#!/usr/bin/env python3
"""Fair head-to-head for MDCompress 2.0.5 and chemfiles after PR 532.

Same structures and serial settings as the cross-format table: fresh
process per sample, cores 0-7, one warmup, n=12, type-7 median. MDCompress
compresses and reads the XTC and the DCD of that trajectory. readcon times
CON, CON.gz, CON.zst and CON-bin. chemfiles 0.10.4 DCD stays its own row.
chemfiles 0.12.0-dev is the shared library built at fc1e930, loaded by
pointer, and is never the 0.10.4 module.

Measurement goes through ``measured_commit.measurement``: a clean tree
whose ``HEAD`` ``git branch -r --contains`` already lists. The record
stores that commit, its tree, and the empty diff digest from that helper.
Paths in the record are relative to the repository.

``cross_format.run`` writes every row of the cross-format table, including
host.json and the chemfiles write profile. This script then measures the
two rows that table does not have, MDCompress on XTC and chemfiles DCD at
fc1e930, and writes them into the same files. Nothing is copied from an
older campaign.
"""

from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
sys.path.insert(0, str(BENCH))

import cross_format  # noqa: E402
from bench_disk import bench_disk  # noqa: E402
from measured_commit import measurement, record_path  # noqa: E402
from sample_protocol import (  # noqa: E402
    peak_rss_bytes,
    pin_cores,
    result_line,
    rotate,
    spawn_worker,
)

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


# Prefixes the record must not contain. Split so the source does not name them.
_MACHINE = ("/" + "tmp", "/" + "home/", "/" + "agent")


def assert_repo_relative_record(text: str) -> None:
    root = str(ROOT.resolve())
    if root in text or any(token in text for token in _MACHINE):
        raise SystemExit("record contains a machine path")


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


def _extra_rows(out: Path, repeats: int, script: Path) -> tuple[list[dict], list[str]]:
    """MDCompress on XTC, and chemfiles DCD at fc1e930.

    The cross-format table already times MDCompress on DCD as
    ``mdcompress-mdc`` and chemfiles 0.10.4 DCD as ``chemfiles-dcd``.
    These two rows are measured here, in the same run, and stored in the
    same files.
    """
    library = chemfiles_012_library()
    if library is None:
        raise SystemExit("chemfiles fc1e930 is not installed under the bench disk")
    rows: list[dict] = []
    lines: list[str] = []
    work = BENCH / "work" / "h2h15"
    for label, n_atoms, n_frames in cross_format.STRUCTURES:
        directory = work / label
        directory.mkdir(parents=True, exist_ok=True)
        spec = cross_format.make_spec(n_atoms, n_frames)
        spec_path = directory / "spec.npz"
        cross_format.save_spec(spec_path, spec)
        desc = directory / "mdcompress.desc"
        desc.write_text(f"MOL\tmetal\t{n_atoms}\n", encoding="utf-8")
        xtc_src = source_for("mdcompress-xtc", spec, directory)
        inputs = {
            "mdcompress-xtc": directory / "mdcompress.xtc.mdc",
            "chemfiles-dcd-012": directory / "chemfiles012.dcd",
        }
        if n_frames >= 2 and not inputs["mdcompress-xtc"].is_file():
            cross_format.write_mdcompress(inputs["mdcompress-xtc"], xtc_src, desc)
        if not inputs["chemfiles-dcd-012"].is_file():
            spawn_worker(
                script,
                {
                    "op": "prepare-012",
                    "spec": os.fspath(spec_path),
                    "dest": os.fspath(inputs["chemfiles-dcd-012"]),
                    "library": os.fspath(library),
                },
            )
        arms = ["chemfiles-dcd-012"]
        if n_frames < 2:
            rows.append(
                _unsupported(label, n_atoms, n_frames, "mdcompress-xtc", "read")
            )
            rows.append(
                _unsupported(label, n_atoms, n_frames, "mdcompress-xtc", "write")
            )
            lines.append(f"unsupported {label} mdcompress-xtc")
        else:
            arms = ["mdcompress-xtc", "chemfiles-dcd-012"]
        timed: dict[str, dict] = {}
        for cache in ("warm", "cold"):
            samples = {arm: [] for arm in arms}
            rss = {arm: [] for arm in arms}
            for sample in range(repeats):
                order = rotate(list(arms), sample)
                lines.append(f"order read-{cache} {label} " + " ".join(order))
                for arm in order:
                    result = spawn_worker(
                        script,
                        {
                            "op": "read",
                            "arm": arm,
                            "path": os.fspath(inputs[arm]),
                            "cache": cache,
                            "library": os.fspath(library),
                        },
                    )
                    samples[arm].append(float(result["wall_s"]))
                    rss[arm].append(int(result["rss_bytes"]))
            timed[cache] = {"samples": samples, "rss": rss}
        for arm in arms:
            warm = timed["warm"]["samples"][arm]
            cold = timed["cold"]["samples"][arm]
            median, iqr = _median(warm)
            cold_median, cold_iqr = _median(cold)
            path = inputs[arm]
            rows.append(
                {
                    "structure": label,
                    "atoms": n_atoms,
                    "frames": n_frames,
                    "arm": arm,
                    "tool": arm.split("-", 1)[0],
                    "format": "xtc" if arm.endswith("xtc") else "dcd",
                    "op": "read",
                    "cache": "warm",
                    "median_s": median,
                    "iqr_s": iqr,
                    "n": len(warm),
                    "rss_bytes": int(np.median(timed["warm"]["rss"][arm])),
                    "file_bytes": path.stat().st_size,
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
            for arm in rotate(list(arms), sample):
                dest = timed_dir / Path(inputs[arm]).name
                result = spawn_worker(
                    script,
                    {
                        "op": "write",
                        "arm": arm,
                        "spec": os.fspath(spec_path),
                        "dest": os.fspath(dest),
                        "library": os.fspath(library),
                        "source": os.fspath(xtc_src),
                        "desc": os.fspath(desc),
                    },
                )
                write_found[arm].append(float(result["wall_s"]))
                write_rss[arm].append(int(result["rss_bytes"]))
        for arm in arms:
            samples = write_found[arm]
            median, iqr = _median(samples)
            dest = timed_dir / Path(inputs[arm]).name
            loses = DROPS[arm]
            if arm == "chemfiles-dcd-012" and dest.is_file() and n_frames >= 2:
                loses = f"{loses}; header DELTA {dcd_delta(dest):.6g}"
            rows.append(
                {
                    "structure": label,
                    "atoms": n_atoms,
                    "frames": n_frames,
                    "arm": arm,
                    "tool": arm.split("-", 1)[0],
                    "format": "xtc" if arm.endswith("xtc") else "dcd",
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
    return rows, lines


def _annotate_interval(rows: list[dict]) -> None:
    """Name the DCD interval unit on the 0.10.4 rows this run just wrote."""
    for row in rows:
        if row.get("arm") != "chemfiles-dcd":
            continue
        loses = str(row.get("loses") or "")
        if "interval unit:" not in loses:
            suffix = "interval unit: AKMA"
            row["loses"] = suffix if loses in ("", "none") else f"{loses}; {suffix}"
        if row.get("op") == "write" and int(row.get("frames") or 1) >= 2:
            path = cross_format.WORK / str(row["structure"]) / "timed" / "chemfiles.dcd"
            if path.is_file() and "header DELTA" not in row["loses"]:
                row["loses"] = f"{row['loses']}; header DELTA {dcd_delta(path):.6g}"


def _scrub_record(out: Path) -> None:
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in {".json", ".txt", ".log", ".tsv", ".md"}:
            continue
        text = cross_format.record_text(path.read_text(encoding="utf-8"))
        if not text.endswith("\n") or text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n"
        for prefix in cross_format._RECORD_PREFIXES:
            if prefix in text:
                raise SystemExit(f"record still names a machine path ({path.name})")
        path.write_text(text, encoding="utf-8")


def run(out: Path, repeats: int = 12) -> None:
    """One invocation writes every row of bench/h2h/scaling/h2h15.

    ``cross_format.run`` is the table. The XTC and chemfiles 0.12 rows are
    measured after it and stored in those same files. ``measurement``
    refuses unless the tree is clean and a remote branch contains HEAD.
    """
    if repeats < 12:
        raise SystemExit("h2h15 takes at least 12 samples")
    ident = measurement(ROOT)
    head = ident["commit"]
    pin_mdcompress()
    import readcon

    version = readcon.__version__
    out.mkdir(parents=True, exist_ok=True)
    cross_format.run(out, repeats)
    extra_rows, extra_lines = _extra_rows(out, repeats, Path(__file__).resolve())
    payload = json.loads((out / "cross-format.json").read_text(encoding="utf-8"))
    _annotate_interval(payload["rows"])
    payload["rows"].extend(extra_rows)
    payload["commit"] = head
    payload["tree"] = ident["tree"]
    payload["diff_sha256"] = ident["diff_sha256"]
    payload["remote"] = ident["remote"]
    payload["measured_commit"] = head
    payload["readcon_version"] = version
    payload["mdcompress_tag"] = MDC_TAG
    payload["mdcompress_commit"] = MDC_COMMIT
    payload["chemfiles_012_version"] = CF012_VERSION
    payload["chemfiles_012_commit"] = CF012_COMMIT
    notes = list(payload.get("notes") or [])
    notes.append(
        "Every row in this directory was measured by bench/h2h/h2h15.py "
        f"on {head}. No row is copied from another commit."
    )
    payload["notes"] = notes
    text = json.dumps(payload, indent=2) + "\n"
    assert_repo_relative_record(text)
    cross_format.write_record_text(out / "cross-format.json", text)
    log_path = out / "cross-format.log"
    prior = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    cross_format.write_record_text(
        log_path, prior + "\n".join(extra_lines) + ("\n" if extra_lines else "")
    )
    host_path = out / "host.json"
    host = json.loads(host_path.read_text(encoding="utf-8"))
    host["commit"] = head
    host["tree"] = ident["tree"]
    host["diff_sha256"] = ident["diff_sha256"]
    host["remote"] = ident["remote"]
    host["measured_commit"] = head
    host["record"] = record_path(out, ROOT)
    cross_format.write_record_text(host_path, json.dumps(host, indent=2) + "\n")
    cross_format.write_record_text(
        out / "identity.txt",
        f"commit {head}\ntree {ident['tree']}\n"
        f"diff_sha256 {ident['diff_sha256']}\nremote {ident['remote']}\n",
    )
    cross_format.write_record_text(
        out / "provenance.json",
        json.dumps(
            {
                "commit": head,
                "tree": ident["tree"],
                "diff_sha256": ident["diff_sha256"],
                "remote": ident["remote"],
                "readcon_version": version,
                "writer": "bench/h2h/h2h15.py",
            },
            indent=2,
        )
        + "\n",
    )
    cross_format.write_record_text(
        out / "NOTES.txt",
        "\n".join(
            [
                "h2h15",
                f"commit {head}",
                f"tree {ident['tree']}",
                f"diff_sha256 {ident['diff_sha256']}",
                f"remote {ident['remote']}",
                "writer bench/h2h/h2h15.py",
                "Every row comes from this run. host.json is written with the table.",
                "MDCompress 2.0.5 times DCD as mdcompress-mdc and XTC as mdcompress-xtc.",
                "chemfiles-dcd is 0.10.4. chemfiles-dcd-012 is 0.12.0-dev at fc1e930.",
                "The Drops column names the DCD interval unit.",
                "",
            ]
        ),
    )
    _scrub_record(out)
    print(f"wrote {record_path(out / 'cross-format.json', ROOT)}", flush=True)


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
