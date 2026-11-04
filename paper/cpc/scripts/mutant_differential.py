#!/usr/bin/env python3
"""Mutate small corpus31 files and read every mutant with the independent reader and with readcon.

Each case takes a file of data/corpus31 (a .con or .convel file under MAX_BYTES
bytes whose content decodes as UTF-8, in name order) and makes one to three
edits at random places: insert a token of ALPHABET (probability 0.4), delete
one to eight characters (0.3), or replace one character with a token (0.3).
random.Random(seed) draws the file, the edits and the tokens, so a seed and a
case count give the same inputs on every run. scripts/indep_reader.py
(read_text) and the readcon module this Python imports (read_con_string, its
exception classified by scripts/error_class.py) read each input. A case is the
same when both readers accept with the same frame count or both reject with
the same class. Lines are not compared, since readcon's exceptions carry none;
the record keeps the line each reader reports.

A differing case belongs to the first group of GROUPS whose variant of the
independent reader, which reads one rule as readcon does, gives readcon's
verdict and class. The group names the clauses that leave that rule open. A
case that no group explains is listed as unexplained, and the script exits 1
after writing the record.

    python paper/cpc/scripts/mutant_differential.py                    # seeds 1-7, 3000 cases each
    python paper/cpc/scripts/mutant_differential.py --seeds 1-3 --cases 500
    python paper/cpc/scripts/mutant_differential.py --check            # reruns the record's cases and compares
    python paper/cpc/scripts/mutant_differential.py --tables           # rewrites the macros from the record only

The record and mutant_macros.tex, the counts the paper prints, are written
together; --check also compares the macros with the record.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import indep_reader
import provenance
import readcon
from error_class import classify

ROOT = Path(__file__).resolve().parents[1]
C31 = ROOT / "data" / "corpus31"
OUT = ROOT / "data" / "spec" / "mutant_differential.json"
MACROS = ROOT / "src" / "figures" / "generated" / "mutant_macros.tex"
MAX_BYTES = 4000
SEEDS = "1-7"
CASES = 3000
ALPHABET = (" ", "\t", "\n", "\r\n", "0", "1", "7", "8", "-", ".", "e", "{", "}", "[", "]", '"', ",", ":",
            "Velocities of Component 1", "Coordinates of Component 1", '"sections":["velocities"]',
            '"con_spec_minor":2', '"section_arity":{"stress":2}', "180", "0.0", "H", "Pt", '"validate":true',
            '"time":"fs",', "\nPt\nVelocities of Component 1\n0 0 0 0 0\n")

COUNTS_OF = indep_reader.counts_of
JSON_NUMBER = indep_reader._json_number
SPLIT_LINES = indep_reader.split_lines


def counts_field_first(raw: str, line: int, n: int) -> list[int]:
    """counts_of with the number of tokens (CON-num.9) checked before the tokens (CON-error.3)."""
    found = len(indep_reader.fields(raw))
    if found != n:
        raise indep_reader.Rejection("InvalidVectorLength", line, "CON-num.9", f"{found} counts, want {n}")
    return COUNTS_OF(raw, line, n)


def json_number_unbounded(text: str, i: int) -> tuple[int | float, int]:
    """_json_number without its range limit: a float literal past binary64 reads as infinity."""
    match = indep_reader.JSON_NUMBER.match(text, i)
    if match is not None and (match.group(1) or match.group(2)) and math.isinf(float(match.group())):
        return float(match.group()), match.end()
    return JSON_NUMBER(text, i)


def split_lines_final_cr(data: bytes) -> list[str]:
    """split_lines with a CR that is the last byte of the input read as a line end."""
    return SPLIT_LINES(data[:-1] if data.endswith(b"\r") else data)


GROUPS = (
    {
        "group": "count line",
        "rule": "CON-error.3 makes a count token that is not an unsigned integer InvalidCount, and CON-num.9 makes "
                "a row with the wrong number of fields InvalidVectorLength; both readers hold a count line to both "
                "clauses. A count line with the wrong number of tokens and a token that is not an unsigned integer "
                "breaks both on one line, and CON-error.4 orders errors by line number only, so no clause picks "
                "the class. readcon checks the number of tokens first, the independent reader each token first.",
        "variant": "the independent reader with the number of tokens of a count line checked before the tokens",
        "patch": ("counts_of", counts_field_first),
    },
    {
        "group": "number past binary64 on line 2",
        "rule": "A JSON number past the binary64 range, such as 1e999, is a number under the RFC 8259 grammar, so "
                "CON-line2.2, which rejects malformed JSON, does not apply, and CON-line2.13 types the reserved keys "
                "only; RFC 8259 section 9 lets a parser limit the range of numbers. The independent reader rejects "
                "such a number anywhere on line 2 (InvalidMetadataJson, CON-line2.1); readcon keeps it in a key "
                "that is not reserved and reads on. No clause requires either reading.",
        "variant": "the independent reader with a float literal past binary64 read as infinity",
        "patch": ("_json_number", json_number_unbounded),
    },
    {
        "group": "CR at the end of the input",
        "rule": "CON-file.3 asks parsers to accept LF and CRLF line ends and states nothing of a CR that is the "
                "last byte of the input. readcon reads that CR as a line end (MemchrLines::read_one and "
                "ignorable_tail in src/iterators.rs), the independent reader as a character of the last line "
                "(split_lines). A last line that holds only that CR is then trailing whitespace, which is not a "
                "frame (CON-frame.1 and decision D2 of spec.org), for readcon, and line 1 of a further frame, which "
                "ends there (IncompleteHeader, CON-frame.3), for the independent reader.",
        "variant": "the independent reader with a CR that is the last byte of the input read as a line end",
        "patch": ("split_lines", split_lines_final_cr),
    },
)


def seed_files() -> list[tuple[str, str]]:
    files = []
    for path in sorted(C31.iterdir()):
        if path.suffix in (".con", ".convel") and path.stat().st_size < MAX_BYTES:
            payload, _ = indep_reader.unwrap(path.read_bytes())
            try:
                files.append((path.name, payload.decode("utf-8")))
            except UnicodeDecodeError:
                continue
    return files


def cases(files: list[tuple[str, str]], seed: int, count: int):
    rng = random.Random(seed)
    for case in range(count):
        name, data = rng.choice(files)
        for _ in range(rng.randint(1, 3)):
            pos = rng.randrange(len(data) + 1)
            op = rng.random()
            if op < 0.4:
                data = data[:pos] + rng.choice(ALPHABET) + data[pos:]
            elif op < 0.7:
                data = data[:pos] + data[pos + rng.randint(1, 8):]
            else:
                data = data[:pos] + rng.choice(ALPHABET) + data[pos + 1:]
        yield case, name, data


def read_indep(text: str) -> dict:
    try:
        frames = indep_reader.read_text(text)
    except indep_reader.Rejection as exc:
        return {"verdict": "reject", "class": exc.cls, "line": exc.line, "clause": exc.clause, "message": exc.message}
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "crash", "class": type(exc).__name__, "line": None, "message": str(exc)}
    return {"verdict": "accept", "frames": len(frames)}


def read_readcon(text: str) -> dict:
    try:
        frames = readcon.read_con_string(text)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001
        cls, line, _ = classify(exc)
        return {"verdict": "reject", "class": cls, "line": line, "message": str(exc)}
    except BaseException as exc:  # noqa: BLE001
        return {"verdict": "crash", "class": type(exc).__name__, "line": None, "message": str(exc)}
    return {"verdict": "accept", "frames": len(frames)}


def outcome(result: dict) -> list:
    return [result["verdict"], result["frames"] if result["verdict"] == "accept" else result["class"]]


def explain(text: str, got: dict) -> dict | None:
    for group in GROUPS:
        name, variant = group["patch"]
        saved = getattr(indep_reader, name)
        setattr(indep_reader, name, variant)
        try:
            again = read_indep(text)
        finally:
            setattr(indep_reader, name, saved)
        if outcome(again) == outcome(got):
            return group
    return None


def seed_list(spec: str) -> list[int]:
    seeds = []
    for part in spec.split(","):
        first, _, last = part.partition("-")
        seeds += range(int(first), int(last or first) + 1)
    return seeds


def run(seeds: list[int], count: int) -> dict:
    files = seed_files()
    per_seed, found = [], {}
    for seed in seeds:
        same = 0
        for case, name, text in cases(files, seed, count):
            a, b = read_indep(text), read_readcon(text)
            if outcome(a) == outcome(b):
                same += 1
                continue
            group = explain(text, b)
            key = group["group"] if group else "unexplained"
            entry = found.setdefault(key, {"group": key, "count": 0, "pairs": {}, "cases": [], "example": None,
                                           "rule": group["rule"] if group else None,
                                           "variant": group["variant"] if group else None})
            entry["count"] += 1
            pair = f"{' '.join(map(str, outcome(a)))} / {' '.join(map(str, outcome(b)))}"
            entry["pairs"][pair] = entry["pairs"].get(pair, 0) + 1
            entry["cases"].append([seed, case])
            if entry["example"] is None:
                entry["example"] = {"seed": seed, "case": case, "file": name, "input": text,
                                    "indep_reader": a, "readcon": b}
        per_seed.append({"seed": seed, "same": same, "differ": count - same})
    order = [g["group"] for g in GROUPS] + ["unexplained"]
    groups = [found[name] for name in order if name in found]
    for entry in groups:
        entry["pairs"] = dict(sorted(entry["pairs"].items(), key=lambda kv: (-kv[1], kv[0])))
    return {
        "script": provenance.portable(Path(__file__)),
        "corpus": provenance.portable(C31),
        "seed_files": len(files),
        "max_bytes": MAX_BYTES,
        "alphabet": list(ALPHABET),
        "seeds": seeds,
        "cases_per_seed": count,
        "compared": "verdict, and the frame count of an accept or the class of a rejection",
        "per_seed": per_seed,
        "totals": {"cases": len(seeds) * count, "same": sum(s["same"] for s in per_seed),
                   "differ": sum(s["differ"] for s in per_seed),
                   "unexplained": found.get("unexplained", {}).get("count", 0)},
        "groups": groups,
        "provenance": provenance.record(),
    }


def comparable(record: dict) -> dict:
    out = {key: value for key, value in record.items() if key != "provenance"}
    out["build"] = {key: record["provenance"]["build"].get(key) for key in ("readcon_version", "library_digest")}
    return out


def macros(record: dict) -> str:
    t = record["totals"]
    values = {
        "mutantCases": f"{t['cases']:,}",
        "mutantSeeds": len(record["seeds"]),
        "mutantPerSeed": f"{record['cases_per_seed']:,}",
        "mutantFiles": record["seed_files"],
        "mutantMaxBytes": f"{record['max_bytes']:,}",
        "mutantSame": f"{t['same']:,}",
        "mutantDiffer": f"{t['differ']:,}",
        "mutantGroups": sum(1 for g in record["groups"] if g["group"] != "unexplained"),
        "mutantUnexplained": t["unexplained"],
    }
    return (f"% Written by {record['script']} from {provenance.portable(OUT).removeprefix('paper/cpc/')}.\n"
            + "".join(f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", help=f"seeds, as 1-7 or 1,3,5 (default: {SEEDS}, or the record's with --check)")
    parser.add_argument("--cases", type=int, help=f"cases per seed (default: {CASES}, or the record's with --check)")
    parser.add_argument("--out", type=Path, default=OUT, help=f"record (default: {provenance.portable(OUT)})")
    parser.add_argument("--check", action="store_true", help="rerun the cases and compare with --out instead of writing")
    parser.add_argument("--tables", action="store_true", help="rewrite the macros from --out only; runs no case")
    args = parser.parse_args()
    if args.tables:
        MACROS.write_text(macros(json.loads(args.out.read_text())))
        print(f"wrote {provenance.portable(MACROS)} from {provenance.portable(args.out)}")
        return 0
    stored = json.loads(args.out.read_text()) if args.check else None
    seeds = seed_list(args.seeds) if args.seeds else stored["seeds"] if stored else seed_list(SEEDS)
    count = args.cases if args.cases is not None else stored["cases_per_seed"] if stored else CASES
    stale = provenance.newer_sources(provenance.readcon_module()) if provenance.readcon_module() else []
    if stale:
        sys.exit(f"the readcon module is older than {', '.join(stale[:3])}; rebuild it")
    record = run(seeds, count)
    t = record["totals"]
    build = record["provenance"]["build"]
    print(f"{t['cases']} cases from {record['seed_files']} corpus31 files: {t['same']} same, {t['differ']} differ, "
          f"{t['unexplained']} unexplained (readcon {build['readcon_version']}, library "
          f"{build['library_digest'][:12]})")
    for row in record["per_seed"]:
        print(f"  seed {row['seed']}: {row['same']} same, {row['differ']} differ")
    for group in record["groups"]:
        print(f"  {group['count']:5d} {group['group']}")
    if args.check:
        if comparable(stored) != comparable(record):
            print(f"{provenance.portable(args.out)} differs from this run", file=sys.stderr)
            return 1
        if not MACROS.is_file() or MACROS.read_text() != macros(stored):
            print(f"{provenance.portable(MACROS)} differs from {provenance.portable(args.out)}", file=sys.stderr)
            return 1
        print(f"{args.out.name} and {MACROS.name} match this run")
        return 0
    args.out.write_text(json.dumps(record, indent=1) + "\n")
    MACROS.write_text(macros(record))
    print(f"wrote {provenance.portable(args.out)} and {provenance.portable(MACROS)}")
    return 1 if t["unexplained"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
