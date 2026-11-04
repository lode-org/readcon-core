#!/usr/bin/env python3
"""Read both corpora through the frame readers and the frame count of the Python module and the C library.

Each file of the conformance corpus (resources/conformance/manifest.toml) and
of the CON 3.1 corpus (data/corpus31/manifest.toml) is read

- by the readcon module of this environment (features python and zstd, with
  Rayon): read_con_string at 1, 2 and 8 threads and the default, read_con on
  a plain, a mapped and a gzip copy at those settings, iter_con on the plain
  copy, iter_con(mmap=True) on the mapped copy, iter_con(stream=True), the
  stream reader, on the plain and gzip copies, and count_frames on the
  plain, mapped and gzip copies;
- by the C library in its default build, which has no Rayon and parses on
  one thread at every setting, and built with parallel, as the release
  archives build it: read_con_buffer_iterator,
  rkr_read_all_frames_n_threads on the plain, mapped and gzip copies at 1, 2
  and 8 threads and 0 (the default), read_con_file_iterator on the plain
  copy, and rkr_count_frames on the plain, mapped and gzip copies.

The plain copy is the corpus file. A compressed file is decoded for the other
copies, and the gzip copy is the decoded text compressed with gzip. The
library maps a plain file at MMAP_THRESHOLD of src/compression.rs.
A decoded text that large is the mapped copy as it is; a smaller one gets
legal 13-line frames in front until the copy reaches that threshold, which
adds that many frames to an accepted file and keeps the class
of a rejected one. A file rejected at line 1 gets the frames after its text,
past the error, since a frame in front would move its first line.

A read matches when it gives the manifest's outcome and frame count, with the
added frames, or its error class (the class names of src/error.rs, the three
section classes as one); neither binding reports a line. Where the manifest
names no frame count, every read of the file must give the same one. A Python
str holds no bytes that are not UTF-8, so read_con_string skips such a file,
and a build without zstd rejects a zstd file with the message that names the
feature; that rejection is counted as the build's outcome for that file.

    python paper/cpc/scripts/corpus_paths.py            # writes data/corpus_paths.json
    python paper/cpc/scripts/corpus_paths.py --check    # compares a rerun with that file
    python paper/cpc/scripts/corpus_paths.py --tables   # rewrites the TeX from that file only

Build the module and both libraries first: pixi run cpc-readcon, cpc-clib and
cpc-clib-parallel.
"""
from __future__ import annotations

import argparse
import ctypes
import gzip
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import provenance  # noqa: E402
from error_class import classify, normal  # noqa: E402

ROOT = SCRIPTS.parent
REPO = provenance.REPO
CONF = REPO / "resources" / "conformance"
C31 = ROOT / "data" / "corpus31"
OUT = ROOT / "data" / "corpus_paths.json"
MACROS = ROOT / "src" / "figures" / "generated" / "corpus_paths_macros.tex"
TABLE = ROOT / "src" / "figures" / "generated" / "corpus_paths_table.tex"
CLIB = Path(os.environ.get("READCON_LIB") or REPO / "target" / "release" / "libreadcon_core.so")
CLIB_PARALLEL = Path(os.environ.get("READCON_LIB_PARALLEL")
                     or REPO / "target" / "clib-parallel" / "release" / "libreadcon_core.so")
def map_bytes() -> int:
    """MMAP_THRESHOLD of src/compression.rs at the commit of src/commit.tex, the wkMmapBytes of the manuscript."""
    from worked_example import commit, release_thresholds

    return release_thresholds(commit())["mmap_bytes"]


