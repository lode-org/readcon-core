#!/usr/bin/env python3
"""Three reader paths over the conformance corpus and the CON 3.1 corpus.

readcon (read_con, and iter_con as a second path through the same library)
and the independent reader indep_reader.py (written from the released CON 3.1
text in docs/orgmode/spec.org; where a clause requires a rejection and names
no class, or no clause decides a case, it follows the reading that the
corpus31 manifest records) read every file of
resources/conformance/{valid,invalid} and paper/cpc/data/corpus31. A reader
matches an entry when it accepts an accept entry with the entry's frame count,
or rejects a reject entry with the entry's error class and, where the reader
reports a line, the entry's line; where the entry names them, the first
frame's periodicity and first column-4 mask and the time-unit override warning
must match too, and readcon's write_con_string of the frames must keep the
version, minor and units of every frame of major 3 and write a frame of major
1 or 2 as major 3 (the Python, Julia and Fortran writers write major 3) with
every unit it declares and the same fields. That rewrite keeps the minor of a frame that
declares con_spec_minor or whose velocities carry a units.time label, which
pins it to minor 0; a 3.0 frame with neither comes back at minor 1, and no
file whose entry marks the rewrite holds one. Every corpus31 entry names its basis
(explicit, class-open, optional or open); the conformance entries are decided
by named clauses and count as explicit. A reader that differs from an explicit
entry is a disagreement; one that differs from any other entry does not follow
that entry. For files accepted by readcon and indep_reader, coordinates,
velocities and cell are compared through float.hex, and masks, ids, symbols,
masses, version, minor, declared and applied time unit and periodicity by
equality.

readcon runs in a child process per call, so a call that aborts the process is
a crash on that file and the run goes on. readcon-core 0.17.3 puts no line
number in its Python exceptions, so its lines are not compared, and it warns
of a units.time that it does not apply only when it converts the frame to
ASE (ConFrame.to_ase()), so the child converts every frame that has velocities.

    python3 paper/cpc/scripts/corpus_crosscheck.py

Writes data/corpus_crosscheck.{csv,json}, src/figures/generated/corpus_crosscheck.tex
and corpus_macros.tex. --out DIR writes the four files to DIR; --tables rewrites
the TeX from the record only; --check writes nothing and exits 1 unless the TeX
is what the record gives.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import indep_reader  # noqa: E402
from error_class import classify, normal  # noqa: E402

ROOT = SCRIPTS.parents[2]
SPEC = ROOT / "docs" / "orgmode" / "spec.org"
CONF = ROOT / "resources" / "conformance"
C31 = ROOT / "paper" / "cpc" / "data" / "corpus31"
DATA = ROOT / "paper" / "cpc" / "data"
GENERATED = ROOT / "paper" / "cpc" / "src" / "figures" / "generated"
GROUPS = (
    "conformance valid",
    "conformance invalid",
    "corpus31 accept",
    "corpus31 reject",
)
SUMMARIES = GROUPS + ("conformance", "corpus31", "all")
READERS = ("readcon", "readcon_iter", "indep")
BASES = ("explicit", "class-open", "optional", "open")
FIELDS = (
    "coords",
    "masks",
    "ids",
    "velocities",
    "version",
    "time_unit",
    "cell",
    "pbc",
    "symbols_masses",
)
OVERRIDE = re.compile(r"units\.time .* is not applied")
NO_ZSTD = "--features zstd"
CLAUSE = re.compile(r"^- (CON-[a-z0-9]+\.[0-9]+) :: ", re.M)
CHILD_TIMEOUT = 300


def first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0][:200] if text else ''}"


def blank(value):
    return "" if value is None else value


def expectation(group: str, path: Path, expected: str, entry: dict, basis: str) -> dict:
    return {
        "group": group,
        "path": path,
        "expected": expected,
        "clause": entry["clause"],
        "basis": basis,
        "frames": entry.get("frames"),
        "error": entry.get("error"),
        "line": entry.get("line"),
        "pbc": entry.get("pbc"),
        "fixed": entry.get("expect_fixed"),
        "time_unit_override": entry.get("time_unit_override", False),
        "rewrite": entry.get("rewrite", False),
    }


def corpus() -> list[dict]:
    files = []
    manifest = tomllib.loads((CONF / "manifest.toml").read_text())
    for kind, expected in (("valid", "accept"), ("invalid", "reject")):
        for entry in manifest[kind]:
            files.append(
                expectation(
                    f"conformance {kind}",
                    CONF / entry["path"],
                    expected,
                    entry,
                    "explicit",
                )
            )
    for entry in tomllib.loads((C31 / "manifest.toml").read_text())["file"]:
        files.append(
            expectation(
                f"corpus31 {entry['expected']}",
                C31 / entry["file"],
                entry["expected"],
                entry,
                entry["basis"],
            )
        )
    return files


def hexes(values) -> list:
    return [None if v is None else float(v).hex() for v in values]


def lattice(rows) -> list | None:
    return None if rows is None else [hexes(r) for r in rows]


def applied_unit(frame):
    value = getattr(frame, "velocity_time_unit", None)
    return value() if callable(value) else value


def readcon_view(frames) -> list[dict]:
    out = []
    for f in frames:
        meta = f.metadata or {}
        atoms = f.atoms
        vel = [(a.vx, a.vy, a.vz) for a in atoms] if f.has_velocities else None
        pbc = getattr(f, "pbc", None)
        out.append(
            {
                "coords": [hexes((a.x, a.y, a.z)) for a in atoms],
                "masks": [[bool(b) for b in a.fixed] for a in atoms],
                "ids": [int(a.atom_id) for a in atoms],
                "velocities": None if vel is None else [hexes(v) for v in vel],
                "version": [f.spec_version, meta.get("con_spec_minor", 0)],
                "time_unit": [
                    (meta.get("units") or {}).get("time"),
                    None if vel is None else applied_unit(f),
                ],
                "cell": [
                    hexes(f.cell),
                    hexes(f.angles),
                    lattice(meta.get("lattice_vectors")),
                ],
                "pbc": None if pbc is None else [bool(b) for b in pbc],
                "symbols_masses": [[a.symbol, float(a.mass).hex()] for a in atoms],
            }
        )
    return out


def indep_view(frames) -> list[dict]:
    out = []
    for f in frames:
        vel = f["velocities"]
        out.append(
            {
                "coords": [hexes(p) for p in f["positions"]],
                "masks": [list(m) for m in f["masks"]],
                "ids": list(f["ids"]),
                "velocities": None if vel is None else [hexes(v) for v in vel],
                "version": [f["major"], f["minor"]],
                "time_unit": [
                    f["declared_time"],
                    None if vel is None else f["time_unit"],
                ],
                "cell": [
                    hexes(f["cell_lengths"]),
                    hexes(f["cell_angles"]),
                    lattice(f["lattice_vectors"]),
                ],
                "pbc": list(f["pbc"]),
                "symbols_masses": [
                    [s, float(m).hex()] for s, m in zip(f["symbols"], f["masses"])
                ],
            }
        )
    return out


def child(call: str, path: str, rewrite: bool) -> dict:
    """One readcon call on ``path`` in this process: the outcome, the frames' view, the override warnings, the rewrite."""
    import readcon

    read = {
        "read_con": readcon.read_con,
        "iter_con": lambda p: list(readcon.iter_con(p)),
    }[call]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            frames = read(path)
        except Exception as exc:  # noqa: BLE001
            cls, line, located = classify(exc)
            return {
                "outcome": "reject",
                "class": cls,
                "line": line,
                "located": located,
                "error": first_line(exc),
            }
        except BaseException as exc:
            if type(exc).__name__ != "PanicException":
                raise
            return {"outcome": "crash", "error": first_line(exc)}
    view = readcon_view(frames)
    out = {
        "outcome": "accept",
        "frames": len(frames),
        "atoms": sum(len(v["ids"]) for v in view),
        "view": view,
        "overrides": sum(bool(OVERRIDE.search(str(w.message))) for w in caught),
    }
    for frame in frames:
        if not frame.has_velocities:
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                frame.to_ase()
            except Exception as exc:  # noqa: BLE001
                out["to_ase_error"] = first_line(exc)
        out["overrides"] += any(OVERRIDE.search(str(w.message)) for w in caught)
    if rewrite:
        try:
            out["rewrite"] = readcon.write_con_string(frames)
        except Exception as exc:  # noqa: BLE001
            out["rewrite_error"] = first_line(exc)
    return out


