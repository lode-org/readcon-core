#!/usr/bin/env python3
"""Give one file to several readers that all claim CON 3.1.

readcon-core 0.17.0, 0.17.1, 0.17.2 and 0.17.3 ship the CON 3.1 text. This script
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
        --reader 0.17.3=readcon-0.17.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl

Writes data/spec/version_drift.json, with the releases of the wheels under
measures_release and the build and host that ran the probes under
provenance; --out DIR writes it to DIR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_class import classify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "spec"

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
    "legacy velocity block, label in capitals": frame() + VELOCITY.replace("Velocities of Component",
                                                                           "VELOCITIES OF COMPONENT"),
    "legacy velocity block, label words separated by tabs": frame() + VELOCITY.replace("Velocities of Component",
                                                                                       "Velocities\tof\tComponent"),
    "legacy velocity block, blank symbol line": frame() + VELOCITY.replace("\nH\n", "\n  \n"),
    "legacy velocity block, symbol line starting with {": frame() + VELOCITY.replace("\nH\n", "\n{H\n"),
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
    return f"accept {entry['frames']}" if entry["verdict"] == "accept" else f"reject {entry['class']}"


def landed(results: dict, labels: list[str], name: str) -> list[dict]:
    return [{"release": cur, "from": outcome(results[prev][name]), "to": outcome(results[cur][name])}
            for prev, cur in zip(labels, labels[1:])
            if outcome(results[prev][name]) != outcome(results[cur][name])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--reader",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="a readcon wheel, or a directory that holds one unpacked, in release order",
    )
    ap.add_argument("--out", type=Path, default=OUT, help="record directory (default: %(default)s)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="version-drift-") as tmp:
        readers, sources = [], {}
        for spec in args.reader:
            label, _, raw = spec.partition("=")
            path = Path(raw)
            if path.suffix == ".whl":
                sources[label] = {"wheel": path.name, "wheel_sha256": sha256(path)}
                with zipfile.ZipFile(path) as wheel:
                    wheel.extractall(Path(tmp) / label)
                path = Path(tmp) / label
            module = sorted((path / "readcon").glob("readcon*.so"))
            sources.setdefault(label, {})["module_sha256"] = sha256(module[0]) if module else None
            readers.append((label, path))

        results = {label: ask(path, PROBES) for label, path in readers}
    labels = [label for label, _ in readers]

    split = []
    for name in PROBES:
        changes = landed(results, labels, name)
        if changes:
            split.append({"probe": name, "verdicts": {label: results[label][name]["verdict"] for label in labels},
                          "outcomes": {label: outcome(results[label][name]) for label in labels},
                          "landed": changes})
    by_release = {label: [item["probe"] for item in split if any(c["release"] == label for c in item["landed"])]
                  for label in labels[1:]}

    import provenance

    payload = {
        "readers": labels,
        "reported_versions": {label: results[label]["__version__"] for label in labels},
        "measures_release": [results[label]["__version__"] for label in labels if "wheel" in sources[label]],
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
                (f"{entry['frames']} frames" if entry["verdict"] == "accept" else "reject")
                .rjust(9)
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
