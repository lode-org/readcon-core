#!/usr/bin/env python3
"""Rewrite every table, figure and macro of the CPC paper from the committed records.

    python paper/cpc/scripts/regen_paper.py             # format only; times and measures nothing
    python paper/cpc/scripts/regen_paper.py --measure   # rerun the measurements, then format

The format steps read only committed records. The measurement steps rewrite
those records; the C-interface rows load the library that
``cargo build --release`` writes, or ``READCON_LIB``. The eOn band
(``evidence/e1_restart.py``), the resume wall times
(``scripts/run_restart_walls.py``), the file sizes (``scripts/file_sizes.py``),
the timing, memray, Cachegrind, head-to-head and binary-format records of
``bench/results/r0174``, the corpus31, corpus-path, every-path, cross-check,
probe and mutant-differential records and the test run of the release
(``scripts/test_run.py --checkout``) are separate steps. A
step that fails stops the run.

Each format step runs under an audit hook that lists the repository files it
opened for reading, the files it wrote with the files read for each, and the
programs it ran (``$ENV/bin/<name>`` for one of the environment's own
programs); ``data/trace/reads.json`` keeps that list, and
``gen_version_map.py``, the last step, names the build of every record a
generated file was written from.  A file read inside a top-level function of
the step's script counts for the outputs that function writes; a file read
elsewhere counts for every output.  readcon opens files in Rust, out of the
hook's sight, so the hook wraps the readcon functions that take a path.

Every step runs with ``SOURCE_DATE_EPOCH`` and ``FORCE_SOURCE_DATE`` set, so
the figures carry a fixed date.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
REPO = CPC.parents[1]
READS = CPC / "data" / "trace" / "reads.json"
SOURCE_DATE_EPOCH = "1794441600"

MEASURE = [
    ["scripts/failure_matrix.py"],
    ["scripts/survey_listing.py"],
    ["scripts/worked_example.py"],
    ["scripts/drift.py"],
    ["scripts/con_openers.py"],
    ["scripts/version_safety.py"],
    ["scripts/spec_corpus_recount.py"],
    ["scripts/restart_formats.py"],
    # The kernel sets of numeric_pins.KERNEL_SETS; importing numeric_pins here would pin every step.
    *[
        ["scripts/restart_formats.py", "--kernels", name]
        for name in ("nehalem", "haswell", "skylakex", "cooperlake")
    ],
    ["evidence/e5_prefactor.py"],
    ["scripts/velocity_case.py"],
    ["scripts/hcn_case.py"],
    ["scripts/gen_spec_supp.py", "--measure"],
]

# The tree is a checkout of the release with this paper/cpc in it, so spec.org is the release text.
FORMAT = [
    ["scripts/gen_release.py"],
    ["scripts/src_anchors.py"],
    ["scripts/gen_failure_tables.py"],
    ["scripts/survey_listing.py", "--tables"],
    ["scripts/spec_corpus_recount.py", "--tables"],
    ["scripts/gen_cloud_tables.py"],
    ["evidence/e5_prefactor.py", "--tables"],
    ["scripts/velocity_case.py", "--tables"],
    ["scripts/gen_case_macros.py"],
    ["scripts/gen_tables.py"],
    ["scripts/r0174_tables.py"],
    ["scripts/h2h_tables.py"],
    ["scripts/binary_formats_tables.py"],
    ["scripts/ordering_tests.py"],
    ["scripts/corpus31_results.py", "--tables"],
    ["scripts/corpus_paths.py", "--tables"],
    ["scripts/every_path_count.py", "--tables"],
    ["scripts/corpus_crosscheck.py", "--tables"],
    ["scripts/clause_coverage.py"],
    ["scripts/mutant_differential.py", "--tables"],
    ["scripts/file_sizes.py", "--table"],
    ["scripts/worked_example.py", "--tables"],
    ["scripts/test_run.py", "--tables"],
    ["scripts/sinum.py"],
    ["scripts/gen_figures.py"],
    ["scripts/plot_perf.py"],
    ["scripts/gen_spec_supp.py", "--as-is"],
    ["scripts/plot_figures.py"],
    ["scripts/plot_restart_formats.py"],
    ["scripts/plot_structures.py"],
    ["scripts/plot_supp.py"],
]

VERSION_MAP = ["scripts/gen_version_map.py"]

# Runs a step's script in this interpreter after installing the hook; argv: root, log, script, args.
HOOK = r"""
import atexit, json, os, runpy, shutil, sys
root, log, script = os.path.realpath(sys.argv[1]), sys.argv[2], sys.argv[3]
mine = os.path.realpath(script)
env_bin = os.path.join(os.path.abspath(sys.prefix), "bin")
skip = tuple(os.path.join(root, d) + os.sep for d in (".git", ".pixi", "target", "paper/cpc/.pixi"))
writing = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
read, wrote, ran, real = {}, {}, set(), {}

def relative(path):
    path = os.path.realpath(os.fsdecode(path))
    if not path.startswith(root + os.sep) or path.startswith(skip) or path.endswith((".py", ".pyc")):
        return None
    return os.path.relpath(path, root)