def readcon_run(call: str, path: Path, rewrite: bool) -> dict:
    argv = [sys.executable, str(Path(__file__).resolve()), "--child", call, str(path)]
    try:
        proc = subprocess.run(
            argv + ["--rewrite"] * rewrite,
            capture_output=True,
            text=True,
            timeout=CHILD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "crash", "error": f"no answer in {CHILD_TIMEOUT} s"}
    if proc.returncode != 0 or not proc.stdout.strip():
        tail = proc.stderr.strip().splitlines()[-1:] or [""]
        return {
            "outcome": "crash",
            "error": f"exit status {proc.returncode}: {tail[0][:200]}",
        }
    return json.loads(proc.stdout)


def indep_run(path: Path) -> tuple[dict, list | None]:
    try:
        frames = indep_reader.read_path(path)
    except indep_reader.Rejection as exc:
        return {
            "outcome": "reject",
            "class": normal(exc.cls),
            "line": exc.line,
            "error": first_line(exc),
        }, None
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "crash", "error": first_line(exc)}, None
    return {
        "outcome": "accept",
        "frames": len(frames),
        "atoms": sum(len(f["ids"]) for f in frames),
        "overrides": sum(f["time_override"] is not None for f in frames),
        "view": indep_view(frames),
    }, frames


def identity(frame: dict) -> tuple:
    return frame["major"], frame["minor"], (frame["metadata"] or {}).get("units")


