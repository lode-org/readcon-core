"""Identifier rules: grammar versions, peer versions and dates, named standards, a code point, and the small
integers of ``rg_main.tex``, ``rg_supp.tex`` and their generated fragments that a record or the specification names."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from numbers_lib import Rule, const, grep, jget, row, rows, text

MAIN = "rg_main.tex"
SUPP = "rg_supp.tex"
GEN = "figures/generated/"
SPEC = "/docs/orgmode/spec.org"
OPENERS = "data/failure/con_openers.json"
DRIFT_X = "data/failure/drift_extxyz.json"
H2H = "bench/results/r0174/h2h/python_coords.json"
CROSSCHECK = "data/corpus_crosscheck.json"
RELEASES = "data/peers/releases.json"
FORMATS = "/bench/h2h/formats/v0.23.3/extra"
MANIFEST = "data/corpus31/manifest.toml"
VELOCITY = "bench/results/velocity_case.json"
VELOCITY_DRIVER = "scripts/velocity_case.py"
READER_EXCHANGE = "logs/reader-exchange.log"
MPI_LOG = "logs/mpi.log"
MPI_DRIVER = "scripts/mpi_from_log.py"
DLPACK_DRIVER = "scripts/gen_dlpack_macros.py"
HCN = "bench/results/hcn_loss.csv"
SURVEY = "data/survey_frame.json"
FAIR_DB = "data/db31/fair-db31/campaign.json"
DRIFT = "data/spec/version_drift.json"
PYTHON_RS = "/src/python.rs"
RESTART = "evidence/results/e1_restart.json"

BOTH = (MAIN, SUPP)
DRIFT_LINE = r"(?=.*extxyz\}? 0\.4\.6)"
NOT_DRIFT = r"(?!.*extxyz\}? 0\.4\.6)(?!.*protein data bank row)"


def lines(pattern: str, docs: tuple[str, ...] = BOTH) -> tuple[str, ...]:
    return tuple(f"{doc}~{pattern}" for doc in docs)


def peer_rules(record: str, prefix: str, guard: str, why: str) -> list[Rule]:
    names = {
        "ase": "ASE",
        "chemfiles": "chemfiles",
        "MDAnalysis": "MDAnalysis",
        "h5py": "h5py",
        "ovito": r"OVITO\)?",
        "openbabel": "Open Babel",
    }
    peers = jget(record, prefix)
    out = []
    for key, name in names.items():
        version = peers[key]
        where = lines(rf"^{guard}.*\b{name} {re.escape(version)}\b")
        if any(
            re.search(w.partition("~")[2], text(f"src/{w.partition('~')[0]}"), re.M)
            for w in where
        ):
            out.append(Rule(version, version, record, f"{key} version {why}", where))
    return out


def release(name: str, version: str) -> dict:
    found = [e for e in jget(RELEASES, name) if e["version"] == version]
    if len(found) != 1:
        raise SystemExit(f"{RELEASES}: {name} {version} is not one release")
    return found[0]


def chemfiles_dev() -> str:
    versions = json.loads(grep(f"{FORMATS}/NOTES.txt", r"^versions (\{.*\})$"))
    return re.match(r"(\d+\.\d+\.\d+)-dev ", versions["chemfiles-0.12.0-dev"]).group(1)


def fair_insert(key: str) -> str:
    """``key`` of the fair paper40x8 insert rows, which must all give one value."""
    values = {
        r[key]
        for r in jget(FAIR_DB, "fair")
        if r["protocol"] == "fair"
        and r["workload"] == "paper40x8"
        and r["op"] == "insert"
    }
    if len(values) != 1:
        raise SystemExit(
            f"{FAIR_DB}: the fair paper40x8 insert rows give {key} {sorted(values)}"
        )
    return f"{values.pop():g}"


def stage_mib() -> str:
    values = 1 << int(grep(PYTHON_RS, r"^const STAGE_VALUES: usize = 1 << (\d+);$"))
    return f"{values * 8 / 2**20:g}"


def slab_side() -> str:
    found = re.match(r"Pt\(100\) (\d)x(\d)x(\d) slab", jget(RESTART, "system"))
    if not found or len(set(found.groups())) != 1:
        raise SystemExit(f"{RESTART}: system names no cubic Pt(100) slab")
    return found.group(1)


def numpy_type7(driver: str) -> str:
    if 'method="linear"' not in text(driver):
        raise SystemExit(f"{driver}: no numpy percentile with method linear")
    return "7"


def spec_digit(digit: int) -> str:
    """``digit`` as the spec names it for a line, column, major, minor, version or mask value."""
    phrase = (
        rf"(?i)\b(?:lines?|columns?|major|minor|versions?|mask)\b[^.\n|]{{0,40}}?"
        rf"(?<![\w.]){digit}(?![\w.])"
    )
    if not re.search(phrase, text(SPEC)):
        raise SystemExit(
            f"{SPEC}: names no line, column, major, minor, version or mask {digit}"
        )
    return str(digit)


SPEC_LINES = (
    r"CON-|(?:line|Line)s?~? ?\d|[Cc]olumn \d|[Mm]ajor|[Mm]inor|[Vv]ersions?~? ?\d|con\\_spec|"
    r"M ?(?:=|\\in|\\ge)|\\mu\\ge|mask|section\\_arity|grammar version"
)
LAYOUT_ROW = r"^[1-9](?:, [1-9])? & "

formats_version = jget(f"{FORMATS}/provenance.json", "readcon_version")
crosscheck_version = jget(CROSSCHECK, "provenance.build.readcon_version")
survey_ids = jget(SURVEY, "ids")
hcn = row(HCN, file="hcn_v31.con", frame="2", reader="readcon-core")["ids"].split()
mpi_ranks = sorted({int(r) for r in re.findall(r" launch ranks (\d+) ", text(MPI_LOG))})
manifest_rfc = grep(MANIFEST, r"RFC (\d+) section 9")


def ase_writer_decimals() -> str:
    """The decimal width of ASE's extended XYZ float format, read from that file.

    The clean-clone trace check refuses ``import ase``. The width is read from
    the installed ``ase/io/extxyz.py`` on ``sys.path`` instead.
    """
    import sys

    for entry in sys.path:
        candidate = Path(entry) / "ase" / "io" / "extxyz.py"
        if not candidate.is_file():
            continue
        found = re.search(r"%\d+\.(\d+)f", candidate.read_text(encoding="utf-8"))
        if found is None:
            raise SystemExit("ASE extxyz writer does not name a decimal width")
        return found.group(1)
    raise SystemExit("ASE extxyz writer does not name a decimal width")


def tectonic_version() -> str:
    """The Tectonic version named by the paper's typeset task."""
    found = re.search(r"Tectonic (\d+\.\d+\.\d+)", text("pixi.toml"))
    if found is None:
        raise SystemExit("pixi.toml does not name a Tectonic version")
    return found.group(1)