THREADS = (("1", 1), ("2", 2), ("8", 8), ("default", None))
# One legal frame of 13 lines, as in tests/every_path/mod.rs. Its empty
# section list keeps a blank line after it from opening a velocity block.
PAD = (
    "pad\n"
    '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu",'
    '"time":"fs"},"sections":[]}\n'
    "10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0 0\n1\n2\n195.084\nPt\nCoordinates of Component 1\n"
    "0.0 0.0 0.0 0 0\n2.5 2.5 0.0 0 1\n"
)
BUILDS = {
    "wheel": ("Python module", ["python", "zstd", "parallel"]),
    "clib": ("C library, default build", []),
    "clib_parallel": ("C library with parallel", ["parallel"]),
}
# Each entry point of a build: the copy it reads and whether it takes a thread setting.
ENTRIES = {
    "wheel": (("string", "text", True, r"\texttt{read\_con\_string}"),
              ("file", "plain", True, r"\texttt{read\_con}, plain file"),
              ("mapped", "mapped", True, r"\texttt{read\_con}, mapped file"),
              ("gzip", "gzip", True, r"\texttt{read\_con}, gzip file"),
              ("iter", "plain", False, r"\texttt{iter\_con}, plain file"),
              ("iter_mmap", "mapped", False, r"\texttt{iter\_con(mmap=True)}, mapped file"),
              ("iter_stream", "plain", False, r"\texttt{iter\_con(stream=True)}, plain file"),
              ("iter_stream_gzip", "gzip", False, r"\texttt{iter\_con(stream=True)}, gzip file"),
              ("count", "plain", False, r"\texttt{count\_frames}, plain file"),
              ("count_mapped", "mapped", False, r"\texttt{count\_frames}, mapped file"),
              ("count_gzip", "gzip", False, r"\texttt{count\_frames}, gzip file")),
    "clib": (("buffer", "text", False, r"\texttt{read\_con\_buffer\_iterator}"),
             ("file", "plain", True, r"\texttt{rkr\_read\_all\_frames\_n\_threads}, plain file"),
             ("mapped", "mapped", True, r"\texttt{rkr\_read\_all\_frames\_n\_threads}, mapped file"),
             ("gzip", "gzip", True, r"\texttt{rkr\_read\_all\_frames\_n\_threads}, gzip file"),
             ("file_iter", "plain", False, r"\texttt{read\_con\_file\_iterator}, plain file"),
             ("count", "plain", False, r"\texttt{rkr\_count\_frames}, plain file"),
             ("count_mapped", "mapped", False, r"\texttt{rkr\_count\_frames}, mapped file"),
             ("count_gzip", "gzip", False, r"\texttt{rkr\_count\_frames}, gzip file")),
}
ENTRIES["clib_parallel"] = ENTRIES["clib"]


def copy_of(key: str) -> str:
    """The copy of the corpus file that the read ``key`` reads."""
    build, name, _ = key.split("/")
    return next(c for e, c, _, _ in ENTRIES[build] if e == name)


def read_keys(build: str) -> list[str]:
    keys = []
    for entry, _, threaded, _ in ENTRIES[build]:
        keys += [f"{build}/{entry}/{label}" for label, _ in THREADS] if threaded else [f"{build}/{entry}/serial"]
    return keys


def corpus() -> list[dict]:
    import tomllib

    files = []
    manifest = tomllib.loads((CONF / "manifest.toml").read_text())
    for kind, expected in (("valid", "accept"), ("invalid", "reject")):
        for entry in manifest[kind]:
            files.append({"corpus": "conformance", "path": CONF / entry["path"], "expected": expected,
                          "frames": None, "error": entry.get("error"), "line": None})
    for entry in tomllib.loads((C31 / "manifest.toml").read_text())["file"]:
        files.append({"corpus": "corpus31", "path": C31 / entry["file"], "expected": entry["expected"],
                      "frames": entry.get("frames"), "error": entry.get("error"), "line": entry.get("line")})
    return files


def compression(raw: bytes) -> str | None:
    if raw[:2] == b"\x1f\x8b":
        return "gzip"
    if raw[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    return None


def decoded(raw: bytes, kind: str | None) -> bytes:
    if kind == "gzip":
        return gzip.decompress(raw)
    if kind == "zstd":
        import zstandard

        return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw), read_across_frames=True).read()
    return raw


def padding(text: bytes, entry: dict) -> tuple[str, bytes, int]:
    """Where the frames that bring the mapped copy to the mapping threshold go, the copy, and how many there are."""
    if len(text) >= map_bytes():
        return "none", text, 0
    pad = (PAD.replace("\n", "\r\n") if b"\r\n" in text else PAD).encode()
    copies = map_bytes() // len(pad) + 1
    if entry["expected"] == "reject" and entry["line"] == 1:
        if not text.endswith(b"\n"):
            raise SystemExit(f"{entry['path']}: a file rejected at line 1 must end with a newline")
        return "end", text + pad * copies, copies
    return "front", pad * copies + text, copies


