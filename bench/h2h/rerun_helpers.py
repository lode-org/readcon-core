#!/usr/bin/env python3
"""Helpers for the Snakemake ``rerun_release`` release-tip rerun driver."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
CPC = ROOT / "paper" / "cpc"

SAVED_RECORD_PREFIXES = (
    "bench/h2h/scaling",
    "bench/h2h/formats/v0.23.3",
    "bench/h2h/million/v0.23.3",
    "bench/h2h/results",
    "bench/h2h/logs",
    "bench/fidelity/results",
    "paper/cpc/bench/results/r0174",
    "paper/cpc/bench/results/v0.23.3",
    "paper/cpc/data",
    "paper/cpc/logs",
    "benches/results",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def require_clean_and_remote() -> str:
    status = _git("status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        raise SystemExit(status.stderr or "git status failed")
    if status.stdout.strip():
        raise SystemExit(
            "refusing release rerun on a dirty tree:\n" + status.stdout.strip()
        )
    head = _git("rev-parse", "HEAD")
    if head.returncode != 0:
        raise SystemExit(head.stderr or "git rev-parse HEAD failed")
    sha = head.stdout.strip()
    branches = _git("branch", "-r", "--contains", "HEAD")
    if branches.returncode != 0 or not branches.stdout.strip():
        raise SystemExit(
            f"refusing release rerun: {sha} is not contained on any remote branch "
            "(git branch -r --contains HEAD returned none)"
        )
    return sha


def refuse_saved_output(path_str: str) -> None:
    resolved = Path(ROOT, path_str).resolve()
    try:
        rel = resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise SystemExit(f"refusing output outside repository: {path_str}") from exc
    for prefix in SAVED_RECORD_PREFIXES:
        if rel == prefix or rel.startswith(prefix + "/"):
            raise SystemExit(f"refusing to write a saved record directory: {rel}")


def run_dlpack_cost(cpc_out: Path, repeats: int) -> None:
    if repeats < 6:
        raise SystemExit("repeats must be at least 6")
    manifest = CPC / "bench" / "dlpack_cost" / "Cargo.toml"
    subprocess.run(
        ["cargo", "build", "--release", "--manifest-path", str(manifest)],
        cwd=ROOT,
        check=True,
    )
    binary = CPC / "bench" / "dlpack_cost" / "target" / "release" / "dlpack_cost"
    proc = subprocess.run(
        ["taskset", "-c", "0", str(binary)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    body = proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n"
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"date_utc={when}\ncommand={binary.relative_to(ROOT)}\n"
    data_dir = cpc_out / "data"
    logs_dir = cpc_out / "logs"
    gen_dir = cpc_out / "generated"
    for folder in (data_dir, logs_dir, gen_dir):
        folder.mkdir(parents=True, exist_ok=True)
    record = data_dir / "dlpack_cost.txt"
    record.write_text(header + body + "exit=0\n", encoding="utf-8")
    (logs_dir / "dlpack_cost.log").write_text(
        header + body + "exit=0\n", encoding="utf-8"
    )

    sys.path.insert(0, str(CPC / "scripts"))
    import bench_dlpack

    bench_dlpack.OUT = gen_dir
    bench_dlpack.LOG = logs_dir / "dlpack-exchange.log"
    bench_dlpack.MACROS = gen_dir / "dlpack_exchange_values.tex"
    bench_dlpack.TABLE = gen_dir / "dlpack_table.tex"
    bench_dlpack.FIGURE = gen_dir / "dlpack.pdf"
    bench_dlpack.REPEATS = max(6, repeats)
    rc = bench_dlpack.main()
    if rc != 0:
        raise SystemExit(f"bench_dlpack failed with exit code {rc}")


def run_mpi_v2(cpc_out: Path, repeats: int) -> None:
    if repeats < 6:
        raise SystemExit("repeats must be at least 6")
    logs_dir = cpc_out / "logs"
    results_dir = cpc_out / "results" / "v2"
    logs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(CPC / "bench"))
    import run_mpi_v2

    run_mpi_v2.OUT = results_dir
    run_mpi_v2.LOG = logs_dir / "mpi.log"
    run_mpi_v2.REPEATS = max(6, repeats)
    run_mpi_v2.main()


def run_mpi_fallback(cpc_out: Path) -> None:
    logs_dir = cpc_out / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(CPC / "scripts"))
    import mpi_fallback

    mpi_fallback.LOG = logs_dir / "mpi-fallback.log"
    rc = mpi_fallback.main()
    if rc != 0:
        raise SystemExit(f"mpi_fallback failed with exit code {rc}")


def run_reader_exchange_cpc(cpc_out: Path, repeats: int) -> None:
    if repeats < 6:
        raise SystemExit("repeats must be at least 6")
    logs_dir = cpc_out / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(CPC / "scripts"))
    import bench_readers

    bench_readers.LOG = logs_dir / "reader-exchange.log"
    bench_readers.REPEATS = max(6, repeats)
    rc = bench_readers.main()
    if rc != 0:
        raise SystemExit(f"bench_readers failed with exit code {rc}")


def run_db_appendix(cpc_out: Path, repeats: int) -> None:
    if repeats < 6:
        raise SystemExit("repeats must be at least 6")
    db_out = cpc_out / "data" / "db"
    db_out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["READCON_DB_REPEATS"] = str(max(12, repeats))
    subprocess.run(
        [sys.executable, str(CPC / "scripts" / "make_db_traces.py")],
        cwd=ROOT,
        env=env,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(CPC / "scripts" / "measure_db.py"),
            "--out",
            str(db_out),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )


def run_novel_fidelity(cpc_out: Path) -> None:
    novel_out = cpc_out / "data" / "novel"
    novel_out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(CPC / "scripts" / "measure_novel.py"),
            "--out",
            str(novel_out),
        ],
        cwd=ROOT,
        check=True,
    )


def run_camp24_extras(scaling_out: Path, repeats: int) -> None:
    if repeats < 6:
        raise SystemExit("repeats must be at least 6")
    camp_out = scaling_out / "camp24"
    camp_out.mkdir(parents=True, exist_ok=True)
    (camp_out / "logs").mkdir(parents=True, exist_ok=True)
    import camp24_run

    camp24_run.OUT = camp_out
    camp24_run.LOGS = camp_out / "logs"
    camp24_run.REPEATS = max(6, repeats)
    camp24_run.ranked()
    camp24_run.ab_ranked()
    camp24_run.conbin()
    camp24_run.conbin_writes()
    camp24_run.host()


def write_formats_lscpu(formats_dir: Path) -> None:
    host_json = formats_dir / "1m" / "host.json"
    if not host_json.is_file():
        raise SystemExit(f"missing {host_json} to extract lscpu.txt")
    data = json.loads(host_json.read_text(encoding="utf-8"))
    lscpu = data.get("lscpu")
    if not lscpu:
        lscpu = subprocess.check_output(["lscpu"], text=True)
    (formats_dir / "lscpu.txt").write_text(lscpu, encoding="utf-8")


def write_superseded_markers(
    tip: str,
    scaling_out: Path,
    formats_out: Path,
    million_out: Path,
    million_results_out: Path,
    cpc_out: Path,
) -> None:
    replacements = {
        ROOT / "bench/h2h/scaling/rel1": scaling_out,
        ROOT / "bench/h2h/scaling/v0.23.3/mpi-pwrite": scaling_out / "camp24",
        ROOT / "bench/h2h/formats/v0.23.3": formats_out,
        ROOT / "bench/h2h/million/v0.23.3": million_out,
        ROOT / "paper/cpc/bench/results/v0.23.3/million": million_results_out,
        ROOT / "paper/cpc/data/db": cpc_out / "data" / "db",
        ROOT / "paper/cpc/data/novel": cpc_out / "data" / "novel",
        ROOT / "paper/cpc/data/mpi": cpc_out / "results" / "v2",
        ROOT / "paper/cpc/logs": cpc_out / "logs",
    }
    for old_dir, new_dir in replacements.items():
        if not old_dir.is_dir():
            continue
        rel_new = new_dir.resolve().relative_to(ROOT.resolve()).as_posix()
        (old_dir / "SUPERSEDED.md").write_text(
            f"Superseded by {rel_new}.\nTip: {tip}.\n",
            encoding="utf-8",
        )
    marker = scaling_out / "SUPERSEDED.OK"
    marker.write_text(f"tip {tip}\n", encoding="utf-8")


def finalize_paper(
    scaling_out: Path,
    formats_out: Path,
    million_results_out: Path,
    cpc_out: Path,
) -> None:
    env = os.environ.copy()
    env["FORMAT_H2H_RECORDS"] = str(formats_out.resolve())
    env["READS_JSON"] = str((scaling_out / "reads.json").resolve())
    env["READER_EXCHANGE_JSON"] = str((scaling_out / "reader-exchange.json").resolve())
    env["DLPACK_COST_RECORD"] = str((cpc_out / "data" / "dlpack_cost.txt").resolve())
    env["MPI_LOG"] = str((cpc_out / "logs" / "mpi.log").resolve())
    env["READCON_DB_LOG"] = str((scaling_out / "db.log").resolve())
    env["READER_EXCHANGE_LOG"] = str(
        (cpc_out / "logs" / "reader-exchange.log").resolve()
    )
    env["MILLION_RESULTS_DIR"] = str(million_results_out.resolve())

    subprocess.run(
        [sys.executable, str(CPC / "scripts" / "clause_coverage.py")],
        cwd=ROOT,
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(CPC / "scripts" / "regen_paper.py")],
        cwd=ROOT,
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(CPC / "scripts" / "trace_numbers.py"), "--check"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    (scaling_out / "PAPER_OK").write_text("ok\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dlpack = sub.add_parser("dlpack-cost")
    p_dlpack.add_argument("--cpc-out", type=Path, required=True)
    p_dlpack.add_argument("--repeats", type=int, default=6)

    p_mpi = sub.add_parser("mpi-v2")
    p_mpi.add_argument("--cpc-out", type=Path, required=True)
    p_mpi.add_argument("--repeats", type=int, default=6)

    p_fb = sub.add_parser("mpi-fallback")
    p_fb.add_argument("--cpc-out", type=Path, required=True)

    p_re = sub.add_parser("reader-exchange-cpc")
    p_re.add_argument("--cpc-out", type=Path, required=True)
    p_re.add_argument("--repeats", type=int, default=6)

    p_db = sub.add_parser("db-appendix")
    p_db.add_argument("--cpc-out", type=Path, required=True)
    p_db.add_argument("--repeats", type=int, default=12)

    p_nv = sub.add_parser("novel-fidelity")
    p_nv.add_argument("--cpc-out", type=Path, required=True)

    p_c24 = sub.add_parser("camp24-extras")
    p_c24.add_argument("--scaling-out", type=Path, required=True)
    p_c24.add_argument("--repeats", type=int, default=6)

    p_ls = sub.add_parser("formats-lscpu")
    p_ls.add_argument("--formats-out", type=Path, required=True)

    p_sup = sub.add_parser("supersede")
    p_sup.add_argument("--tip", required=True)
    p_sup.add_argument("--scaling-out", type=Path, required=True)
    p_sup.add_argument("--formats-out", type=Path, required=True)
    p_sup.add_argument("--million-out", type=Path, required=True)
    p_sup.add_argument("--million-results-out", type=Path, required=True)
    p_sup.add_argument("--cpc-out", type=Path, required=True)

    p_pap = sub.add_parser("finalize-paper")
    p_pap.add_argument("--scaling-out", type=Path, required=True)
    p_pap.add_argument("--formats-out", type=Path, required=True)
    p_pap.add_argument("--million-results-out", type=Path, required=True)
    p_pap.add_argument("--cpc-out", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "dlpack-cost":
        run_dlpack_cost(ROOT / args.cpc_out, args.repeats)
    elif args.cmd == "mpi-v2":
        run_mpi_v2(ROOT / args.cpc_out, args.repeats)
    elif args.cmd == "mpi-fallback":
        run_mpi_fallback(ROOT / args.cpc_out)
    elif args.cmd == "reader-exchange-cpc":
        run_reader_exchange_cpc(ROOT / args.cpc_out, args.repeats)
    elif args.cmd == "db-appendix":
        run_db_appendix(ROOT / args.cpc_out, args.repeats)
    elif args.cmd == "novel-fidelity":
        run_novel_fidelity(ROOT / args.cpc_out)
    elif args.cmd == "camp24-extras":
        run_camp24_extras(ROOT / args.scaling_out, args.repeats)
    elif args.cmd == "formats-lscpu":
        write_formats_lscpu(ROOT / args.formats_out)
    elif args.cmd == "supersede":
        write_superseded_markers(
            args.tip,
            ROOT / args.scaling_out,
            ROOT / args.formats_out,
            ROOT / args.million_out,
            ROOT / args.million_results_out,
            ROOT / args.cpc_out,
        )
    elif args.cmd == "finalize-paper":
        finalize_paper(
            ROOT / args.scaling_out,
            ROOT / args.formats_out,
            ROOT / args.million_results_out,
            ROOT / args.cpc_out,
        )


if __name__ == "__main__":
    main()
