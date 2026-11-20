"""Run the asv suite. One-thread benchmarks are pinned to cpu 0."""

from __future__ import annotations

import json
import os
import site
import subprocess
import sys

import arms

BENCH = arms.BENCH
WORK = arms.WORK


def machine_file(home, name: str, cores: int) -> None:
    home.mkdir(parents=True, exist_ok=True)
    document = {
        "version": 1,
        name: {
            "machine": name,
            "os": "Linux",
            "arch": "x86_64",
            "cpu": "unspecified",
            "num_cpu": str(cores),
            "ram": "unspecified",
        },
    }
    path = home / ".asv-machine.json"
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def invoke(args: list[str], env: dict, log_name: str) -> None:
    log_path = WORK / log_name
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            args,
            cwd=BENCH,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise SystemExit(f"asv exited {completed.returncode} ({log_name})")


def main() -> int:
    arms.ensure_inputs()
    eon_root = arms.fetch_eon(WORK / "eon-src")
    prefix = WORK / "prefix-tip-a"
    if not prefix.is_dir():
        raise SystemExit("tip-a prefix is missing")
    revision = subprocess.check_output(
        ["git", "-C", str(arms.REPO), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    cores = arms.nproc()
    name = arms.machine_hash()[:12]
    home = WORK / "asv-home"
    machine_file(home, name, cores)
    # HOME is redirected so the machine file is not the login home.
    # Record the user site first; it is derived from HOME.
    user_site = site.getusersitepackages()
    base = os.environ.copy()
    base["HOME"] = str(home)
    base["PYTHONPATH"] = os.pathsep.join((str(prefix), str(eon_root), user_site))
    base["OMP_NUM_THREADS"] = "1"
    base["MKL_NUM_THREADS"] = "1"
    base["OPENBLAS_NUM_THREADS"] = "1"
    base["NUMEXPR_NUM_THREADS"] = "1"
    base["VECLIB_MAXIMUM_THREADS"] = "1"
    base["BLIS_NUM_THREADS"] = "1"
    pinned = dict(base)
    pinned["RAYON_NUM_THREADS"] = "1"
    invoke(
        [
            "taskset",
            "-c",
            "0",
            sys.executable,
            "-m",
            "asv",
            "run",
            "--environment",
            "existing:same",
            "--launch-method",
            "spawn",
            "--machine",
            name,
            "--set-commit-hash",
            revision,
            "-b",
            "FullFrame|CoordsOne",
        ],
        pinned,
        "asv-one.log",
    )
    wide = dict(base)
    wide["RAYON_NUM_THREADS"] = str(cores)
    invoke(
        [
            sys.executable,
            "-m",
            "asv",
            "run",
            "--environment",
            "existing:same",
            "--launch-method",
            "spawn",
            "--machine",
            name,
            "--set-commit-hash",
            revision,
            "-b",
            "CoordsAll",
        ],
        wide,
        "asv-all.log",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
