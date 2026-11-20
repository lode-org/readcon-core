"""Serial like-for-like reader benchmark.

Full-frame arms build positions, cell, symbols, masses, and fixed flags on one
thread. Coordinate-only rows stay out of the ratio column. Repeats are kept.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import arms

BENCH = arms.BENCH
REPO = arms.REPO
WORK = arms.WORK
PINS = arms.PINS
WORKER = BENCH / "worker.py"

BLAS = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def require_clean() -> str:
    status = git("status", "--porcelain")
    if status:
        fail("worktree is dirty:\n" + status)
    return git("rev-parse", "HEAD")


def publish(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def download(url: str, dest: Path, expect: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and arms.file_sha256(dest) == expect:
        return
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    digest = __import__("hashlib").sha256(data).hexdigest()
    if digest != expect:
        fail(f"download hash {digest} != {expect}")
    temporary = dest.with_name(dest.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, dest)


def build_tip(label: str) -> tuple[Path, str]:
    target = WORK / f"target-{label}"
    out = WORK / f"wheels-{label}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    log_path = WORK / f"build-{label}.log"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    env["CARGO_BUILD_JOBS"] = "2"
    env["RUSTUP_TOOLCHAIN"] = "1.88.0"
    command = [
        sys.executable,
        "-m",
        "maturin",
        "build",
        "--release",
        "--features",
        "python,zstd,mimalloc-allocator",
        "--interpreter",
        sys.executable,
        "--out",
        str(out),
    ]
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=REPO,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        fail(f"build {label} exited {completed.returncode}")
    wheels = sorted(out.glob("readcon-*.whl"))
    if len(wheels) != 1:
        fail(f"build {label} produced {len(wheels)} wheels")
    return wheels[0], arms.file_sha256(wheels[0])


def install_wheel(wheel: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(dest),
            "--no-deps",
            "--upgrade",
            str(wheel),
        ]
    )


def arm_table(cores: int) -> list[tuple[str, str, int]]:
    return [
        ("readcon_tip_a", "full-frame", 1),
        ("readcon_tip_b", "full-frame", 1),
        ("readcon_release", "full-frame", 1),
        ("ase", "full-frame", 1),
        ("eon", "full-frame", 1),
        ("readcon_positions_1", "coords-only", 1),
        ("readcon_positions_all", "coords-only", cores),
    ]


def one(
    arm: str, path: str, threads: int, prefixes: dict[str, str], eon_root: str
) -> dict:
    env = os.environ.copy()
    env.update(BLAS)
    env["RAYON_NUM_THREADS"] = str(threads)
    env.pop("PYTHONPATH", None)
    prefix = prefixes.get(arm, "")
    if prefix:
        env["READCON_PREFIX"] = prefix
        env["PYTHONPATH"] = prefix
    else:
        env.pop("READCON_PREFIX", None)
    if arm == "eon":
        env["EON_ROOT"] = eon_root
        env["PYTHONPATH"] = eon_root
    else:
        env.pop("EON_ROOT", None)
    command = [sys.executable, str(WORKER), arm, path, str(threads)]
    if threads == 1:
        command = ["taskset", "-c", "0", *command]
    completed = subprocess.run(
        command,
        input="\n",
        text=True,
        capture_output=True,
        env=env,
        cwd=BENCH,
        timeout=1800,
        check=False,
    )
    parsed = None
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith("{"):
            parsed = json_loads(line)
            break
    if parsed is None or completed.returncode != 0 or parsed.get("error"):
        detail = (completed.stderr or completed.stdout)[-500:]
        return {
            "seconds": None,
            "n_frames": 0,
            "n_atoms": 0,
            "checksum": "",
            "version": "",
            "error": parsed.get("error") if parsed else detail,
            "exit": completed.returncode,
        }
    parsed["exit"] = completed.returncode
    return parsed


def json_loads(line: str) -> dict:
    import json

    return json.loads(line)


def append_log(handle, line: str) -> None:
    handle.write(line + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    publish(path, buffer.getvalue())


def main() -> int:
    arms.assert_schedule()
    revision = require_clean()
    machine = arms.machine_hash()
    cores = arms.nproc()
    WORK.mkdir(parents=True, exist_ok=True)
    inputs = arms.ensure_inputs()
    eon_root = str(arms.fetch_eon(WORK / "eon-src"))
    tip_a_wheel, tip_a_hash = build_tip("tip-a")
    tip_b_wheel, tip_b_hash = build_tip("tip-b")
    release_pin = PINS["readcon_release"]
    release_wheel = WORK / "wheels-release" / release_pin["wheel"]
    download(release_pin["url"], release_wheel, release_pin["sha256"])
    prefix = {
        "readcon_tip_a": WORK / "prefix-tip-a",
        "readcon_tip_b": WORK / "prefix-tip-b",
        "readcon_release": WORK / "prefix-release",
        "readcon_positions_1": WORK / "prefix-tip-a",
        "readcon_positions_all": WORK / "prefix-tip-a",
    }
    install_wheel(tip_a_wheel, prefix["readcon_tip_a"])
    install_wheel(tip_b_wheel, prefix["readcon_tip_b"])
    install_wheel(release_wheel, prefix["readcon_release"])
    prefixes = {name: str(path) for name, path in prefix.items()}
    labels = {
        "readcon_tip_a": f"0.24.0 {revision} tip-a {tip_a_hash}",
        "readcon_tip_b": f"0.24.0 {revision} tip-b {tip_b_hash}",
        "readcon_release": release_pin["version"],
        "ase": PINS["ase"]["version"],
        "eon": PINS["eon_reader"]["commit"],
        "readcon_positions_1": f"0.24.0 {revision} tip-a {tip_a_hash}",
        "readcon_positions_all": f"0.24.0 {revision} tip-a {tip_a_hash}",
    }
    units = []
    for arm, work, threads in arm_table(cores):
        for spec in inputs.values():
            units.append((arm, work, threads, spec))
    log_path = WORK / "campaign.log"
    samples: list[dict] = []
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        append_log(log, f"revision {revision}")
        append_log(log, f"machine {machine}")
        append_log(log, f"nproc {cores}")
        append_log(log, f"repeats {arms.REPEATS}")
        append_log(log, "schedule ABBA-rotated")
        append_log(log, "warmup_discard no")
        append_log(log, "blas_threads 1")
        append_log(log, "taskset full-frame and coords-1 on cpu 0")
        for name, spec in inputs.items():
            append_log(
                log,
                f"input name={name} kind={spec['kind']} sha256={spec['sha256']}",
            )
        expected: dict[str, tuple[int, int, str]] = {}
        for arm, work, threads, spec in units:
            doc = one(arm, spec["path"], threads, prefixes, eon_root)
            append_log(
                log,
                "equal-work "
                f"arm={arm} work={work} threads={threads} input={spec['name']} "
                f"seconds={doc.get('seconds')} frames={doc.get('n_frames')} "
                f"atoms={doc.get('n_atoms')} checksum={doc.get('checksum')} "
                f"version={doc.get('version')} error={doc.get('error', '')}",
            )
            if doc.get("error") or doc.get("seconds") is None:
                fail(f"equal-work failed for {arm} {spec['name']}: {doc.get('error')}")
            _check_version(arm, doc["version"])
            key = spec["name"]
            found = (int(doc["n_frames"]), int(doc["n_atoms"]), doc["checksum"])
            if key not in expected:
                expected[key] = found
            elif found != expected[key]:
                fail(
                    f"equal-work mismatch {arm} {spec['name']} {found} != {expected[key]}"
                )
        for rep in range(arms.REPEATS):
            for arm, work, threads, spec in arms.abba_order(units, rep):
                doc = one(arm, spec["path"], threads, prefixes, eon_root)
                append_log(
                    log,
                    "sample "
                    f"rep={rep} arm={arm} work={work} threads={threads} "
                    f"input={spec['name']} seconds={doc.get('seconds')} "
                    f"frames={doc.get('n_frames')} atoms={doc.get('n_atoms')} "
                    f"checksum={doc.get('checksum')} version={doc.get('version')} "
                    f"error={doc.get('error', '')}",
                )
                if doc.get("error") or doc.get("seconds") is None:
                    fail(f"sample failed for {arm} {spec['name']}: {doc.get('error')}")
                _check_version(arm, doc["version"])
                found = (int(doc["n_frames"]), int(doc["n_atoms"]), doc["checksum"])
                if found != expected[spec["name"]]:
                    fail(
                        f"sample mismatch {arm} {spec['name']} rep {rep} "
                        f"{found} != {expected[spec['name']]}"
                    )
                samples.append(
                    {
                        "arm": arm,
                        "work": work,
                        "threads": str(threads),
                        "input": spec["name"],
                        "input_kind": spec["kind"],
                        "input_sha256": spec["sha256"],
                        "rep": str(rep),
                        "seconds": f"{float(doc['seconds']):.16g}",
                        "n_frames": str(found[0]),
                        "n_atoms": str(found[1]),
                        "checksum": found[2],
                        "revision": labels[arm],
                        "machine": machine,
                        "nproc": str(cores),
                    }
                )
    records, summary = summarize(samples, machine, cores)
    fields = [
        "arm",
        "work",
        "threads",
        "input",
        "input_kind",
        "input_sha256",
        "n",
        "median_s",
        "iqr_s",
        "n_frames",
        "n_atoms",
        "checksum",
        "revision",
        "machine",
        "nproc",
    ]
    write_csv(BENCH / "results" / "rows.csv", fields, records)
    write_csv(BENCH / "results" / "samples.csv", list(samples[0].keys()), samples)
    write_csv(
        BENCH / "results" / "summary.csv",
        fields + ["ratio_over_tip", "aa_ratio"],
        summary,
    )
    print(f"rows {len(records)} samples {len(samples)} revision {revision}")
    return 0


def _check_version(arm: str, version: str) -> None:
    if arm == "readcon_release" and version != PINS["readcon_release"]["version"]:
        fail(f"release version {version}")
    if arm == "ase" and version != PINS["ase"]["version"]:
        fail(f"ase version {version}")
    if arm == "eon" and version != PINS["eon_reader"]["commit"]:
        fail(f"eon version {version}")
    if arm.startswith("readcon_tip") or arm.startswith("readcon_positions"):
        if version == PINS["readcon_release"]["version"] or not version:
            fail(f"{arm} loaded version {version}")


def summarize(
    samples: list[dict], machine: str, cores: int
) -> tuple[list[dict], list[dict]]:
    sys.path.insert(0, str(REPO / "paper" / "cpc" / "scripts"))
    import host_from_log

    grouped: dict[tuple, list[dict]] = {}
    for sample in samples:
        key = (sample["arm"], sample["input"])
        grouped.setdefault(key, []).append(sample)
    arm_order = [name for name, _work, _threads in arm_table(cores)]
    input_order = ["synthetic", "cuh2_band"]
    records = []
    keys = sorted(
        grouped,
        key=lambda item: (arm_order.index(item[0]), input_order.index(item[1])),
    )
    for arm, _input_name in keys:
        group = grouped[(arm, _input_name)]
        if len(group) != arms.REPEATS:
            fail(f"{arm} has {len(group)} repeats")
        median, iqr = arms.type7([float(row["seconds"]) for row in group])
        head = group[0]
        records.append(
            {
                "arm": arm,
                "work": head["work"],
                "threads": head["threads"],
                "input": head["input"],
                "input_kind": head["input_kind"],
                "input_sha256": head["input_sha256"],
                "n": str(len(group)),
                "median_s": f"{median:.16g}",
                "iqr_s": f"{iqr:.16g}",
                "n_frames": head["n_frames"],
                "n_atoms": head["n_atoms"],
                "checksum": head["checksum"],
                "revision": head["revision"],
                "machine": machine,
                "nproc": str(cores),
            }
        )
    by_key = {(row["arm"], row["input"]): row for row in records}
    summary = []
    for row in records:
        item = dict(row)
        item["ratio_over_tip"] = ""
        item["aa_ratio"] = ""
        if row["work"] == "full-frame":
            tip = by_key[("readcon_tip_a", row["input"])]
            other_b = by_key[("readcon_tip_b", row["input"])]
            item["ratio_over_tip"] = f"{host_from_log.require_same(row, tip):.16g}"
            item["aa_ratio"] = f"{host_from_log.require_same(other_b, tip):.16g}"
        summary.append(item)
    return records, summary


if __name__ == "__main__":
    raise SystemExit(main())
