#!/usr/bin/env python3
"""Native binary trajectory readers against readcon-core on one system, timed on the readcon-core tree ``READCON_SRC``.

The system of ``bench/binary_formats/system.h`` is 1,000,000 atoms in 10
frames.  ``gen.c`` writes it once in binary64 (``reference.f64`` and
``reference_box.f64``) and once through the writer of each binary format: XTC
and TRR by xdrfile 1.1.4, DCD by the molfile DCD code that MDAnalysis vendors,
TNG by the TNG library.  ``readcon_read.rs`` writes the CON files from
``reference.f64`` with the readcon-core writer, in shortest round-trip binary64,
with six decimals and with two, and the ``.rcbin`` positions image of the
round-trip CON.  Six decimals hold more than the binary32 of TRR and DCD, and
two decimals, 0.01 angstrom, the 0.001 nm of XTC and TNG.

Every reader is a driver of ``bench/binary_formats`` that times, in a fresh
process, the open, the read of every frame and the release (``bf_driver.h``).
``frames`` reads one frame at a time into a buffer the next frame reuses;
``all`` holds every frame in its own buffer until the read ends.  readcon-core
adds ``columns`` (``read_soa_path`` of the positions) and ``image``
(``read_rcbin``).

Steps, each writing one record to ``BENCH_RESULTS/binary_formats``:

* ``build``: fetch the pinned sources of ``SOURCES`` and ``MOLFILE`` into
  ``BENCH_WORK/binary_formats`` and check their SHA-256, build the libraries and
  drivers with the flags below, and build ``readcon_read`` in a generated crate
  with the release profile and ``Cargo.lock`` of ``READCON_SRC``; every locked
  version must be the library's (``build.json``);
* ``payloads``: write every file twice; the second run must give the bytes of
  the first (``payloads.json``);
* ``check``: read every file with every reader into binary64 angstrom and
  compare it with ``reference.f64`` against the tolerance of its format; read
  libxtc's test file ``tests/data/pep.xtc`` with libxtc, xdrfile and
  MDAnalysis, and a TNG file of two frame sets with both TNG readers
  (``checks.json``);
* ``time``: the interleaved rounds of ``interleave.campaign`` over every cell,
  each run a fresh process that prints the frame count, atom count and
  checksum of the check run, after ``interleave.settle`` has kept every CPU
  busy for the ``settle_ms`` of ``settle.json``, which
  ``bench/settle_period.py`` measures on the host (``timings.json``).

    python bench/binary_formats.py                 # build, payloads, check, time
    python bench/binary_formats.py --steps time    # one step; the steps before it must have run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import portable  # noqa: E402
import provenance  # noqa: E402


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


STEPS = ("build", "payloads", "check", "time")
DRIVERS = HERE / "binary_formats"


def readcon_src() -> Path:
    return Path(os.environ.get("READCON_SRC", "").strip() or provenance.REPO).resolve()


SRC = readcon_src()
WORK = Path(os.environ.get("BENCH_WORK", HERE / "work" / "r0174")) / "binary_formats"
RESULTS = (
    Path(os.environ.get("BENCH_RESULTS", HERE / "results" / "r0174")) / "binary_formats"
)
GCC = os.environ.get("GCC", "/usr/bin/gcc")
GXX = os.environ.get("GXX", "/usr/bin/g++")
BUILD = WORK / "build"
BIN = BUILD / "bin"
PAYLOADS = WORK / "payloads"

SOURCES = {
    "xdrfile": {
        "release": "1.1.4",
        "url": "https://ftp.gromacs.org/pub/contrib/xdrfile-1.1.4.tar.gz",
        "sha256": "e3c587c5ff24441a092fe2f3bc1dc03667bf126558f437161e779bfbcce48022",
        "dir": "xdrfile-1.1.4",
    },
    "libxtc": {
        "commit": "58f40e1e9d392ec607e775772658eb1b748be549",
        "url": "https://gitlab.com/impulse_md/libxtc/-/archive/58f40e1e9d392ec607e775772658eb1b748be549/"
        "libxtc-58f40e1e9d392ec607e775772658eb1b748be549.tar.gz",
        "sha256": "6352f6f63ca337376e1b18b6610c3c29ccc1661fe50fc56064fe361bc555f421",
        "dir": "libxtc-58f40e1e9d392ec607e775772658eb1b748be549",
    },
    "tng": {
        "commit": "14dd68ff46df1ef1cf2d9bcc1f4f5bddb974ce1c",
        "url": "https://codeload.github.com/gromacs/tng/tar.gz/14dd68ff46df1ef1cf2d9bcc1f4f5bddb974ce1c",
        "sha256": "f29e74753ab005133eca0e0a8676549579e6f28d09fe54b2593b2fa285ef5d5b",
        "dir": "tng-14dd68ff46df1ef1cf2d9bcc1f4f5bddb974ce1c",
    },
}
MOLFILE = {
    "commit": "ae9ff4b738606ba1e7c18a8a9b99a8a87eb69f74",
    "url": "https://raw.githubusercontent.com/MDAnalysis/mdanalysis/ae9ff4b738606ba1e7c18a8a9b99a8a87eb69f74/"
    "package/MDAnalysis/lib/formats/include/",
    "files": {
        "readdcd.h": "d3c6ecf3bc46e11cfe4d9328e5dba3b72b23ef2e916a6a6c2f0aadfbf877b6c3",
        "fastio.h": "9dcd75ddabebd5387de04bbd1befbbd61e199658c3a58f7aa6aea25afb763ac0",
        "endianswap.h": "c06034ca21ed28017eb50f6455d646a41d79d9adb78b44deb9e2bca25f35b44f",
    },
}

C_FLAGS = ["-O3", "-DNDEBUG"]
# The flags libxtc's setup.py passes on Linux when the compiler takes them; build() checks each is in setup.py.
LIBXTC_FLAGS = [
    "-O3",
    "-fopenmp",
    "-DHAS_INT128",
    "-fno-exceptions",
    "-fno-rtti",
    "-ffast-math",
    "-std=c++11",
    "-fvisibility=hidden",
    "-fvisibility-inlines-hidden",
    "-march=native",
]
# TNG's CMake build defines USE_STD_INTTYPES_H where inttypes.h exists.
TNG_FLAGS = ["-DUSE_STD_INTTYPES_H"]

# CON file: the decimals the readcon-core writer prints, None for its shortest round trip
CON_FILES = {"traj.con": None, "traj_six.con": 6, "traj_two.con": 2}
# The largest |read - reference| in angstrom each file may give for positions and box lengths: the quantization of
# the format plus the binary32 rounding of values below 512 angstrom (51.2 nm), rounded up; DCD stores the box in
# binary64, and a CON file with decimals rounds to half a unit of the last one.
TOLERANCE = {
    **{
        name: (0.0, 0.0) if d is None else (0.5 * 10.0**-d + 2.0**-40,) * 2
        for name, d in CON_FILES.items()
    },
    "traj.rcbin": (0.0, 0.0),
    "traj.trr": (2e-5, 2e-5),
    "traj.dcd": (2e-5, 0.0),
    "traj.xtc": (5.2e-3, 2e-5),
    "traj.tng": (5.2e-3, 2e-5),
}
# name: driver, mode, threads, file
CELLS = {
    "readcon-frames": ("readcon_read", "frames", 1, "traj.con"),
    "readcon-frames-six": ("readcon_read", "frames", 1, "traj_six.con"),
    "readcon-frames-two": ("readcon_read", "frames", 1, "traj_two.con"),
    "readcon-all": ("readcon_read", "all", 1, "traj.con"),
    "readcon-all-six": ("readcon_read", "all", 1, "traj_six.con"),
    "readcon-all-two": ("readcon_read", "all", 1, "traj_two.con"),
    "readcon-all-8": ("readcon_read", "all", 8, "traj.con"),
    "readcon-all-six-8": ("readcon_read", "all", 8, "traj_six.con"),
    "readcon-all-two-8": ("readcon_read", "all", 8, "traj_two.con"),
    "readcon-columns": ("readcon_read", "columns", 1, "traj.con"),
    "readcon-columns-six": ("readcon_read", "columns", 1, "traj_six.con"),
    "readcon-columns-two": ("readcon_read", "columns", 1, "traj_two.con"),
    "readcon-image": ("readcon_read", "image", 1, "traj.rcbin"),
    "xdrfile-xtc-frames": ("read_xdrfile", "frames", 1, "traj.xtc"),
    "xdrfile-xtc-all": ("read_xdrfile", "all", 1, "traj.xtc"),
    "xdrfile-trr-frames": ("read_xdrfile", "frames", 1, "traj.trr"),
    "xdrfile-trr-all": ("read_xdrfile", "all", 1, "traj.trr"),
    "libxtc-frames": ("read_libxtc", "frames", 1, "traj.xtc"),
    "libxtc-all": ("read_libxtc", "all", 1, "traj.xtc"),
    "libxtc-frames-8": ("read_libxtc", "frames", 8, "traj.xtc"),
    "libxtc-all-8": ("read_libxtc", "all", 8, "traj.xtc"),
    "molfile-dcd-frames": ("read_dcd", "frames", 1, "traj.dcd"),
    "molfile-dcd-all": ("read_dcd", "all", 1, "traj.dcd"),
    "tng-frames": ("read_tng", "frames", 1, "traj.tng"),
    "tng-all": ("read_tng", "all", 1, "traj.tng"),
}
GENERATED = (
    "reference.f64",
    "reference_box.f64",
    "traj.xtc",
    "traj.trr",
    "traj.dcd",
    "traj.tng",
    "traj_two_sets.tng",
)
WRITTEN = (*CON_FILES, "traj.rcbin")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def stamp() -> dict:
    """The provenance block of a record: the ``readcon_read`` build, the library version it was built from, and
    the host."""
    version = tomllib.loads((SRC / "Cargo.toml").read_text())["package"]["version"]
    return {
        "build": {
            **provenance.binary_build(BIN / "readcon_read"),
            "readcon_version": version,
        },
        "host": provenance.host(),
    }


def write(name: str, doc: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(portable.portable(doc), indent=2) + "\n")
    print("wrote", path, flush=True)


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


def first_line(cmd: list[str]) -> str:
    return (
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        .stdout.splitlines()[0]
        .strip()
    )


def fetch(url: str, expected: str, out: Path) -> None:
    if not (out.is_file() and sha256(out) == expected):
        out.parent.mkdir(parents=True, exist_ok=True)
        print("fetch", url, flush=True)
        with (
            urllib.request.urlopen(url, timeout=120) as response,
            out.open("wb") as handle,
        ):
            shutil.copyfileobj(response, handle)
    found = sha256(out)
    if found != expected:
        raise SystemExit(f"{url}: SHA-256 {found}, pinned {expected}")


def sources() -> dict[str, Path]:
    """Fetch and unpack the pinned sources; the directory of each, and ``molfile`` for the DCD headers."""
    downloads, unpacked = WORK / "downloads", WORK / "src"
    roots = {}
    for name, pin in SOURCES.items():
        archive = downloads / f"{pin['dir']}.tar.gz"
        fetch(pin["url"], pin["sha256"], archive)
        root = unpacked / pin["dir"]
        shutil.rmtree(root, ignore_errors=True)
        unpacked.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(unpacked, filter="data")
        roots[name] = root
    molfile = unpacked / f"molfile-{MOLFILE['commit']}"
    for header, expected in MOLFILE["files"].items():
        fetch(MOLFILE["url"] + header, expected, molfile / header)
    roots["molfile"] = molfile
    return roots


def tng_version(root: Path) -> dict[str, str]:
    """The version fields of BuildTNG.cmake that its version.h.in names."""
    text = (root / "BuildTNG.cmake").read_text()
    fields = {
        key: re.search(rf'set\({key} "([^"]+)"\)', text).group(1)
        for key in (
            "TNG_MAJOR_VERSION",
            "TNG_MINOR_VERSION",
            "TNG_VERSION_PATCH_LEVEL",
            "TNG_API_VERSION",
        )
    }
    fields["TNG_IO_VERSION"] = (
        "{TNG_MAJOR_VERSION}.{TNG_MINOR_VERSION}.{TNG_VERSION_PATCH_LEVEL}".format(
            **fields
        )
    )
    return fields


def compile_steps(roots: dict[str, Path]) -> list[tuple[str, list]]:
    """(output, command) of every library, object and driver, in build order."""
    xdr, tng, lx, mol = (
        roots["xdrfile"],
        roots["tng"],
        roots["libxtc"] / "libxtc",
        roots["molfile"],
    )
    obj = BUILD / "obj"
    steps: list[tuple[str, list]] = []
    xdr_objs = []
    for name in ("xdrfile", "xdrfile_xtc", "xdrfile_trr"):
        out = obj / f"{name}.o"
        steps.append(
            (
                out.name,
                [
                    GCC,
                    *C_FLAGS,
                    "-I",
                    xdr / "include",
                    "-c",
                    xdr / "src" / f"{name}.c",
                    "-o",
                    out,
                ],
            )
        )
        xdr_objs.append(out)
    steps.append(("libxdrfile.a", ["ar", "rcs", BUILD / "libxdrfile.a", *xdr_objs]))
    tng_sources = sorted((tng / "src" / "compression").glob("*.c")) + [
        tng / "src/lib/tng_io.c",
        tng / "src/lib/md5.c",
    ]
    tng_objs = []
    for source in tng_sources:
        out = obj / f"tng_{source.stem}.o"
        steps.append(
            (
                out.name,
                [
                    GCC,
                    *C_FLAGS,
                    *TNG_FLAGS,
                    "-I",
                    tng / "include",
                    "-I",
                    BUILD / "include",
                    "-c",
                    source,
                    "-o",
                    out,
                ],
            )
        )
        tng_objs.append(out)
    steps.append(("libtng_io.a", ["ar", "rcs", BUILD / "libtng_io.a", *tng_objs]))
    kernel = obj / "xtc_unpack.o"
    steps.append(
        (kernel.name, [GXX, *LIBXTC_FLAGS, "-c", lx / "xtc_unpack.cpp", "-o", kernel])
    )
    include = ["-I", DRIVERS]
    steps += [
        (
            "gen",
            [
                GCC,
                *C_FLAGS,
                "-ffp-contract=off",
                *TNG_FLAGS,
                *include,
                "-I",
                xdr / "include",
                "-I",
                tng / "include",
                "-I",
                BUILD / "include",
                "-I",
                mol,
                DRIVERS / "gen.c",
                BUILD / "libxdrfile.a",
                BUILD / "libtng_io.a",
                "-Wl,--wrap=time",
                "-lz",
                "-lm",
                "-o",
                BIN / "gen",
            ],
        ),
        (
            "read_xdrfile",
            [
                GCC,
                *C_FLAGS,
                *include,
                "-I",
                xdr / "include",
                DRIVERS / "read_xdrfile.c",
                BUILD / "libxdrfile.a",
                "-lm",
                "-o",
                BIN / "read_xdrfile",
            ],
        ),
        (
            "read_dcd",
            [
                GCC,
                *C_FLAGS,
                *include,
                "-I",
                mol,
                DRIVERS / "read_dcd.c",
                "-o",
                BIN / "read_dcd",
            ],
        ),
        (
            "read_tng",
            [
                GCC,
                *C_FLAGS,
                *TNG_FLAGS,
                *include,
                "-I",
                tng / "include",
                "-I",
                BUILD / "include",
                DRIVERS / "read_tng.c",
                BUILD / "libtng_io.a",
                "-lz",
                "-lm",
                "-o",
                BIN / "read_tng",
            ],
        ),
        (
            "read_libxtc",
            [
                GXX,
                *C_FLAGS,
                "-std=c++11",
                "-fopenmp",
                *include,
                "-I",
                lx,
                DRIVERS / "read_libxtc.cpp",
                kernel,
                "-o",
                BIN / "read_libxtc",
            ],
        ),
    ]
    return steps


def readcon_manifest() -> str:
    """Cargo.toml of the readcon_read crate: the edition and release profile of READCON_SRC, its library by path."""
    library = tomllib.loads((SRC / "Cargo.toml").read_text())
    profile = library.get("profile", {}).get("release", {})
    lines = [
        "[package]",
        'name = "binary-formats-readcon"',
        'version = "0.0.0"',
        f'edition = "{library["package"]["edition"]}"',
        "publish = false",
        "",
        "[[bin]]",
        'name = "readcon_read"',
        f"path = {json.dumps(str(DRIVERS / 'readcon_read.rs'))}",
        "",
        "[dependencies]",
        f'readcon-core = {{ path = {json.dumps(str(SRC))}, features = ["parallel"] }}',
        "",
        "[profile.release]",
        *(f"{key} = {json.dumps(value)}" for key, value in profile.items()),
        "",
        "[workspace]",
        "",
    ]
    return "\n".join(lines)


def locked(path: Path) -> dict[str, tuple]:
    return {
        f"{p['name']} {p['version']}": (p.get("source"), p.get("checksum"))
        for p in tomllib.loads(path.read_text())["package"]
    }


def build_readcon() -> dict:
    crate = WORK / "readcon_read"
    crate.mkdir(parents=True, exist_ok=True)
    manifest = readcon_manifest()
    (crate / "Cargo.toml").write_text(manifest)
    shutil.copyfile(SRC / "Cargo.lock", crate / "Cargo.lock")
    run(
        ["cargo", "build", "--release"],
        cwd=crate,
        env={**os.environ, "CARGO_TARGET_DIR": str(WORK / "target")},
    )
    library, driver = locked(SRC / "Cargo.lock"), locked(crate / "Cargo.lock")
    driver.pop("binary-formats-readcon 0.0.0")
    other = sorted(name for name in driver if driver[name] != library.get(name))
    if other:
        raise SystemExit(
            f"readcon_read locks other packages than {SRC / 'Cargo.lock'}: {other}"
        )
    binary = WORK / "target" / "release" / "readcon_read"
    shutil.copy2(binary, BIN / "readcon_read")
    return {
        "manifest": manifest,
        "command": ["cargo", "build", "--release"],
        "locked_packages": len(driver),
        "locked_as_library": True,
    }


def build() -> None:
    roots = sources()
    setup = (roots["libxtc"] / "setup.py").read_text()
    absent = [flag for flag in LIBXTC_FLAGS if flag not in setup]
    if absent:
        raise SystemExit(f"libxtc setup.py names none of {absent}")
    shutil.rmtree(BUILD, ignore_errors=True)
    for sub in ("obj", "bin", "include/tng"):
        (BUILD / sub).mkdir(parents=True)
    version = tng_version(roots["tng"])
    text = (roots["tng"] / "include/tng/version.h.in").read_text()
    for key, value in version.items():
        text = text.replace(f"@{key}@", value)
    (BUILD / "include/tng/version.h").write_text(text)
    commands = {}
    for out, cmd in compile_steps(roots):
        run(cmd)
        commands[out] = [Path(c).name if c in (GCC, GXX) else str(c) for c in cmd]
    readcon = build_readcon()
    binaries = {
        name: {"sha256": sha256(BIN / name)}
        for name in sorted(p.name for p in BIN.iterdir())
    }
    write(
        "build.json",
        {
            "sources": {**SOURCES, "molfile": MOLFILE},
            "tng_version_h": version,
            "compilers": {
                "gcc": first_line([GCC, "--version"]),
                "g++": first_line([GXX, "--version"]),
                "rustc": first_line(["rustc", "--version"]),
                "cargo": first_line(["cargo", "--version"]),
            },
            "flags": {"c": C_FLAGS, "libxtc_kernel": LIBXTC_FLAGS, "tng": TNG_FLAGS},
            "commands": commands,
            "readcon_read": readcon,
            "binaries": binaries,
            "provenance": stamp(),
        },
    )


def system() -> dict:
    """The parameters system.h defines."""
    text = (DRIVERS / "system.h").read_text()
    value = {
        name: re.search(rf"#define {name} (\S+)", text).group(1)
        for name in ("BF_SIDE", "BF_FRAMES", "BF_SPACING", "BF_JITTER")
    }
    side = int(value["BF_SIDE"])
    return {
        "side": side,
        "atoms": side**3,
        "frames": int(value["BF_FRAMES"]),
        "spacing_A": float(value["BF_SPACING"]),
        "jitter_A": float(value["BF_JITTER"]),
    }


def write_payloads(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    run([BIN / "gen", out])
    readcon = BIN / "readcon_read"
    for name, decimals in CON_FILES.items():
        run(
            [
                readcon,
                "write-con",
                out / "reference.f64",
                out / "reference_box.f64",
                out / name,
                "roundtrip" if decimals is None else decimals,
            ]
        )
    run([readcon, "write-rcbin", out / "traj.con", out / "traj.rcbin"])


def writers() -> dict:
    """The precision in nm that gen.c gives the XTC and TNG writers, and the decimals of each CON file."""
    gen = (DRIVERS / "gen.c").read_text()
    xtc = re.search(r"write_xtc\(.*,\s*([\d.]+)f\)", gen).group(1)
    tng = re.search(r"tng_compression_precision_set\(\w+,\s*([\d.]+)\)", gen).group(1)
    return {
        "xtc_precision_nm": 1 / float(xtc),
        "tng_precision_nm": 1 / float(tng),
        "con_decimals": CON_FILES,
    }


def payloads() -> None:
    shutil.rmtree(PAYLOADS, ignore_errors=True)
    write_payloads(PAYLOADS)
    files, identical = {}, {}
    with bench_scratch("scratch") as tmp:
        write_payloads(Path(tmp))
        for name in (*GENERATED, *WRITTEN):
            path = PAYLOADS / name
            files[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
            identical[name] = sha256(Path(tmp) / name) == files[name]["sha256"]
    if not all(identical.values()):
        raise SystemExit(f"the payloads do not rerun byte for byte: {identical}")
    write(
        "payloads.json",
        {
            "system": system(),
            "writers": writers(),
            "files": files,
            "rerun_identical": identical,
            "provenance": stamp(),
        },
    )


def summary(stdout: str) -> dict:
    fields = dict(line.split(" ", 1) for line in stdout.splitlines() if " " in line)
    return {
        "seconds": float(fields["seconds"]),
        "frames": int(fields["frames"]),
        "atoms": int(fields["atoms"]),
        "checksum": fields["checksum"],
    }


def dump(
    driver: str, mode: str, threads: int, path: Path, tmp: Path
) -> tuple[dict, np.ndarray, np.ndarray]:
    pos, box = tmp / "positions.f64", tmp / "box.f64"
    proc = run(
        [BIN / driver, "dump", mode, threads, path, pos, box],
        capture_output=True,
        text=True,
    )
    printed = summary(proc.stdout)
    del printed["seconds"]
    return printed, np.fromfile(pos), np.fromfile(box)


def compared(got: np.ndarray, ref: np.ndarray) -> float | None:
    return float(np.abs(got - ref).max()) if got.shape == ref.shape else None


def libxtc_pep(root: Path, tmp: Path) -> dict:
    """libxtc against xdrfile and MDAnalysis on libxtc's own test file, and against the pep.npy its tests use."""
    from MDAnalysis.lib.formats.libmdaxdr import XTCFile

    import MDAnalysis

    data = root / "tests" / "data"
    reference = np.load(data / "pep.npy").astype(np.float64)
    frames, atoms = reference.shape[:2]
    with XTCFile(str(data / "pep.xtc")) as xtc:
        mda = np.stack([xtc.read().x.astype(np.float64) for _ in range(len(xtc))])
    out = {
        "file": "tests/data/pep.xtc",
        "frames": frames,
        "atoms": atoms,
        "mdanalysis": MDAnalysis.__version__,
    }
    for driver in ("read_libxtc", "read_xdrfile"):
        _, pos, _ = dump(driver, "frames", 1, data / "pep.xtc", tmp)
        nm = pos.reshape(frames, atoms, 3) / 10.0
        bad = np.abs(nm - mda).max(axis=2) > 1e-6
        out[driver] = {
            "max_nm_from_pep_npy": float(np.abs(nm - reference).max()),
            "max_nm_from_mdanalysis": float(np.abs(nm - mda).max()),
            "atoms_off_mdanalysis": int(bad.sum()),
            "first_off": [int(i) for i in np.argwhere(bad)[0]] if bad.any() else None,
        }
    return out