def prepare(files: list[dict], work: Path) -> list[dict]:
    """The copies of every corpus file in ``work``, and what each read of them should give."""
    jobs = []
    for i, entry in enumerate(files):
        raw = entry["path"].read_bytes()
        kind = compression(raw)
        text = decoded(raw, kind)
        where, mapped, added = padding(text, entry)
        (work / f"{i}.txt").write_bytes(text)
        (work / f"{i}.mapped.con").write_bytes(mapped)
        (work / f"{i}.con.gz").write_bytes(gzip.compress(text, mtime=0))
        try:
            text.decode("utf-8")
            utf8 = True
        except UnicodeDecodeError:
            utf8 = False
        jobs.append({"id": str(i), "plain": str(entry["path"]), "text": str(work / f"{i}.txt"),
                     "mapped": str(work / f"{i}.mapped.con"), "gzip": str(work / f"{i}.con.gz"),
                     "compressed": kind, "utf8": utf8, "padding": where, "added": added})
    return jobs


def first_class(exc: BaseException) -> str:
    return classify(exc)[0]


def wheel_child(jobs: list[dict]) -> dict:
    import readcon

    def verdict(call, size=len) -> str:
        try:
            frames = call()
        except Exception as exc:  # noqa: BLE001
            return f"reject {first_class(exc)}"
        except BaseException as exc:
            if type(exc).__name__ != "PanicException":
                raise
            return "crash"
        return f"accept {size(frames)}"

    out = {}
    for job in jobs:
        got = {}
        raw = Path(job["text"]).read_bytes()
        for label, n in THREADS:
            if job["utf8"]:
                text = raw.decode("utf-8")
                got[f"wheel/string/{label}"] = verdict(lambda: readcon.read_con_string(text, n_threads=n))
            else:
                got[f"wheel/string/{label}"] = "skip"
            for entry in ("plain", "mapped", "gzip"):
                key = {"plain": "file"}.get(entry, entry)
                got[f"wheel/{key}/{label}"] = verdict(lambda: readcon.read_con(job[entry], n_threads=n))
        got["wheel/iter/serial"] = verdict(lambda: list(readcon.iter_con(job["plain"])))
        got["wheel/iter_mmap/serial"] = verdict(lambda: list(readcon.iter_con(job["mapped"], mmap=True)))
        got["wheel/iter_stream/serial"] = verdict(lambda: list(readcon.iter_con(job["plain"], stream=True)))
        got["wheel/iter_stream_gzip/serial"] = verdict(lambda: list(readcon.iter_con(job["gzip"], stream=True)))
        for entry in ("plain", "mapped", "gzip"):
            key = {"plain": "count"}.get(entry, f"count_{entry}")
            got[f"wheel/{key}/serial"] = verdict(lambda: readcon.count_frames(job[entry]), size=int)
        out[job["id"]] = got
    return out


def clib_child(build: str, library: Path, jobs: list[dict]) -> dict:
    lib = ctypes.CDLL(str(library))
    vp, cp, size = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t
    for name, args, res in (
        ("read_con_buffer_iterator", [vp, size], vp),
        ("read_con_file_iterator", [cp], vp),
        ("con_frame_iterator_next_status", [vp, ctypes.POINTER(vp)], ctypes.c_int),
        ("con_frame_iterator_error_message", [vp], cp),
        ("free_con_frame_iterator", [vp], None),
        ("free_rkr_frame", [vp], None),
        ("rkr_read_all_frames_n_threads", [cp, ctypes.POINTER(size), size], ctypes.POINTER(vp)),
        ("free_rkr_frame_array", [ctypes.POINTER(vp), size], None),
        ("rkr_last_error_message", [], cp),
        ("rkr_count_frames", [cp], size),
    ):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res

    def rejected(message: bytes | None) -> str:
        return f"reject {first_class(RuntimeError((message or b'').decode('utf-8', 'replace')))}"

    def iterate(it) -> str:
        if not it:
            return rejected(lib.rkr_last_error_message())
        frame, frames = vp(), 0
        while True:
            status = lib.con_frame_iterator_next_status(it, ctypes.byref(frame))
            if status != 0:
                break
            lib.free_rkr_frame(frame)
            frames += 1
        message = lib.con_frame_iterator_error_message(it)
        lib.free_con_frame_iterator(it)
        return f"accept {frames}" if status == -14 else rejected(message)

    def read_all(path: str, n: int | None) -> str:
        count = size(0)
        frames = lib.rkr_read_all_frames_n_threads(path.encode(), ctypes.byref(count), n or 0)
        if not frames:
            return rejected(lib.rkr_last_error_message())
        lib.free_rkr_frame_array(frames, count.value)
        return f"accept {count.value}"

    def count(path: str) -> str:
        frames = lib.rkr_count_frames(path.encode())
        if frames == 2 ** (8 * ctypes.sizeof(size)) - 1:
            return rejected(lib.rkr_last_error_message())
        return f"accept {frames}"

    out = {}
    for job in jobs:
        got = {}
        raw = Path(job["text"]).read_bytes()
        buffer = ctypes.create_string_buffer(raw, len(raw))
        got[f"{build}/buffer/serial"] = iterate(lib.read_con_buffer_iterator(buffer, len(raw)))
        for label, n in THREADS:
            for entry in ("plain", "mapped", "gzip"):
                key = {"plain": "file"}.get(entry, entry)
                got[f"{build}/{key}/{label}"] = read_all(job[entry], n)
        got[f"{build}/file_iter/serial"] = iterate(lib.read_con_file_iterator(job["plain"].encode()))
        for entry in ("plain", "mapped", "gzip"):
            key = {"plain": "count"}.get(entry, f"count_{entry}")
            got[f"{build}/{key}/serial"] = count(job[entry])
        out[job["id"]] = got
    return out