def fields(frame: dict) -> dict:
    """The fields of one frame of the independent reader, without its version."""
    view = indep_view([frame])[0]
    view.pop("version")
    unit = view["time_unit"][1]
    view["time_unit"][1] = (
        None if unit is None else indep_reader.canonical_unit(str(unit))
    )
    return view


def kept(before: dict, after: dict) -> bool:
    """A frame of major 3 is kept when it comes back with its version, minor and units. The rewrite keeps the minor of
    a frame that declares con_spec_minor or whose velocities carry a units.time label, which pins it to minor 0; a 3.0
    frame with neither comes back at minor 1, the minor the builder stamps (D15), and is not kept. The Python, Julia and
    Fortran writers write every frame as major 3 (D15), so a frame of major 1 or 2 is kept when it comes back as major 3
    with every unit it declares and the same fields."""
    if before["major"] >= 3:
        return identity(before) == identity(after)
    declared, written = (
        (frame["metadata"] or {}).get("units") or {} for frame in (before, after)
    )
    return (
        after["major"] == 3
        and all(written.get(key) == value for key, value in declared.items())
        and fields(before) == fields(after)
    )


def rewrite_status(frames: list[dict] | None, got: dict) -> str:
    """'kept' when indep_reader reads readcon's rewrite with every frame of the file kept (``kept``)."""
    if "rewrite_error" in got:
        return f"write failed: {got['rewrite_error']}"
    if frames is None:
        return "no reference: the independent reader rejects the file"
    try:
        again = indep_reader.read_text(got["rewrite"])
    except indep_reader.Rejection as exc:
        return f"rewrite rejected: {exc}"
    before, after = [identity(f) for f in frames], [identity(f) for f in again]
    if len(frames) == len(again) and all(kept(b, a) for b, a in zip(frames, again)):
        return "kept"
    k = next(
        (i for i, (b, a) in enumerate(zip(before, after)) if b != a),
        min(len(before), len(after)),
    )
    return f"frame {k}: {before[k] if k < len(before) else None} -> {after[k] if k < len(after) else None}"


def line_compared(entry: dict, got: dict) -> bool:
    return (
        entry["expected"] == "reject" == got["outcome"]
        and entry["line"] is not None
        and got.get("line") is not None
    )


