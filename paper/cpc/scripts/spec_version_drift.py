#!/usr/bin/env python3
"""Give one file to several readers that all claim CON 3.1.

readcon-core 0.17.0, 0.17.1, 0.17.2 and the version in Cargo.toml ship the CON 3.1 text. This script
gives the same probe files to each published readcon wheel and records the
verdicts, so a behaviour change between releases is a measurement and not a
claim. For every probe that splits the readers, the record names the release
at which each change landed: the first reader, in the order given, whose
outcome differs from the reader before it.

Each wheel is unpacked into its own directory and read in a subprocess, because
the binding is a compiled extension and only one copy can be imported per
process. A reader is a wheel file or a directory that holds an unpacked wheel.

    python3 paper/cpc/scripts/spec_version_drift.py \
        --reader 0.17.0=readcon-0.17.0-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
        --reader 0.17.1=readcon-0.17.1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
        --reader 0.17.2=readcon-0.17.2-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl \
        --reader <version>=readcon-<version>-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl

Writes data/spec/version_drift.json, with the releases of the wheels under
measures_release and the build and host that ran the probes under
provenance; --out DIR writes it to DIR.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_class import classify  # noqa: E402


_repo = next(
    _p for _p in Path(__file__).resolve().parents if (_p / "readcon_bench.py").is_file()
)
__import__("sys").path.insert(0, str(_repo))
_BENCH = __import__("readcon_bench")
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "spec"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")

CELL = "10 10 10\n90 90 90\n"
COORD = "1\n1\n1\nH\nCoordinates of Component 1\n0 0 0 0 0\n"
VELOCITY = "\nH\nVelocities of Component 1\n0.1 0.2 0.3 0 0\n"


def frame(line1: str = "PRE", line2: str = '{"con_spec_version":2}') -> str:
    return f"{line1}\n{line2}\n{CELL}\n\n{COORD}"


PROBES = {
    "one frame, empty line 1": frame(line1=""),
    "two frames, empty line 1 on both": frame(line1="") + frame(line1=""),
    "two frames, empty line 1 on the second": frame() + frame(line1=""),
    "one frame, empty line 2": frame(line2=""),
    "one frame, empty lines 1 and 2": frame(line1="", line2=""),
    "two frames, filled headers": frame() + frame(),
    "legacy velocity block": frame() + VELOCITY,
    "legacy velocity block, label in capitals": frame()
    + VELOCITY.replace("Velocities of Component", "VELOCITIES OF COMPONENT"),
    "legacy velocity block, label words separated by tabs": frame()
    + VELOCITY.replace("Velocities of Component", "Velocities\tof\tComponent"),
    "legacy velocity block, blank symbol line": frame()
    + VELOCITY.replace("\nH\n", "\n  \n"),
    "legacy velocity block, symbol line starting with {": frame()
    + VELOCITY.replace("\nH\n", "\n{H\n"),
}

CHILD = r"""
import json, sys
import readcon
probes = json.load(sys.stdin)
out = {}
for name, text in probes.items():
    try:
        out[name] = {"verdict": "accept", "frames": len(readcon.read_con_string(text))}
    except Exception as exc:
        out[name] = {"verdict": "reject", "message": str(exc)}
out["__version__"] = getattr(readcon, "__version__", "unknown")
json.dump(out, sys.stdout)
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_labeled(spec: str, *, option: str) -> tuple[str, Path]:
    label, sep, raw = spec.partition("=")
    if sep == "" or not label or not raw:
        raise SystemExit(f"{option} must be VERSION=PATH, got {spec!r}")
    if VERSION.fullmatch(label) is None:
        raise SystemExit(f"{option} version must match X.Y.Z, got {label!r}")
    return label, Path(raw)


def reader_module_sha(path: Path, label: str) -> str:
    module = sorted((path / "readcon").glob("readcon*.so"))
    if not module:
        raise SystemExit(f"reader {label!r} has no readcon*.so in {path}")
    return sha256(module[0])


def ask(libdir: Path, probes: dict[str, str]) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", CHILD],
        input=json.dumps(probes),
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(libdir), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    out = json.loads(proc.stdout)
    for name in probes:
        if out[name]["verdict"] == "reject":
            out[name]["class"] = classify(Exception(out[name]["message"]))[0]
    return out


