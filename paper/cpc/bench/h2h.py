#!/usr/bin/env python3
"""Head-to-head campaigns of the performance section, timed on the readcon-core tree ``READCON_SRC``.

Two trajectories of 10,000 frames of the 218-atom CuH2 slab:

* ``traj_coords.con``: ``resources/test/cuh2.con`` repeated 10,000 times,
  coordinates only, with the plain XYZ, extended XYZ, ASE ``.traj`` and h5py
  ``position/value`` peers that ``benches/headtohead.py`` writes;
* ``traj_vel_206.con``: the 206,095,637-byte velocity trajectory of
  ``benches/make_velocity_campaign.py``, with the plain XYZ and GRO files of the
  same frames.  The script is run a second time and its three outputs must
  equal the first ones byte for byte.

Each CON gets a positions ``.rcbin`` image written by ``examples/peer_time.rs``.
The Python campaign times the calls of ``benches/headtohead.py`` (readcon, h5py
and ASE), each run a fresh ``h2h_child.py``, and captures the memray peak of
each call with the scripts of that file, each capture a fresh interpreter.  The
C++ campaign runs the programs of ``benches/cpp_peer_matrix.py`` (g++ and
clang++ at -O2 and -O3 against chemfiles 0.10.4, built by
``bench/build_chemfiles.sh`` into ``CHEMFILES_BUILDS``), each run a fresh
process that prints its own seconds.  Every campaign goes through the
interleaved rounds of ``interleave.campaign``.  The records, with host paths
replaced as in ``portable.py`` and the provenance of the module and library
that were timed, go to ``BENCH_RESULTS/h2h``.

    python bench/h2h.py                    # payloads, python, cpp
    python bench/h2h.py --steps python     # one step; the payloads must exist
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import interleave  # noqa: E402
import portable  # noqa: E402
import provenance  # noqa: E402

FRAMES = 10000
STEPS = ("payloads", "python", "cpp")
CAMPAIGNS = ("coords", "vel")


def readcon_src() -> Path:
    return Path(os.environ.get("READCON_SRC", "").strip() or provenance.REPO).resolve()


SRC = readcon_src()
WORK = Path(os.environ.get("BENCH_WORK", HERE / "work" / "r0174")) / "h2h"
RESULTS = Path(os.environ.get("BENCH_RESULTS", HERE / "results" / "r0174")) / "h2h"
CHEMFILES = Path(os.environ.get("CHEMFILES_BUILDS", HERE / "work" / "chemfiles"))
# The parallel builds of the campaigns stay out of the tree's target/, whose release library is the default
# build that the probes and the survey load.
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", WORK / "target"))
GXX = os.environ.get("GXX", "/usr/bin/g++")
CLANGXX = os.environ.get("CLANGXX", "/usr/bin/clang++")


def files() -> dict[str, dict[str, Path]]:
    return {
        "coords": {"con": WORK / "traj_coords.con", "rcbin": WORK / "traj_coords.rcbin",
                   "xyz": WORK / "coords" / "traj.xyz", "peers": WORK / "coords"},
        "vel": {"con": WORK / "traj_vel_206.con", "rcbin": WORK / "traj_vel_206.rcbin",
                "xyz": WORK / "traj_vel_206.xyz", "gro": WORK / "traj_vel_206.gro", "peers": WORK / "vel"},
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def cargo_env() -> dict:
    return {**os.environ, "CARGO_TARGET_DIR": str(TARGET)}


def write(name: str, doc: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(portable.portable(doc), indent=2) + "\n")
    print("wrote", path, flush=True)


def velocity_campaign(out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {"con": out / "traj_vel_206.con", "xyz": out / "traj_vel_206.xyz", "gro": out / "traj_vel_206.gro"}
    run([sys.executable, SRC / "benches/make_velocity_campaign.py", "--fixture", SRC / "resources/test/cuh2.con",
         "--out", paths["con"], "--xyz", paths["xyz"], "--gro", paths["gro"]])
    return paths


def payloads() -> None:
    sys.path.insert(0, str(SRC / "benches"))
    import headtohead

    WORK.mkdir(parents=True, exist_ok=True)
    paths = files()
    for campaign in CAMPAIGNS:
        shutil.rmtree(paths[campaign]["peers"], ignore_errors=True)
    fixture = (SRC / "resources/test/cuh2.con").read_bytes()
    con = paths["coords"]["con"]
    with con.open("wb") as handle:
        for _ in range(FRAMES):
            handle.write(fixture)
    headtohead.ensure_peers(con, paths["coords"]["peers"], FRAMES)

    first = velocity_campaign(WORK)
    with tempfile.TemporaryDirectory(prefix="h2h-rerun-", dir=WORK) as tmp:
        second = velocity_campaign(Path(tmp))
        rerun = {kind: filecmp.cmp(first[kind], second[kind], shallow=False) for kind in first}
    if not all(rerun.values()):
        raise SystemExit(f"make_velocity_campaign.py is not byte-reproducible: {rerun}")
    headtohead.ensure_peers(paths["vel"]["con"], paths["vel"]["peers"], FRAMES)

    for campaign in CAMPAIGNS:
        run(["cargo", "run", "--release", "--features", "parallel", "--example", "peer_time", "--",
             paths[campaign]["con"], "1", "rcbin"], cwd=SRC, env=cargo_env())

    manifest: dict = {"frames": FRAMES, "fixture": "resources/test/cuh2.con",
                      "velocity_campaign_rerun_identical": rerun, "files": {}}
    for campaign in CAMPAIGNS:
        for kind, path in paths[campaign].items():
            if kind == "peers":
                continue
            manifest["files"][f"{campaign}.{kind}"] = {"path": str(path), "bytes": path.stat().st_size,
                                                       "sha256": sha256(path)}
        for peer in sorted(paths[campaign]["peers"].glob("traj.*")):
            manifest["files"][f"{campaign}.peer.{peer.suffix[1:]}"] = {
                "path": str(peer), "bytes": peer.stat().st_size, "sha256": sha256(peer)}
    manifest["provenance"] = provenance.record()
    write("payloads.json", manifest)


def child_output(cmd: list) -> dict:
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(str(c) for c in cmd)} exited {proc.returncode}: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def memray_scripts(con: str, rc: str, peers: dict[str, Path], n: int, shape: tuple) -> dict[str, str]:
    """The memray scripts of ``benches/headtohead.py``: one call each, imports included, nothing timed."""
    return {
        "read_con": f"import readcon; assert len(readcon.read_con({con!r}, 1))=={n}\n",
        "read_arrays": ("import readcon\n"
                        f"a=readcon.read_arrays({con!r}, 1, positions_only=True, low_memory=False)\n"
                        f"assert a.positions.shape[0]=={n}\n"),
        "read_arrays_low_memory": ("import readcon\n"
                                   f"a=readcon.read_arrays({con!r}, 1, positions_only=True, low_memory=True)\n"
                                   f"assert a.positions.shape[0]=={n}\n"),
        "h5py_positions": ("import h5py\n"
                           f"a=h5py.File({str(peers['h5'])!r})['position/value'][...]\n"
                           f"assert a.shape[0]=={n}\n"),
        "read_rcbin_owned": ("import readcon\n"
                             f"a=readcon.read_rcbin({rc!r})\n"
                             f"assert a.positions.shape=={shape!r}\n"),
        "ase_traj": ("from ase.io import read\n"
                     f"assert len(read({str(peers['traj'])!r}, index=':'))=={n}\n"),
        "ase_extxyz": ("from ase.io import read\n"
                       f"assert len(read({str(peers['extxyz'])!r}, index=':', format='extxyz'))=={n}\n"),
    }


def memray_capture(script: Path, out: Path):
    def capture() -> dict:
        subprocess.run([sys.executable, "-m", "memray", "run", "-q", "-o", str(out), "-f", "--native", str(script)],
                       stdout=subprocess.DEVNULL, check=True)
        from memray import FileReader

        with FileReader(str(out)) as reader:
            return {"peak_bytes": int(reader.metadata.peak_memory)}
    return capture


def python() -> None:
    sys.path.insert(0, str(SRC / "benches"))
    import headtohead

    import readcon

    paths = files()
    for campaign in CAMPAIGNS:
        con, rc, work = (str(paths[campaign]["con"]), str(paths[campaign]["rcbin"]), paths[campaign]["peers"])
        peers = headtohead.ensure_peers(paths[campaign]["con"], work, FRAMES)
        shape = (FRAMES, len(readcon.read_first_frame(con).atoms), 3)
        calls = ("read_con", "read_arrays", "read_arrays_low_memory", "read_rcbin_owned", "read_rcbin_caller",
                 "h5py_positions", "ase_traj", "ase_extxyz")
        timed = interleave.campaign({
            name: (lambda name=name: child_output([sys.executable, HERE / "h2h_child.py", name, con, rc, work,
                                                   FRAMES]))
            for name in calls})
        with tempfile.TemporaryDirectory(prefix="h2h-memray-") as tmp:
            scripts = {}
            for name, body in memray_scripts(con, rc, peers, FRAMES, shape).items():
                scripts[name] = Path(tmp) / f"{name}.py"
                scripts[name].write_text(body)
            heap = interleave.campaign({name: memray_capture(path, Path(tmp) / f"{name}.bin")
                                        for name, path in scripts.items()}, metric="peak_bytes", suffix="_bytes")
        doc = {
            "campaign": campaign,
            "con": con,
            "con_bytes": paths[campaign]["con"].stat().st_size,
            "rcbin_bytes": paths[campaign]["rcbin"].stat().st_size,
            "peers": {k: {"path": str(v), "bytes": v.stat().st_size} for k, v in peers.items()},
            "timed": "each call once untimed and once timed in a fresh h2h_child.py, from the call until what it "
                     "read is released",
            "protocol": timed["protocol"],
            "hardware": timed["hardware"],
            "timings": timed["cells"],
            "memray_protocol": heap["protocol"],
            "memray": heap["cells"],
            "memray_peak_bytes": {name: int(cell["median_bytes"]) for name, cell in heap["cells"].items()},
            "provenance": provenance.record(),
        }
        write(f"python_{campaign}.json", doc)


# mode of cpp_ratio.cpp, the file it reads, the key of the cell in the record
CPP_MODES = {
    "coords": (("readcon-soa", "con", "readcon_coordinates"), ("readcon-frames", "con", "readcon_frames"),
               ("chemfiles", "xyz", "chemfiles_xyz")),
    "vel": (("readcon-soa", "con", "readcon_coordinates"), ("readcon-frames", "con", "readcon_frames"),
            ("chemfiles", "xyz", "chemfiles_xyz"), ("readcon-soa-all", "con", "readcon_with_velocities"),
            ("readcon-frames-vel", "con", "readcon_frames_with_velocities"), ("chemfiles-vel", "gro", "chemfiles_gro")),
}
# readcon key, chemfiles key, the ratio key of the record
CPP_RATIOS = (("readcon_coordinates", "chemfiles_xyz", "ratio_readcon_over_chemfiles"),
              ("readcon_frames", "chemfiles_xyz", "ratio_frames_over_chemfiles"),
              ("readcon_with_velocities", "chemfiles_gro", "ratio_velocities"),
              ("readcon_frames_with_velocities", "chemfiles_gro", "ratio_frames_velocities"))


def printed_run(binary: Path, mode: str, path: Path):
    def run_once() -> dict:
        proc = subprocess.run([str(binary), mode, str(path)], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise SystemExit(f"{binary.name} {mode} {path.name} exited {proc.returncode}: {proc.stderr[-2000:]}")
        fields = dict(line.split(" ", 1) for line in proc.stdout.splitlines() if " " in line)
        return {"seconds": float(fields["seconds"]), "frames": int(fields["frames"]), "checksum": fields["checksum"]}
    return run_once


def cpp() -> None:
    sys.path.insert(0, str(SRC / "benches"))
    import cpp_peer_matrix as matrix

    run(["cargo", "build", "--release", "--features", "parallel", "--lib"], cwd=SRC, env=cargo_env())
    library = TARGET / "release" / "libreadcon_core.so"
    paths = files()
    drivers = {"gcc": GXX, "clang": CLANGXX}
    gcc_major = subprocess.run([GXX, "-dumpversion"], capture_output=True, text=True,
                               check=True).stdout.strip().split(".")[0]
    rustc = subprocess.run(["rustc", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    profile = (SRC / "Cargo.toml").read_text().split("[profile.release]", 1)[1].split("[", 1)[0].strip()
    for campaign in CAMPAIGNS:
        with tempfile.TemporaryDirectory(prefix="h2h-cpp-") as tmp:
            built, runs = {}, {}
            for name, opt, build_name in matrix.CELLS:
                chem_build = CHEMFILES / build_name
                binary, _ = matrix.build_cell(name, drivers[name], opt, CHEMFILES / "chemfiles-0.10.4", chem_build,
                                              library.parent, Path(tmp), gcc_major)
                built[(name, opt)] = (binary, chem_build)
                for mode, kind, key in CPP_MODES[campaign]:
                    runs[f"{name} {opt} {key}"] = printed_run(binary, mode, paths[campaign][kind])
            record = interleave.campaign(runs)
        cells = []
        for name, opt, _ in matrix.CELLS:
            binary, chem_build = built[(name, opt)]
            cell = {"compiler": name, "cxx": Path(drivers[name]).name,
                    "compiler_version": matrix.compiler_version(drivers[name]), "cxx_flags": [opt, "-std=c++17"],
                    "chemfiles_build_dir": chem_build.name, "chemfiles_cmake_cxx_flags_release": opt,
                    "chemfiles_version": "0.10.4"}
            for _, _, key in CPP_MODES[campaign]:
                summary = record["cells"][f"{name} {opt} {key}"]
                cell[key] = {k: v for k, v in summary.items() if k != "printed"}
                cell[f"{key}_printed"] = summary["printed"]
            for ours, theirs, key in CPP_RATIOS:
                if ours in cell:
                    cell[key] = cell[ours]["median_s"] / cell[theirs]["median_s"]
            if campaign == "vel":
                cell["gro_path"] = str(paths[campaign]["gro"])
                cell["gro_bytes"] = paths[campaign]["gro"].stat().st_size
            cells.append(cell)
        doc = {
            "campaign": campaign,
            "rustc": rustc,
            "cargo_profile_release": profile,
            "readcon_library": str(library),
            "cargo_features": ["parallel"],
            "inputs": {"con_coordinates": str(paths[campaign]["con"]),
                       "con_bytes": paths[campaign]["con"].stat().st_size,
                       "xyz": str(paths[campaign]["xyz"]), "xyz_bytes": paths[campaign]["xyz"].stat().st_size,
                       "frames": cells[0]["readcon_coordinates_printed"]["frames"]},
            "timed_readcon_call": "readcon::CoordinateBlocks::read(path, 1, positions_only=true) then sum of x",
            "timed_readcon_frames_call": "readcon::ConFrameIterator, one frame at a time, sum of x of each frame",
            "timed_chemfiles_call": "chemfiles::Trajectory::read every step, sum of positions[][0]",
            "protocol": record["protocol"],
            "hardware": record["hardware"],
            "cells": cells,
            "provenance": {"library": provenance.binary_build(library), "host": provenance.host()},
        }
        write(f"cpp_{campaign}.json", doc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--steps", default=",".join(STEPS), help="comma-separated subset of " + ", ".join(STEPS))
    args = parser.parse_args()
    steps = [s for s in args.steps.split(",") if s]
    unknown = sorted(set(steps) - set(STEPS))
    if unknown:
        raise SystemExit(f"unknown steps {unknown}")
    if shutil.which("cargo") is None:
        raise SystemExit("cargo is not on PATH")
    if provenance.library_digest(SRC) != provenance.library_digest():
        raise SystemExit(f"{SRC} holds other library sources than {provenance.REPO}, whose digest the records name")
    if "payloads" in steps:
        payloads()
    if "python" in steps:
        python()
    if "cpp" in steps:
        cpp()


if __name__ == "__main__":
    main()