def misses(entry: dict, got: dict, writer: bool) -> list[str]:
    """The checks of ``entry`` that ``got`` fails; a line is checked only where the reader reports one."""
    if got["outcome"] != entry["expected"]:
        return ["outcome"]
    if entry["expected"] == "reject":
        failed = (
            []
            if entry["error"] is None or entry["error"] == got.get("class")
            else ["class"]
        )
        if line_compared(entry, got) and entry["line"] != got["line"]:
            failed.append("line")
        return failed
    failed = [
        name
        for name, want, have in (
            ("frames", entry["frames"], got.get("frames")),
            ("pbc", entry["pbc"], got.get("pbc")),
            ("fixed", entry["fixed"], got.get("fixed")),
        )
        if want is not None and want != have
    ]
    if bool(got.get("overrides")) != entry["time_unit_override"]:
        failed.append("override")
    if writer and entry["rewrite"] and got.get("rewrite_status") != "kept":
        failed.append("rewrite")
    return failed


def same_decision(a: dict, b: dict) -> bool:
    """The same verdict, and the same frame count, or the same error class and, where both report one, line."""
    if a["outcome"] != b["outcome"]:
        return False
    if a["outcome"] == "accept":
        return a["frames"] == b["frames"]
    if a["outcome"] != "reject" or a["class"] != b["class"]:
        return False
    return a.get("line") is None or b.get("line") is None or a["line"] == b["line"]


def compare(a: list[dict], b: list[dict]) -> dict:
    if len(a) != len(b):
        return {k: False for k in FIELDS}
    return {k: all(x[k] == y[k] for x, y in zip(a, b)) for k in FIELDS}


def run(entry: dict) -> dict:
    path = entry["path"]
    got = {
        "readcon": readcon_run("read_con", path, entry["rewrite"]),
        "readcon_iter": readcon_run("iter_con", path, False),
    }
    got["indep"], ind_frames = indep_run(path)
    for result in got.values():
        view = result.get("view")
        for frame in view or ():
            unit = frame["time_unit"][1]
            frame["time_unit"][1] = (
                None if unit is None else indep_reader.canonical_unit(str(unit))
            )
        result["pbc"] = view[0]["pbc"] if view else None
        result["fixed"] = view[0]["masks"][0] if view and view[0]["masks"] else None
    rc, it, ind = got["readcon"], got["readcon_iter"], got["indep"]
    if entry["rewrite"] and rc["outcome"] == "accept":
        rc["rewrite_status"] = rewrite_status(ind_frames, rc)
    row = {
        "group": entry["group"],
        "file": str(path.relative_to(ROOT)),
        "basis": entry["basis"],
        "expected": entry["expected"],
        "expected_frames": blank(entry["frames"]),
        "expected_class": blank(entry["error"]),
        "expected_line": blank(entry["line"]),
        "expected_pbc": blank(entry["pbc"]),
        "expected_fixed": blank(entry["fixed"]),
        "expected_override": entry["time_unit_override"],
        "rewrite": entry["rewrite"],
        "clause": entry["clause"],
    }
    for name in READERS:
        result = got[name]
        failed = misses(entry, result, writer=name == "readcon")
        kind = (
            ""
            if not failed
            else "disagreement"
            if entry["basis"] == "explicit"
            else "not followed"
        )
        row.update(
            {
                name: result["outcome"],
                f"{name}_frames": blank(result.get("frames")),
                f"{name}_atoms": blank(result.get("atoms")),
                f"{name}_class": blank(result.get("class")),
                f"{name}_line": blank(result.get("line")),
                f"{name}_pbc": blank(result.get("pbc")),
                f"{name}_overrides": blank(result.get("overrides")),
                f"{name}_error": result.get("error") or result.get("to_ase_error", ""),
                f"{name}_line_compared": line_compared(entry, result),
                f"{name}_failed": " ".join(failed),
                f"{name}_agrees": not failed,
                f"{name}_kind": kind,
            }
        )
    row["readcon_located"] = blank(rc.get("located"))
    row["readcon_rewrite"] = rc.get("rewrite_status", "")
    row["iter_same"] = same_decision(rc, it) and rc.get("view") == it.get("view")
    row["readcon_indep_same"] = same_decision(rc, ind)
    if "view" in rc and "view" in ind:
        same = compare(rc["view"], ind["view"])
        row.update({f"{k}_agree": same[k] for k in FIELDS})
        row["field_identical"] = all(same.values())
    else:
        row.update({f"{k}_agree": "" for k in FIELDS})
        row["field_identical"] = ""
    row["iter_field_identical"] = (
        all(compare(it["view"], ind["view"]).values())
        if "view" in it and "view" in ind
        else ""
    )
    return row