def tng_two_sets(tmp: Path) -> dict:
    """Both TNG readers on traj_two_sets.tng, the frames of traj.tng in two frame sets."""
    ref = np.fromfile(PAYLOADS / "reference.f64")
    out = {"file": "traj_two_sets.tng", "frames_per_set": system()["frames"] // 2}
    for mode in ("frames", "all"):
        pos, box = tmp / "positions.f64", tmp / "box.f64"
        proc = subprocess.run(
            [
                str(BIN / "read_tng"),
                "dump",
                mode,
                "1",
                str(PAYLOADS / "traj_two_sets.tng"),
                str(pos),
                str(box),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        result: dict = {"returncode": proc.returncode}
        if proc.returncode == 0:
            result["max_position_error_A"] = compared(np.fromfile(pos), ref)
        out[mode] = result
    return out


def check() -> None:
    ref = np.fromfile(PAYLOADS / "reference.f64")
    ref_box = np.fromfile(PAYLOADS / "reference_box.f64")
    sysdef = system()
    cells = {}
    with bench_scratch("scratch") as tmp:
        for name, (driver, mode, threads, file) in CELLS.items():
            printed, pos, box = dump(driver, mode, threads, PAYLOADS / file, Path(tmp))
            pos_err, box_err = compared(pos, ref), compared(box, ref_box)
            pos_tol, box_tol = TOLERANCE[file]
            ok = (
                printed["frames"] == sysdef["frames"]
                and printed["atoms"] == sysdef["atoms"]
                and pos_err is not None
                and box_err is not None
                and pos_err <= pos_tol
                and box_err <= box_tol
            )
            off = None
            if pos.shape == ref.shape:
                off = int(
                    (np.abs(pos - ref).reshape(-1, 3).max(axis=1) > pos_tol).sum()
                )
            cells[name] = {
                "driver": driver,
                "mode": mode,
                "threads": threads,
                "file": file,
                "printed": printed,
                "max_position_error_A": pos_err,
                "max_box_error_A": box_err,
                "position_tolerance_A": pos_tol,
                "box_tolerance_A": box_tol,
                "atom_positions_beyond_tolerance": off,
                "passes": ok,
            }
        pep = libxtc_pep(WORK / "src" / SOURCES["libxtc"]["dir"], Path(tmp))
        sets = tng_two_sets(Path(tmp))
    write(
        "checks.json",
        {
            "system": sysdef,
            "cells": cells,
            "libxtc_pep": pep,
            "tng_two_sets": sets,
            "provenance": stamp(),
        },
    )


def timed_run(driver: str, mode: str, threads: int, file: str):
    def run_once() -> dict:
        proc = subprocess.run(
            [str(BIN / driver), "time", mode, str(threads), str(PAYLOADS / file)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"{driver} time {mode} {file} exited {proc.returncode}: {proc.stderr[-2000:]}"
            )
        return summary(proc.stdout)

    return run_once


def time_cells() -> None:
    import interleave

    checks = load("checks.json")["cells"]
    settle = load("settle.json")
    record = interleave.campaign(
        {name: timed_run(*cell) for name, cell in CELLS.items()},
        settle_ms=settle["settle_ms"],
    )
    cells = {}
    for name, (driver, mode, threads, file) in CELLS.items():
        cell = record["cells"][name]
        if cell["printed"] != checks[name]["printed"]:
            raise SystemExit(
                f"{name}: timed runs print {cell['printed']}, the check run {checks[name]['printed']}"
            )
        cells[name] = {
            "driver": driver,
            "mode": mode,
            "threads": threads,
            "file": file,
            "passes_check": checks[name]["passes"],
            **cell,
        }
    write(
        "timings.json",
        {
            "protocol": {
                **record["protocol"],
                "timed": "open, read of every frame and release, in the driver",
                "settle_sha256": sha256(RESULTS / "settle.json"),
            },
            "hardware": record["hardware"],
            "cells": cells,
            "provenance": stamp(),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--steps",
        default=",".join(STEPS),
        help="comma-separated subset of " + ", ".join(STEPS),
    )
    args = parser.parse_args()
    steps = [s for s in args.steps.split(",") if s]
    unknown = sorted(set(steps) - set(STEPS))
    if unknown:
        raise SystemExit(f"unknown steps {unknown}")
    if shutil.which("cargo") is None:
        raise SystemExit("cargo is not on PATH")
    if provenance.library_digest(SRC) != provenance.library_digest():
        raise SystemExit(
            f"{SRC} holds other library sources than {provenance.REPO}, whose digest the records name"
        )
    if "build" in steps:
        build()
    if "payloads" in steps:
        payloads()
    if "check" in steps:
        check()
    if "time" in steps:
        time_cells()


if __name__ == "__main__":
    main()