def task():
    names, frame = [], sys._getframe(2)
    while frame is not None:
        name = frame.f_code.co_filename
        if real.setdefault(name, os.path.realpath(name)) == mine:
            names.append(frame.f_code.co_name)
        frame = frame.f_back
    names = [n for n in reversed(names) if n not in ("<module>", "main")]
    return names[0] if names else ""

def hook(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        rel = relative(args[0])
        if rel is None:
            return
        mode, flags = args[1], args[2]
        if any(c in mode for c in "wax+") if isinstance(mode, str) else flags & writing:
            wrote.setdefault(rel, set()).add(task())
        elif rel not in wrote:
            read.setdefault(rel, set()).add(task())
    elif event == "os.rename":
        rel = relative(args[1])
        if rel is not None:
            wrote.setdefault(rel, set()).add(task())
    elif event == "subprocess.Popen":
        program = args[0] if args[0] is not None else args[1]
        program = program if isinstance(program, (str, bytes, os.PathLike)) else program[0]
        program = os.fsdecode(program).split()[0]
        found = program if os.sep in program else shutil.which(program) or program
        in_env = os.path.dirname(os.path.abspath(found)) == env_bin
        ran.add("$ENV/bin/" + os.path.basename(found) if in_env else os.path.basename(program))

def save():
    writers = set().union(*wrote.values())
    outputs = {}
    for path, tasks in sorted(wrote.items()):
        if os.path.exists(os.path.join(root, path)):
            outputs[path] = sorted(r for r, used in read.items()
                                   if "" in tasks or any(t == "" or t not in writers or t in tasks for t in used))
    with open(log, "w") as handle:
        json.dump({"read": sorted(read), "wrote": outputs, "ran": sorted(ran)}, handle)

def opens(fn, modes):
    def call(*args, **kwargs):
        for arg, mode in zip(args, modes):
            if isinstance(arg, (str, os.PathLike)) and (mode == "w" or os.path.isfile(arg)):
                sys.audit("open", os.fspath(arg), mode, os.O_WRONLY if mode == "w" else os.O_RDONLY)
        return fn(*args, **kwargs)
    return call

atexit.register(save)
sys.addaudithook(hook)
try:
    import readcon
except ImportError:
    readcon = None
for name in dir(readcon) if readcon is not None else ():
    fn = getattr(readcon, name)
    if callable(fn) and not isinstance(fn, type) and not name.endswith(("_string", "_memory")):
        modes = "r" if name.startswith(("read", "iter", "count")) else "w" if name.startswith("write") else \
            "rw" if name.startswith("convert") else ""
        if modes:
            setattr(readcon, name, opens(fn, modes))
sys.argv = sys.argv[3:]
sys.path[0] = os.path.dirname(os.path.realpath(script))
runpy.run_path(script, run_name="__main__")
"""


def run(step: list[str], env: dict[str, str], ledger: list[dict] | None = None) -> None:
    start = time.perf_counter()
    script = [str(CPC / step[0]), *step[1:]]
    with tempfile.TemporaryDirectory(prefix="regen-") as tmp:
        log = Path(tmp) / "opened.json"
        command = (
            [sys.executable, *script]
            if ledger is None
            else [sys.executable, "-c", HOOK, str(REPO), str(log), *script]
        )
        code = subprocess.run(
            command, cwd=REPO, env=env, check=False, stdout=subprocess.DEVNULL
        ).returncode
        if code:
            raise SystemExit(f"{' '.join(step)} exited {code}")
        if ledger is not None:
            ledger.append({"step": " ".join(step), **json.loads(log.read_text())})
    print(f"{' '.join(step)}: {time.perf_counter() - start:.1f} s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--measure",
        action="store_true",
        help="rerun the measurements before formatting",
    )
    args = parser.parse_args()
    env = dict(os.environ, SOURCE_DATE_EPOCH=SOURCE_DATE_EPOCH, FORCE_SOURCE_DATE="1")
    env["PATH"] = os.pathsep.join([str(Path(sys.prefix) / "bin"), env.get("PATH", "")])
    env.setdefault(
        "READCON_LIB", str(REPO / "target" / "release" / "libreadcon_core.so")
    )
    if args.measure:
        if not Path(env["READCON_LIB"]).is_file():
            raise SystemExit(
                f"{env['READCON_LIB']} is missing; run cargo build --release"
            )
        for step in MEASURE:
            run(step, env)
    # matplotlib runs fc-list when it builds its font cache, and the ledger would record that run for the first
    # step that imports matplotlib in a new HOME, so the cache is built before the ledgered steps.
    subprocess.run(
        [sys.executable, "-c", "import matplotlib.font_manager"],
        cwd=REPO,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    ledger: list[dict] = []
    for step in FORMAT:
        run(step, env, ledger)
    READS.parent.mkdir(parents=True, exist_ok=True)
    READS.write_text(
        json.dumps(
            {"script": "paper/cpc/scripts/regen_paper.py", "steps": ledger}, indent=1
        )
        + "\n"
    )
    run(VERSION_MAP, env)


if __name__ == "__main__":
    main()