def summarise(rows: list[dict]) -> dict:
    groups = {}
    picks = {name: (lambda r, name=name: r["group"] == name) for name in GROUPS}
    picks["conformance"] = lambda r: r["group"].startswith("conformance")
    picks["corpus31"] = lambda r: r["group"].startswith("corpus31")
    picks["all"] = lambda r: True
    for name in SUMMARIES:
        sel = [r for r in rows if picks[name](r)]
        both = {
            "readcon": [r for r in sel if r["field_identical"] != ""],
            "readcon_iter": [r for r in sel if r["iter_field_identical"] != ""],
        }
        same = {"readcon": "field_identical", "readcon_iter": "iter_field_identical"}
        readers = {}
        for reader in READERS:
            readers[reader] = {
                "matches": sum(r[f"{reader}_agrees"] for r in sel),
                "disagreements": sum(
                    r[f"{reader}_kind"] == "disagreement" for r in sel
                ),
                "not_followed": sum(r[f"{reader}_kind"] == "not followed" for r in sel),
                "crashes": sum(r[reader] == "crash" for r in sel),
                "lines_compared": sum(r[f"{reader}_line_compared"] for r in sel),
            }
            if reader in both:
                readers[reader]["accepted_with_indep"] = len(both[reader])
                readers[reader]["field_mismatches"] = sum(
                    not r[same[reader]] for r in both[reader]
                )
        groups[name] = {
            "files": len(sel),
            "basis": {b: sum(r["basis"] == b for r in sel) for b in BASES},
            "readers": readers,
            "readcon_iter_same_as_read_con": sum(r["iter_same"] for r in sel),
            "readcon_indep_same_decision": sum(r["readcon_indep_same"] for r in sel),
            "accepted_by_both": len(both["readcon"]),
            "field_identical": sum(bool(r["field_identical"]) for r in both["readcon"]),
            "readcon_crashes": sum(
                "crash" in (r["readcon"], r["readcon_iter"]) for r in sel
            ),
            "rewrite_files": sum(r["rewrite"] for r in sel),
            "rewrite_kept": sum(r["readcon_rewrite"] == "kept" for r in sel),
            "expected_reject": sum(r["expected"] == "reject" for r in sel),
        }
    keys = [
        "file",
        "group",
        "basis",
        "expected",
        "expected_frames",
        "expected_class",
        "expected_line",
    ]
    for name in READERS:
        keys += [
            name,
            f"{name}_frames",
            f"{name}_class",
            f"{name}_line",
            f"{name}_failed",
            f"{name}_kind",
            f"{name}_error",
        ]
    keys += ["readcon_rewrite", "iter_same"]
    differing = [
        {k: r[k] for k in keys}
        for r in rows
        if not (all(r[f"{name}_agrees"] for name in READERS) and r["iter_same"])
    ]
    field_mismatch = [
        {
            "file": r["file"],
            "iter_field_identical": r["iter_field_identical"],
            **{k: r[f"{k}_agree"] for k in FIELDS},
        }
        for r in rows
        if False in (r["field_identical"], r["iter_field_identical"])
    ]
    no_zstd = {
        name: [r["file"] for r in rows if NO_ZSTD in r[f"{name}_error"]]
        for name in READERS[:2]
    }
    return {
        "groups": groups,
        "differing": differing,
        "field_mismatch": field_mismatch,
        "readcon_no_zstd": no_zstd,
    }