def run_child(build: str, jobs_path: Path) -> dict:
    argv = [sys.executable, str(Path(__file__).resolve()), "--child", build, str(jobs_path)]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise SystemExit(f"the {build} reads ended with exit status {proc.returncode}:\n{tail}")
    return json.loads(proc.stdout)


def wanted(entry: dict, job: dict, key: str) -> str | None:
    """What the read ``key`` of ``entry`` should give: 'accept N', 'accept' (count not named), 'reject C' or 'skip'."""
    build = key.split("/")[0]
    copy = copy_of(key)
    if copy == "text" and build == "wheel" and not job["utf8"]:
        return "skip"
    if copy == "plain" and job["compressed"] == "zstd" and "zstd" not in BUILDS[build][1]:
        return "reject Compression"
    if entry["expected"] == "reject":
        return f"reject {normal(entry['error'])}"
    added = job["added"] if copy == "mapped" else 0
    return "accept" if entry["frames"] is None else f"accept {entry['frames'] + added}"


def matches(want: str, got: str) -> bool:
    if want == "accept":
        return got.startswith("accept ")
    if want.startswith("reject ") and got.startswith("reject "):
        return normal(got.split()[1]) == want.split()[1]
    return want == got


def results(jobs: list[dict], files: list[dict], got: dict) -> dict:
    keys = [k for build in BUILDS for k in read_keys(build)]
    summary = {k: {"reads": 0, "skipped": 0, "no_zstd": 0, "differ": []} for k in keys}
    rows = []
    for entry, job in zip(files, jobs):
        name = provenance.portable(entry["path"])
        row_got = {k: got[k.split("/")[0]][job["id"]][k] for k in keys}
        differ, counts = set(), set()
        for key in keys:
            want = wanted(entry, job, key)
            if want == "skip":
                summary[key]["skipped"] += 1
                continue
            summary[key]["reads"] += 1
            summary[key]["no_zstd"] += want == "reject Compression"
            if not matches(want, row_got[key]):
                differ.add(key)
            elif want == "accept":
                added = job["added"] if copy_of(key) == "mapped" else 0
                counts.add(int(row_got[key].split()[1]) - added)
        if len(counts) > 1:
            differ |= {k for k in keys if wanted(entry, job, k) == "accept"}
        for key in differ:
            summary[key]["differ"].append(name)
        rows.append({"corpus": entry["corpus"], "file": name, "expected": entry["expected"],
                     "frames": entry["frames"], "class": normal(entry["error"]) if entry["error"] else None,
                     "compressed": job["compressed"], "utf8": job["utf8"],
                     "mapped": {"padding": job["padding"], "frames": job["added"]}, "differ": sorted(differ),
                     "got": row_got})
    for s in summary.values():
        s["match"] = s["reads"] - len(s["differ"])
    totals = {"files": len(rows), "conformance": sum(r["corpus"] == "conformance" for r in rows),
              "corpus31": sum(r["corpus"] == "corpus31" for r in rows), "read_kinds": len(keys),
              "reads": sum(s["reads"] for s in summary.values()), "match": sum(s["match"] for s in summary.values()),
              "skipped": sum(s["skipped"] for s in summary.values()),
              "not_text": sum(not r["utf8"] for r in rows),
              "no_zstd_files": sum(r["compressed"] == "zstd" for r in rows),
              "padded_front": sum(r["mapped"]["padding"] == "front" for r in rows),
              "padded_end": sum(r["mapped"]["padding"] == "end" for r in rows),
              "mapped_as_is": sum(r["mapped"]["padding"] == "none" for r in rows),
              "map_bytes": map_bytes(), "pad_lines": PAD.count("\n"),
              "files_differ": sorted(r["file"] for r in rows if r["differ"])}
    totals["differ"] = totals["reads"] - totals["match"]
    by_build = {b: {"reads": sum(summary[k]["reads"] for k in read_keys(b)),
                    "match": sum(summary[k]["match"] for k in read_keys(b))} for b in BUILDS}
    return {"totals": totals, "by_build": by_build, "reads": summary, "files": rows}


