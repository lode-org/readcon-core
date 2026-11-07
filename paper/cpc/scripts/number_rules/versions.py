"""Identifier rules: versions printed in the prose of ``rg_main.tex`` and ``rg_supp.tex`` that a record names."""

from __future__ import annotations

from pathlib import Path

from numbers_lib import Rule, jget


def _cargo_version() -> str:
    root = Path(__file__).resolve().parents[4]
    for line in (root / "Cargo.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith('version = "'):
            return line.split('"', 2)[1]
    raise SystemExit("Cargo.toml has no version")


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
    if version not in jget(DRIFT, "readers"):
        raise SystemExit(f"{DRIFT}: {version} is not one of the readers")
    return jget(DRIFT, "reported_versions")[version]


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
        for v in ("0.17.0", "0.17.1", "0.17.2", _cargo_version())
    ),
]