def spec_record() -> dict:
    text = SPEC.read_text()
    manifest = tomllib.loads((C31 / "manifest.toml").read_text())
    return {
        "doc": str(SPEC.relative_to(ROOT)),
        "version": re.search(r"^- Version :: (\S+)", text, re.M).group(1),
        "clauses": len(CLAUSE.findall(text)),
        "manifest_spec_doc": manifest["spec_doc"],
        "manifest_reader_minor": manifest["reader_minor"],
        "indep_reader_minor": indep_reader.READER_MINOR,
    }


def corpus31_features() -> dict:
    counts = {
        "files": 0,
        "con_spec_minor": 0,
        "velocity_block": 0,
        "gzip": 0,
        "zstd": 0,
    }
    for entry in tomllib.loads((C31 / "manifest.toml").read_text())["file"]:
        payload, envelope = indep_reader.unwrap((C31 / entry["file"]).read_bytes())
        counts["files"] += 1
        counts["con_spec_minor"] += b'"con_spec_minor"' in payload
        counts["velocity_block"] += b"velocities of component" in re.sub(
            rb"[ \t]+", b" ", payload.lower()
        )
        counts[envelope] = counts.get(envelope, 0) + 1
    counts.pop("none", None)
    return counts


def zstd_sentence(record: dict, name: str) -> list[str]:
    missing = record.get("readcon_no_zstd", {})
    counts = {
        call: len(missing.get(reader, ()))
        for call, reader in ((r"read\_con", "readcon"), (r"iter\_con", "readcon_iter"))
    }
    if not any(counts.values()):
        return []
    lead = r"The readcon-core build under test is compiled without its zstd feature"
    if len(set(counts.values())) > 1:
        parts = " and ".join(
            rf"\texttt{{{call}}} rejects {n}" for call, n in counts.items()
        )
        return [rf"{lead}: of the zstd files, {parts} with \texttt{{Compression}}."]
    n = counts[r"read\_con"]
    files = (
        f"the {n} zstd files of the {name} corpus"
        if n == record["corpus31_features"].get("zstd")
        else f"{n} zstd files"
    )
    return [
        rf"{lead}, so \texttt{{read\_con}} and \texttt{{iter\_con}} reject {files} with \texttt{{Compression}}."
    ]