_ASE = object()


_RULES = [
    Rule(
        "3.1",
        grep(SPEC, r"^\|\s+(3\.1) \| \d{4}-\d{2}-\d{2} \|"),
        SPEC,
        "the CON 3.1 row of the specification history",
    ),
    Rule(
        "3.0",
        grep(SPEC, r"^\|\s+(3\.0) \| \d{4}-\d{2}-\d{2} \|"),
        SPEC,
        "row of the version history of the specification",
    ),
    *peer_rules(
        OPENERS,
        "provenance.peers",
        NOT_DRIFT,
        "of the survey that opens the probe files",
    ),
    *peer_rules(DRIFT_X, "provenance.peers", DRIFT_LINE, "of the drift comparison"),
    Rule(
        "2.10.0",
        jget(H2H, "provenance.peers.MDAnalysis"),
        H2H,
        "MDAnalysis version of the same-file and nearest-native panel",
        lines(r"protein data bank row.*MDAnalysis 2\.10\.0"),
    ),
    Rule(
        "0.4.6",
        jget(DRIFT_X, "readers.extxyz"),
        DRIFT_X,
        "libAtoms extxyz version of the drift comparison",
        lines(r"extxyz\}? 0\.4\.6"),
    ),
    *(
        Rule(
            v,
            jget(DRIFT, "reported_versions")[v],
            DRIFT,
            f"published wheel {v} the drift probes ran",
            lines(r"published wheels of 0\.17\.0, 0\.17\.1, 0\.17\.2", (SUPP,)),
        )
        for v in ("0.17.0", "0.17.1", "0.17.2")
    ),
    Rule(
        crosscheck_version,
        crosscheck_version,
        CROSSCHECK,
        "readcon-core version of the cross-check",
        (f"{GEN}corpus_crosscheck.tex~readcon-core {re.escape(crosscheck_version)}",),
    ),
    Rule(
        f"v{formats_version}",
        formats_version,
        f"{FORMATS}/provenance.json",
        "readcon_version of the cross-format campaign",
        lines(
            rf"v{re.escape(formats_version)}",
            (MAIN, f"{GEN}format_h2h.tex"),
        ),
    ),
    Rule(
        "0.12.0",
        chemfiles_dev(),
        f"{FORMATS}/NOTES.txt",
        "chemfiles development version of the cross-format campaign",
        (f"{GEN}format_h2h.tex~chemfiles 0\\.12\\.0-dev",),
    ),
    Rule(
        "3.17.0",
        release("OVITO", "3.17.0")["version"],
        RELEASES,
        "OVITO release heading of its release notes",
        lines(r"OVITO 3\.17\.0"),
    ),
    Rule(
        "2026-10-21",
        release("OVITO", "3.17.0")["date"],
        RELEASES,
        "date of the OVITO 3.17.0 release heading",
        lines(r"OVITO 3\.17\.0, released", (SUPP,)),
    ),
    Rule(
        "2.11.0",
        release("MDAnalysis", "2.11.0")["version"],
        RELEASES,
        "MDAnalysis GitHub release package-2.11.0",
        lines(r"MDAnalysis 2\.11\.0|Release 2\.11\.0", (MAIN, SUPP)),
    ),
    Rule(
        "0.2.7",
        release("metatensor-core", "0.2.7")["version"],
        RELEASES,
        "metatensor-core GitHub release metatensor-core-v0.2.7",
        lines(r"Since version 0\.2\.7, the Python package of metatensor-core", (SUPP,)),
    ),
    *(
        Rule(
            v,
            release("d-SEAMS", v)["version"],
            RELEASES,
            f"d-SEAMS GitHub release v{v}",
            lines(r"^d-SEAMS 2\.14\.0 and 2\.14\.1 read CON files", (MAIN,)),
        )
        for v in ("2.14.0", "2.14.1")
    ),
    Rule(
        "0.1.2",
        release("ase-extxyz", "0.1.2")["version"],
        RELEASES,
        "ase-extxyz GitHub release",
        lines(r"ase-extxyz package 0\.1\.2", (SUPP,)),
    ),
    Rule(
        "2026-10-02",
        release("ase-extxyz", "0.1.2")["date"],
        RELEASES,
        "publication date of the ase-extxyz 0.1.2 GitHub release",
        lines(r"ase-extxyz package 0\.1\.2, released", (SUPP,)),
    ),
    Rule(
        "0.0.2",
        release("extxyz-ng", "0.0.2")["version"],
        RELEASES,
        "extxyz-ng release on PyPI",
        lines(r"extxyz-ng 0\.0\.2", (SUPP,)),
    ),
    Rule(
        "CODATA 2018",
        f"CODATA {jget(VELOCITY, 'natural_unit.codata')}",
        VELOCITY,
        "CODATA edition of the natural unit of the velocity case",
    ),
    Rule(
        "RFC)~8259",
        f"RFC)~{manifest_rfc}",
        MANIFEST,
        "RFC the corpus entries on JSON numbers and nesting cite",
    ),
    Rule(
        "U+2003",
        grep(MANIFEST, r"holds (U\+2003) only"),
        MANIFEST,
        "code point of the corpus entry on a blank line of Unicode white space",
    ),
    *(
        Rule(
            str(d),
            spec_digit(d),
            SPEC,
            f"line, column, major, minor, version or mask {d} of the specification",
            lines(SPEC_LINES, (MAIN, SUPP, f"{GEN}corpus_crosscheck.tex"))
            + lines(LAYOUT_ROW, (MAIN,)),
        )
        for d in range(10)
    ),
    Rule(
        "7",
        numpy_type7(MPI_DRIVER),
        MPI_DRIVER,
        "numpy percentile method linear, Hyndman-Fan type 7",
        (f"{GEN}mpi_host_table.tex", f"{SUPP}~Distributed read on this host"),
    ),
    Rule(
        "7",
        grep(READER_EXCHANGE, r"^numpy_percentile method=linear type=(\d+)$"),
        READER_EXCHANGE,
        "quantile type of the host timing record",
        (
            f"{GEN}host_table.tex",
            f"{SUPP}~The bar is the type 7 median\\.$",
            f"{SUPP}~type 7 interquartile range",
        ),
    ),
    Rule(
        "7",
        grep(DLPACK_DRIVER, r'"""Type (\d+): linear between the order statistics'),
        DLPACK_DRIVER,
        "quantile type of the DLPack macros",
        lines(
            r"type 7 interquartile ranges are \\dlpack|whisker is the type 7 interquartile range\.\}$",
            (MAIN,),
        ),
    ),
    Rule(
        "8",
        grep(READER_EXCHANGE, r"^nproc (\d+)$"),
        READER_EXCHANGE,
        "nproc of the host timing record",
        lines(r"8 cores", (MAIN, SUPP, f"{GEN}host_table.tex")),
    ),
    Rule(
        "6",
        str(jget("data/limiter-r15/provenance.json", "repeats")),
        "data/limiter-r15/provenance.json",
        "repeats of the limiter ladder",
        lines(r"6 repetitions", (SUPP,)),
    ),
    Rule(
        "1",
        str(jget("data/limiter-r15/limiter-r15.json", "ladder.0")),
        "data/limiter-r15/limiter-r15.json",
        "first width of the limiter ladder",
        lines(r"1-8 read-only ladder", (SUPP,)),
    ),
    Rule(
        "8",
        str(jget("data/limiter-r15/limiter-r15.json", "ladder.3")),
        "data/limiter-r15/limiter-r15.json",
        "last width of the limiter ladder",
        lines(r"1-8 read-only ladder", (SUPP,)),
    ),
    Rule(
        "5",
        str(jget("data/failure/restart_formats.json", "parameters.movable_images")),
        "data/failure/restart_formats.json",
        "movable images of the restart band",
        lines(r"movable images", (MAIN,)),
    ),
    _ASE,
    Rule(
        tectonic_version(),
        tectonic_version(),
        "pixi.toml",
        "Tectonic version named by the typeset task",
        lines(r"Tectonic", (SUPP,)),
    ),
    *(
        Rule(
            str(r),
            str(r),
            MPI_LOG,
            "rank count of a launch in the MPI record",
            lines(r"at 1, 2, 4 and 8 ranks", (SUPP,)),
        )
        for r in mpi_ranks
    ),
    *(
        Rule(
            i,
            i,
            HCN,
            "identifier of the frame-2 readcon-core row of hcn_v31.con",
            (f"{GEN}hcn_table.tex~stores ids",),
        )
        for i in dict.fromkeys(hcn)
    ),
    *(
        Rule(
            str(i),
            str(i),
            SURVEY,
            "identifier of the survey frame",
            lines(r"The identifiers are 17, 3", (SUPP,)),
        )
        for i in survey_ids
        if i < 10
    ),
    Rule(
        "8",
        fair_insert("n_atoms"),
        FAIR_DB,
        "n_atoms of every fair paper40x8 insert row",
        lines(r"fair store comparison ingests", (SUPP,)),
    ),
    Rule(
        "2",
        fair_insert("span_s"),
        FAIR_DB,
        "span_s of every fair paper40x8 insert row",
        lines(r"fair store comparison ingests", (SUPP,)),
    ),
    Rule(
        "4",
        str(jget(CROSSCHECK, "groups.corpus31.basis.optional")),
        CROSSCHECK,
        "optional entries of the CON 3.1 corpus",
        (f"{GEN}corpus_crosscheck.tex~4 optional",),
    ),
    Rule(
        "4",
        stage_mib(),
        PYTHON_RS,
        "STAGE_VALUES doubles of 8 bytes, in MiB",
        lines(r"copying them in runs of about \\\(4\\\) MiB", (SUPP,)),
    ),
    *(
        Rule(
            f,
            f,
            HCN,
            "frame of hcn_v31.con in the HCN record",
            lines(
                r"Frames 0 and 1 of one file|Frame 2 is a constructed probe", (SUPP,)
            ),
        )
        for f in dict.fromkeys(
            r["frame"] for r in rows(HCN) if r["file"] == "hcn_v31.con"
        )
    ),
    Rule(
        "3",
        slab_side(),
        RESTART,
        "side of the Pt(100) slab of the restart record",
        lines(r"slab of \\\(3\\times3\\times3\\\)", (SUPP,))
        + lines(r"three layers of \\\(3\\times3\\\)", (MAIN,)),
    ),
    Rule(
        "1",
        f"{const(VELOCITY_DRIVER, 'DT_FS'):g}",
        VELOCITY_DRIVER,
        "DT_FS of the velocity Verlet step",
        lines(r"velocity Verlet (?:step of|over) (?:\\\()?1"),
    ),
]


@lru_cache(maxsize=1)
def _rules() -> list[Rule]:
    width = ase_writer_decimals()
    ase = Rule(
        width,
        width,
        "ase/io/extxyz.py",
        "decimal width of the ASE extended XYZ writer",
        lines(r"8 decimals", (SUPP,)),
    )
    return [ase if item is _ASE else item for item in _RULES]


def __getattr__(name: str):
    if name == "RULES":
        return _rules()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