def outcome(entry: dict) -> str:
    return (
        f"accept {entry['frames']}"
        if entry["verdict"] == "accept"
        else f"reject {entry['class']}"
    )


def landed(results: dict, labels: list[str], name: str) -> list[dict]:
    return [
        {
            "release": cur,
            "from": outcome(results[prev][name]),
            "to": outcome(results[cur][name]),
        }
        for prev, cur in zip(labels, labels[1:])
        if outcome(results[prev][name]) != outcome(results[cur][name])
    ]


def ensure_published_clean(root: Path) -> str:
    """The HEAD a remote branch contains. A dirty checkout is refused."""
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "bench" / "h2h"))
    import measured_commit

    return str(measured_commit.measurement(root)["commit"])


def require_installed_module(module: Path | None) -> Path:
    if module is None:
        raise SystemExit("the readcon module was not found; rebuild it")
    return module


def refuse_stale_module(newer: list[str]) -> None:
    """A module older than a library file was not built from this tree."""
    if newer:
        raise SystemExit(
            f"the readcon module is older than {', '.join(newer[:3])}; rebuild it"
        )


def seed_from_record(
    path: Path,
) -> tuple[list[str], dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Readers, outcomes, source hashes, and per-reader measurements from a record."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    readers = list(payload.get("readers") or [])
    if not readers:
        raise SystemExit(f"seed record has no readers: {path}")
    probes = payload.get("probes") or {}
    probe_text = payload.get("probe_text") or {}
    expected_names = set(PROBES)
    if set(probes) != expected_names:
        raise SystemExit("seed record probe names drift from this script's probes")
    if set(probe_text) != expected_names:
        raise SystemExit("seed record probe_text names drift from this script's probes")
    for name, expected in PROBES.items():
        seeded = probe_text.get(name)
        if not isinstance(seeded, str):
            raise SystemExit(f"seed record probe_text[{name!r}] is not a string")
        if text_sha256(seeded) != text_sha256(expected):
            raise SystemExit(f"seed record probe_text[{name!r}] drifted; rerun probes")
    reported = payload.get("reported_versions") or {}
    sources = payload.get("sources") or {}
    seeded_measurements = payload.get("reader_measurements") or {}
    results: dict[str, dict] = {}
    measurements: dict[str, dict] = {}
    legacy_commit = payload.get("provenance", {}).get("build", {}).get("source_commit")
    for label in readers:
        per_reader = {"__version__": reported.get(label, "unknown")}
        for name in PROBES:
            if name not in probes or label not in probes[name]:
                raise SystemExit(
                    f"seed record misses probe {name!r} for reader {label!r}"
                )
            per_reader[name] = probes[name][label]
        results[label] = per_reader
        seeded = seeded_measurements.get(label)
        if isinstance(seeded, dict):
            measurements[label] = dict(seeded)
        else:
            source = sources.get(label) if isinstance(sources, dict) else None
            module_sha = (
                source.get("module_sha256") if isinstance(source, dict) else None
            )
            measurements[label] = {
                "version": per_reader["__version__"],
                "commit": legacy_commit,
                "date": None,
                "module_sha256": module_sha,
            }
    return readers, results, dict(sources), measurements


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--reader-wheel",
        action="append",
        default=[],
        metavar="VERSION=WHEEL",
        help="reader from a wheel file (records wheel + module hashes)",
    )
    ap.add_argument(
        "--reader-dir",
        action="append",
        default=[],
        metavar="VERSION=DIR",
        help="reader from an unpacked import directory",
    )
    ap.add_argument(
        "--reader",
        action="append",
        default=[],
        metavar="VERSION=PATH",
        help="deprecated alias for --reader-wheel/--reader-dir",
    )
    ap.add_argument(
        "--out", type=Path, default=OUT, help="record directory (default: %(default)s)"
    )
    ap.add_argument(
        "--seed-record",
        type=Path,
        default=None,
        help="existing version_drift.json to carry forward for already-measured readers",
    )
    args = ap.parse_args()
    ensure_published_clean(ROOT.parents[1])

    with bench_scratch("scratch") as tmp:
        reader_labels: list[str] = []
        results: dict[str, dict] = {}
        sources: dict[str, dict] = {}
        measurements: dict[str, dict] = {}
        if args.seed_record is not None:
            seeded_labels, seeded_results, seeded_sources, seeded_measurements = (
                seed_from_record(args.seed_record)
            )
            reader_labels.extend(seeded_labels)
            results.update(seeded_results)
            sources.update(seeded_sources)
            measurements.update(seeded_measurements)
        specs: list[tuple[str, Path, bool]] = []
        for spec in args.reader_wheel:
            label, path = parse_labeled(spec, option="--reader-wheel")
            specs.append((label, path, True))
        for spec in args.reader_dir:
            label, path = parse_labeled(spec, option="--reader-dir")
            specs.append((label, path, False))
        for spec in args.reader:
            label, path = parse_labeled(spec, option="--reader")
            specs.append((label, path, path.suffix == ".whl"))
        if not specs:
            if not reader_labels:
                raise SystemExit(
                    "at least one reader is required (--reader-wheel/--reader-dir or --seed-record)"
                )
        for label, path, wheel_expected in specs:
            if label in results:
                raise SystemExit(
                    f"reader {label!r} already exists in seed record; remove it there or pick a new label"
                )
            if path.suffix == ".whl":
                sources[label] = {"wheel": path.name, "wheel_sha256": sha256(path)}
                with zipfile.ZipFile(path) as wheel:
                    wheel.extractall(Path(tmp) / label)
                path = Path(tmp) / label
            elif wheel_expected:
                raise SystemExit(f"--reader-wheel needs a .whl path, got {path}")
            sources.setdefault(label, {})["module_sha256"] = reader_module_sha(
                path, label
            )
            results[label] = ask(path, PROBES)
            reader_labels.append(label)
    labels = reader_labels

    split = []
    for name in PROBES:
        changes = landed(results, labels, name)
        if changes:
            split.append(
                {
                    "probe": name,
                    "verdicts": {
                        label: results[label][name]["verdict"] for label in labels
                    },
                    "outcomes": {
                        label: outcome(results[label][name]) for label in labels
                    },
                    "landed": changes,
                }
            )
    by_release = {
        label: [
            item["probe"]
            for item in split
            if any(c["release"] == label for c in item["landed"])
        ]
        for label in labels[1:]
    }

    import provenance

    module = require_installed_module(provenance.readcon_module())
    stale = provenance.newer_sources(module)
    refuse_stale_module(stale)
    source_commit = provenance.record().get("build", {}).get("source_commit")
    measured_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for label in labels:
        if label not in measurements:
            module_sha = sources.get(label, {}).get("module_sha256")
            measurements[label] = {
                "version": results[label]["__version__"],
                "commit": source_commit,
                "date": measured_at,
                "module_sha256": module_sha,
            }
    payload = {
        "readers": labels,
        "reported_versions": {label: results[label]["__version__"] for label in labels},
        "reader_measurements": {label: measurements[label] for label in labels},
        "measures_release": [
            results[label]["__version__"]
            for label in labels
            if "wheel" in sources[label]
        ],
        "sources": sources,
        "probes": {
            name: {label: results[label][name] for label in labels} for name in PROBES
        },
        "probe_text": PROBES,
        "n_probes": len(PROBES),
        "n_split": len(split),
        "split": split,
        "changes_by_release": by_release,
        "provenance": provenance.record(),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "version_drift.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    width = max(len(name) for name in PROBES)
    print("probe".ljust(width), *(label.rjust(9) for label in labels))
    for name in PROBES:
        cells = []
        for label in labels:
            entry = results[label][name]
            cells.append(
                (
                    f"{entry['frames']} frames"
                    if entry["verdict"] == "accept"
                    else "reject"
                ).rjust(9)
            )
        print(name.ljust(width), *cells)
    print()
    print(f"{len(split)} of {len(PROBES)} probes split the readers")
    for item in split:
        print("  ", item["probe"], item["landed"])
    for label, names in by_release.items():
        print(f"changes that landed in {label}: {len(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