def tex(record: dict) -> str:
    spec = record["spec"]
    name = f"CON {spec['version']}"
    version = record["provenance"]["build"]["readcon_version"]
    label = {
        "conformance valid": "Conformance, valid",
        "conformance invalid": "Conformance, invalid",
        "corpus31 accept": f"{name} corpus, accept",
        "corpus31 reject": f"{name} corpus, reject",
        "all": "All",
    }
    g = record["groups"]
    basis = g["corpus31"]["basis"]
    caption = [
        rf"readcon-core and the independent reader over the conformance corpus and the {name} corpus.",
        rf"Each entry of the {name} corpus manifest names acceptance with a frame count, or rejection with an error "
        rf"class and a line, and the basis of that outcome in the released {name} text "
        rf"(\texttt{{{spec['doc']}}}, {spec['clauses']} clauses): explicit when clauses decide the outcome and the "
        r"class, class-open when clauses require the rejection and name no class, optional when a clause permits "
        r"the outcome without requiring it, and open when no clause decides the file.",
        rf"The corpus has {basis['explicit']} explicit, {basis['class-open']} class-open, {basis['optional']} "
        rf"optional and {basis['open']} open entries.",
        r"The conformance manifest names acceptance, or rejection with an error class, and its entries count as "
        r"explicit.",
        r"A reader matches an entry when it returns every value that the entry names.",
        r"These are the verdict, the frame count, the error class, the line of the error where the reader reports "
        r"one, and the periodicity and the column-4 mask of the first frame where the entry names them.",
        r"The reader also warns of a time-unit override exactly on the entries that name one.",
        r"For \texttt{read\_con}, the rewrite of each file that its entry marks keeps the version, minor and units of "
        r"every frame of major 3.",
        r"It writes a frame of major 1 or 2 as major 3, with each unit that the frame declares and the same fields, "
        r"as the Python, Julia and Fortran writers do.",
        r"That rewrite keeps the minor of a frame that declares one or whose velocities carry a time label, which "
        r"pins it to minor 0; a frame of version 3.0 with neither comes back at minor 1, and no marked file contains "
        r"one.",
        r"A reader that differs from an explicit entry disagrees with the specification, and one that differs "
        r"from any other entry departs from the reading that entry records.",
        rf"readcon-core {version} puts no line number in its Python exceptions, so its lines are not compared; it "
        r"warns of a declared time unit that it does not apply only when it converts a frame to ASE "
        r"(\texttt{ConFrame.to\_ase}), and the check converts every frame that has velocities.",
        *zstd_sentence(record, name),
        r"\texttt{read\_con} and \texttt{iter\_con} are two paths through readcon-core; the independent reader is "
        r"pure Python written from the released text, and it follows the reading the manifest records where that "
        r"text leaves a case open.",
        r"Field-identical counts the files that both \texttt{read\_con} and the independent reader accept with "
        r"equal fields: coordinates, velocities and cell equal in every bit, and the same masks, identifiers, "
        r"symbols, masses, version, minor, declared and applied time unit and periodicity.",
    ]
    lines = [
        "% Written by paper/cpc/scripts/corpus_crosscheck.py from paper/cpc/data/corpus_crosscheck.json.",
        r"\begin{table}[tbp]",
        r"\centering",
        r"\small",
        r"\caption{" + caption[0],
        *caption[1:-1],
        caption[-1] + "}",
        r"\label{tab:corpus-crosscheck}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}lrrrrrrrrrrr@{}}",
        r"\toprule",
        r" & & \multicolumn{3}{c}{\texttt{read\_con}} & \multicolumn{3}{c}{\texttt{iter\_con}} & "
        r"\multicolumn{3}{c}{Independent} & \\",
        r"\cmidrule(lr){3-5}\cmidrule(lr){6-8}\cmidrule(lr){9-11}",
        r"File group & Files & Match & Disagree & Not followed & Match & Disagree & Not followed & Match & "
        r"Disagree & Not followed & Field-identical \\",
        r"\midrule",
    ]
    for key in GROUPS + ("all",):
        s = g[key]
        if key == "all":
            lines.append(r"\midrule")
        cells = [label[key], str(s["files"])]
        for reader in READERS:
            r = s["readers"][reader]
            cells += [
                str(r["matches"]),
                str(r["disagreements"]),
                str(r["not_followed"]),
            ]
        cells.append(
            f"{s['field_identical']}/{s['accepted_by_both']}"
            if s["accepted_by_both"]
            else "--"
        )
        lines.append(" & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}}", r"\end{table}", ""]
    return "\n".join(lines)


