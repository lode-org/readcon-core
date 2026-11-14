"""Identifier rules: versions printed in the prose of ``rg_main.tex`` and ``rg_supp.tex`` that a record names."""

from __future__ import annotations

import json
import subprocess

from numbers_lib import REPO, ROOT, Rule, jget

GIT_DRIFT = "paper/cpc/data/spec/version_drift.json"


def _drift() -> dict:
    disk = ROOT / "data" / "spec" / "version_drift.json"
    if disk.is_file():
        return json.loads(disk.read_text(encoding="utf-8"))
    listed = subprocess.run(
        ["git", "-C", str(REPO), "log", "--pretty=%H", "--", GIT_DRIFT],
        capture_output=True,
        text=True,
        check=True,
    )
    for commit in listed.stdout.split():
        shown = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{commit}:{GIT_DRIFT}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if shown.returncode == 0 and shown.stdout.strip():
            return json.loads(shown.stdout)
    raise SystemExit(f"{DRIFT} is not in the tree or its history")


DOC = "rg_main.tex"
OPENERS = "data/failure/con_openers.json"
DRIFT = "data/spec/version_drift.json"
OPEN_NEITHER = (r"rg_supp.tex~open neither a version-1 CON file nor a CON 3.1 file",)
DRIFT_LINE = (
    rf"{DOC}~published wheels of readcon-core",
    r"rg_supp.tex~spec\\_version\\_drift\.py.*readcon wheels",
)


def opener(library: str, peer: str) -> str:
    """The version of ``library`` in the record, which must open neither probe file under any of its readers."""
    readers = {
        k: v for k, v in jget(OPENERS, "readers").items() if k.split(",")[0] == library
    }
    if not readers or any(
        result["opens"] for reader in readers.values() for result in reader.values()
    ):
        raise SystemExit(
            f"{OPENERS}: {library} opens a probe file or is not in the record"
        )
    return jget(OPENERS, f"provenance.peers.{peer}")


def drift_reader(version: str) -> str:
    """A published wheel that ``spec_version_drift.py`` ran, as the wheel reported its own version."""
    data = _drift()
    readers = data.get("readers") or []
    reported = data.get("reported_versions") or {}
    if version not in readers and version not in reported:
        raise SystemExit(f"{DRIFT}: {version} is not one of the readers")
    return reported[version]


RULES = [
    Rule(
        "0.10.4",
        opener("chemfiles", "chemfiles"),
        OPENERS,
        "chemfiles version; opens neither file",
        OPEN_NEITHER,
    ),
    Rule(
        "2.10.0",
        opener("MDAnalysis", "MDAnalysis"),
        OPENERS,
        "MDAnalysis version; opens neither file",
        OPEN_NEITHER,
    ),
    Rule(
        "3.16.1",
        opener("OVITO", "ovito"),
        OPENERS,
        "OVITO version; opens neither file",
        OPEN_NEITHER,
    ),
    Rule(
        "3.2.1",
        opener("Open Babel", "openbabel"),
        OPENERS,
        "Open Babel version; opens neither file",
        OPEN_NEITHER,
    ),
    *(
        Rule(
            v,
            drift_reader(v),
            DRIFT,
            f"published wheel {v} the drift probes ran",
            DRIFT_LINE,
        )
        for v in ("0.17.0", "0.17.1", "0.17.2")
    ),
]
