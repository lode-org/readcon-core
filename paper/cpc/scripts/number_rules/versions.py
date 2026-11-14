"""Identifier rules: versions printed in the prose of ``rg_main.tex`` and ``rg_supp.tex`` that a record names."""

from __future__ import annotations

from pathlib import Path

from numbers_lib import Rule, jget


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


def _drift_rules() -> list[Rule]:
    """Each wheel's reported version. The cargo version is not one of these readers."""
    record = Path(__file__).resolve().parents[2] / DRIFT
    if not record.is_file():
        return []
    reported = jget(DRIFT, "reported_versions")
    return [
        Rule(
            reported[name],
            reported[name],
            DRIFT,
            f"published wheel {name} the drift probes ran",
            DRIFT_LINE,
        )
        for name in jget(DRIFT, "readers")
    ]


RULES = [
    Rule(
        "0.10.4",
        opener("chemfiles", "chemfiles"),
        OPENERS,
        "chemfiles version; opens neither file",
        OPEN_NEITHER,
    ),
    Rule(
        "2.11.0",
        opener("MDAnalysis", "MDAnalysis"),
        OPENERS,
        "MDAnalysis version; opens neither file",
        OPEN_NEITHER,
    ),
    Rule(
        "3.17.2",
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
    *_drift_rules(),
]