def macros(record: dict) -> str:
    g = record["groups"]
    a, c31 = g["all"], g["corpus31"]
    readers = a["readers"]
    values = {
        "corpusFiles": a["files"],
        "corpusCrossConfValid": g["conformance valid"]["files"],
        "corpusCrossConfInvalid": g["conformance invalid"]["files"],
        "corpusThreeOne": c31["files"],
        "corpusThreeOneAccept": g["corpus31 accept"]["files"],
        "corpusThreeOneReject": g["corpus31 reject"]["files"],
        "corpusBasisExplicit": c31["basis"]["explicit"],
        "corpusBasisClassOpen": c31["basis"]["class-open"],
        "corpusBasisOptional": c31["basis"]["optional"],
        "corpusBasisOpen": c31["basis"]["open"],
        "corpusReadconAgree": readers["readcon"]["matches"],
        "corpusIterAgree": readers["readcon_iter"]["matches"],
        "corpusIndepAgree": readers["indep"]["matches"],
        "corpusReadconDisagree": readers["readcon"]["disagreements"],
        "corpusIterDisagree": readers["readcon_iter"]["disagreements"],
        "corpusIndepDisagree": readers["indep"]["disagreements"],
        "corpusReadconNotFollowed": readers["readcon"]["not_followed"],
        "corpusIterNotFollowed": readers["readcon_iter"]["not_followed"],
        "corpusIndepNotFollowed": readers["indep"]["not_followed"],
        "corpusCrashes": sum(readers[name]["crashes"] for name in READERS),
        "corpusIterSame": a["readcon_iter_same_as_read_con"],
        "corpusSameDecision": a["readcon_indep_same_decision"],
        "corpusBoth": a["accepted_by_both"],
        "corpusFieldIdentical": a["field_identical"],
        "corpusExpectedReject": a["expected_reject"],
        "corpusRewriteFiles": a["rewrite_files"],
        "corpusRewriteKept": a["rewrite_kept"],
        "corpusDiffering": len(record["differing"]),
        "corpusSpecClauses": record["spec"]["clauses"],
        "corpusIndepLines": record["indep_reader_lines"],
        "corpusVelocityFiles": record["corpus31_features"]["velocity_block"],
        "corpusGzipFiles": record["corpus31_features"].get("gzip", 0),
        "corpusZstdFiles": record["corpus31_features"].get("zstd", 0),
        "corpusNoZstd": len(record.get("readcon_no_zstd", {}).get("readcon", ())),
    }
    lines = [
        "% Written by paper/cpc/scripts/corpus_crosscheck.py from paper/cpc/data/corpus_crosscheck.json."
    ]
    lines += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in values.items()]
    return "\n".join(lines) + "\n"


def portable(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out", type=Path, help="write the record and the TeX to this directory"
    )
    parser.add_argument(
        "--tables", action="store_true", help="rewrite the TeX from the record only"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 unless the TeX is what the record gives",
    )
    parser.add_argument(
        "--child", nargs=2, metavar=("CALL", "PATH"), help=argparse.SUPPRESS
    )
    parser.add_argument("--rewrite", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(*args.child, args.rewrite)))
        return
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    out_csv, out_json = (
        (args.out or DATA) / f"corpus_crosscheck.{ext}" for ext in ("csv", "json")
    )
    out_tex, out_macros = (
        (args.out or GENERATED) / name
        for name in ("corpus_crosscheck.tex", "corpus_macros.tex")
    )
    if args.check:
        record = json.loads(out_json.read_text())
        stale = [
            path.name
            for path, text in ((out_tex, tex(record)), (out_macros, macros(record)))
            if not path.is_file() or path.read_text() != text
        ]
        if stale:
            sys.exit(
                f"{', '.join(stale)} differ from {portable(out_json)}; run corpus_crosscheck.py --tables"
            )
        print(
            f"{out_tex.name} and {out_macros.name} are what {portable(out_json)} gives"
        )
        return
    if args.tables:
        record = json.loads(out_json.read_text())
        out_tex.write_text(tex(record))
        out_macros.write_text(macros(record))
        return
    import provenance

    rows = [run(entry) for entry in corpus()]
    rows.sort(key=lambda r: (GROUPS.index(r["group"]), r["file"]))
    with out_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarise(rows)
    warnings.filterwarnings("ignore", message=".*OVITO.*PyPI")
    record = {
        "csv": portable(out_csv),
        "spec": spec_record(),
        **summary,
        "corpus31_features": corpus31_features(),
        "indep_reader_lines": len(
            (SCRIPTS / "indep_reader.py").read_text().splitlines()
        ),
        "provenance": provenance.record(),
    }
    out_json.write_text(json.dumps(record, indent=2) + "\n")
    out_tex.write_text(tex(record))
    out_macros.write_text(macros(record))
    for key, s in summary["groups"].items():
        print(key, json.dumps({k: v for k, v in s.items() if k != "readers"}))
        for reader, counts in s["readers"].items():
            print("   ", reader, json.dumps(counts))
    for d in summary["differing"]:
        print("DIFFERS", {k: v for k, v in d.items() if v not in ("", None)})
    for d in summary["field_mismatch"]:
        print("FIELDS", d)


if __name__ == "__main__":
    main()