def macros(record: dict) -> str:
    t, b = record["totals"], record["by_build"]
    values = {
        "cpathsFiles": t["files"], "cpathsConformance": t["conformance"], "cpathsCorpusThreeOne": t["corpus31"],
        "cpathsReadKinds": t["read_kinds"], "cpathsReads": f"{t['reads']:,}", "cpathsMatch": f"{t['match']:,}",
        "cpathsDiffer": t["differ"], "cpathsNotText": t["not_text"], "cpathsZstdFiles": t["no_zstd_files"],
        "cpathsPaddedFront": t["padded_front"], "cpathsPaddedEnd": t["padded_end"],
        "cpathsMappedAsIs": t["mapped_as_is"],
        "cpathsWheelReads": f"{b['wheel']['reads']:,}", "cpathsClibReads": f"{b['clib']['reads']:,}",
        "cpathsClibParallelReads": f"{b['clib_parallel']['reads']:,}",
        "cpathsPadLines": t["pad_lines"],
    }
    return ("% Written by paper/cpc/scripts/corpus_paths.py from data/corpus_paths.json.\n"
            + "".join(f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()))


def table(record: dict) -> str:
    lines = [
        "% Written by paper/cpc/scripts/corpus_paths.py from data/corpus_paths.json.",
        r"\begin{table}[tbp]", r"\centering", r"\small",
        r"\caption{Both corpora on the frame readers and the frame count of the Python module and the C library.",
        r"A cell gives the reads that return the outcome of the manifest, of all reads at that thread setting.",
        r"The \cpathsFiles{} files are the \cpathsConformance{} of the conformance corpus and the "
        r"\cpathsCorpusThreeOne{} of the CON 3.1 corpus.",
        r"A read matches when it gives the manifest's outcome and frame count, or its error class; neither binding "
        r"reports a line, and where the manifest names no frame count every read of the file gives the same one.",
        r"The plain file is the corpus file; the mapped file is the decoded text at the mapping threshold or beyond, "
        r"with legal \cpathsPadLines-line frames in front of a smaller text, or "
        r"after a text rejected on its first line, which add their frames to the count; the gzip file is the "
        r"decoded text compressed with gzip.",
        r"A Python str cannot hold the \cpathsNotText{} files that are not UTF-8, so \texttt{read\_con\_string} "
        r"reads the others.",
        r"The C library has no zstd in either build and rejects the \cpathsZstdFiles{} zstd files in the plain "
        r"file, file iterator and frame count rows with the message that names the feature, as it documents.",
        r"The default build has no Rayon and parses on one thread at every setting, and the release archives "
        r"contain the parallel build.}",
        r"\label{tab:corpus-paths}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}llrrrrr@{}}", r"\toprule",
        r"Build & Entry point & 1 thread & 2 threads & 8 threads & Default & Serial \\", r"\midrule",
    ]
    for build, (label, _) in BUILDS.items():
        first = True
        for entry, _, threaded, tex in ENTRIES[build]:
            cells = []
            for th, _ in THREADS:
                s = record["reads"].get(f"{build}/{entry}/{th}")
                cells.append(f"{s['match']}/{s['reads']}" if threaded and s else "--")
            s = record["reads"].get(f"{build}/{entry}/serial")
            cells.append(f"{s['match']}/{s['reads']}" if not threaded and s else "--")
            lines.append(f"{label if first else ''} & {tex} & {' & '.join(cells)} \\\\")
            first = False
        lines.append(r"\midrule" if build != list(BUILDS)[-1] else r"\bottomrule")
    lines += [r"\end{tabular}}", r"\end{table}", ""]
    return "\n".join(lines)


def comparable(record: dict) -> dict:
    prov = record["provenance"]
    builds = [prov["build"], *prov["c_libraries"].values()]
    return {"results": record["results"], "digests": sorted({b["library_digest"] for b in builds})}


def measure() -> dict:
    for library, task in ((CLIB, "cpc-clib"), (CLIB_PARALLEL, "cpc-clib-parallel")):
        if not library.is_file():
            sys.exit(f"{library} is missing; build it with pixi run {task}")
        stale = provenance.newer_sources(library)
        if stale:
            sys.exit(f"{library} is older than {', '.join(stale[:3])}; rebuild it with pixi run {task}")
    builds = {"wheel": {**provenance.readcon_build(), "features": BUILDS["wheel"][1]},
              "clib": {**provenance.binary_build(CLIB), "features": BUILDS["clib"][1]},
              "clib_parallel": {**provenance.binary_build(CLIB_PARALLEL), "features": BUILDS["clib_parallel"][1]}}
    if builds["wheel"]["newer_sources"]:
        sys.exit(f"the readcon module is older than {builds['wheel']['newer_sources'][0]}; pixi run cpc-readcon")
    files = corpus()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        jobs = prepare(files, work)
        jobs_path = work / "jobs.json"
        jobs_path.write_text(json.dumps(jobs))
        got = {build: run_child(build, jobs_path) for build in BUILDS}
    return {
        "manifests": [provenance.portable(CONF / "manifest.toml"), provenance.portable(C31 / "manifest.toml")],
        "threads": [label for label, _ in THREADS],
        "results": results(jobs, files, got),
        "provenance": {"build": builds["wheel"],
                       "c_libraries": {name: builds[name] for name in ("clib", "clib_parallel")},
                       "host": provenance.host(), "peers": {"python": platform.python_version()}},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help="record (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="compare a rerun with --out instead of writing it")
    parser.add_argument("--tables", action="store_true", help="rewrite the TeX from --out only; read nothing")
    parser.add_argument("--child", nargs=2, metavar=("BUILD", "JOBS"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        build, jobs = args.child[0], json.loads(Path(args.child[1]).read_text())
        library = {"clib": CLIB, "clib_parallel": CLIB_PARALLEL}.get(build)
        print(json.dumps(wheel_child(jobs) if build == "wheel" else clib_child(build, library, jobs)))
        return 0
    if args.tables:
        stored = json.loads(args.out.read_text())["results"]
        MACROS.write_text(macros(stored))
        TABLE.write_text(table(stored))
        print(f"wrote {MACROS} and {TABLE} from {args.out}")
        return 0
    record = measure()
    r = record["results"]
    t = r["totals"]
    print(f"corpus paths: {t['files']} files, {t['match']} of {t['reads']} reads match the manifest over "
          f"{t['read_kinds']} entry points and thread settings, {t['differ']} differ")
    for build, counts in r["by_build"].items():
        print(f"  {build}: {counts['match']} of {counts['reads']}")
    if args.check:
        stored = json.loads(args.out.read_text())
        if comparable(stored) != comparable(record):
            print(f"{args.out} differs from this run", file=sys.stderr)
            return 1
        for path, text in ((MACROS, macros(stored["results"])), (TABLE, table(stored["results"]))):
            if not path.is_file() or path.read_text() != text:
                print(f"{path} differs from {args.out}", file=sys.stderr)
                return 1
        print(f"{args.out}, {MACROS.name} and {TABLE.name} match this run")
    else:
        args.out.write_text(json.dumps(record, indent=1) + "\n")
        MACROS.write_text(macros(r))
        TABLE.write_text(table(r))
        print(f"wrote {args.out}, {MACROS} and {TABLE}")
    return 1 if t["differ"] or t["files_differ"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
