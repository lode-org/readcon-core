"""Twelve-repeat like-for-like timing of the aluminum trajectory only.

Earlier synthetic and cuh2_band rows are appended to, not rewritten.
"""

from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path

import arms
import run_bench

BENCH = arms.BENCH
WORK = arms.WORK
PINS = arms.PINS
REPEATS = int(PINS["simulation_protocol"]["repeats"])


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def wheel_sha(directory: Path) -> str:
    wheels = sorted(directory.glob("readcon-*.whl"))
    if len(wheels) != 1:
        fail(f"{directory} has {len(wheels)} wheels")
    return arms.file_sha256(wheels[0])


def extend_csv(path: Path, rows: list[dict]) -> None:
    original = path.read_bytes()
    if not original.endswith(b"\n"):
        fail(f"{path.name} has no trailing newline")
    header = original.splitlines()[0].decode("utf-8")
    fields = header.split(",")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=fields, lineterminator="\n", extrasaction="ignore"
    )
    for row in rows:
        writer.writerow(row)
    extra = buffer.getvalue().encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(original)
        handle.write(extra)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    written = path.read_bytes()
    if not written.startswith(original):
        fail(f"{path.name} prefix changed")


def simulation_input() -> dict[str, str]:
    spec = PINS["simulation"]
    path = BENCH / spec["path"]
    if not path.is_file():
        fail(f"missing {spec['path']}; run make_al_md.py")
    digest = arms.file_sha256(path)
    if digest != spec["sha256"]:
        fail(f"simulation hash {digest} != pin {spec['sha256']}")
    if path.stat().st_size != int(spec["bytes"]):
        fail("simulation byte size does not match the pin")
    return {
        "name": spec["name"],
        "kind": spec["kind"],
        "sha256": digest,
        "path": str(path),
    }


def summarize_new(samples: list[dict]) -> tuple[list[dict], list[dict]]:
    sys.path.insert(0, str(arms.REPO / "paper" / "cpc" / "scripts"))
    import host_from_log

    grouped: dict[str, list[dict]] = {}
    for sample in samples:
        grouped.setdefault(sample["arm"], []).append(sample)
    order = [name for name, _work, _threads in run_bench.arm_table(1)]
    records = []
    for arm in order:
        group = grouped.get(arm, [])
        if len(group) != REPEATS:
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
                "machine": head["machine"],
                "nproc": head["nproc"],
            }
        )
    by_arm = {row["arm"]: row for row in records}
    summary = []
    for row in records:
        item = dict(row)
        item["ratio_over_tip"] = ""
        item["aa_ratio"] = ""
        if row["work"] == "full-frame":
            tip = by_arm["readcon_tip_a"]
            other_b = by_arm["readcon_tip_b"]
            item["ratio_over_tip"] = f"{host_from_log.require_same(row, tip):.16g}"
            item["aa_ratio"] = f"{host_from_log.require_same(other_b, tip):.16g}"
        summary.append(item)
    return records, summary


def main() -> int:
    if REPEATS != 12:
        fail(f"simulation repeats {REPEATS}")
    arms.assert_schedule()
    revision = run_bench.require_clean()
    machine = arms.machine_hash()
    cores = arms.nproc()
    spec = simulation_input()
    if int(PINS["simulation"]["n_frames"]) < 1000:
        fail("simulation frame pin is below 1000")
    if int(PINS["simulation"]["n_atoms"]) < 100:
        fail("simulation atom pin is below 100")
    builds = PINS["tip_builds"]
    tip_a = WORK / "wheels-tip-a"
    tip_b = WORK / "wheels-tip-b"
    tip_a_hash = wheel_sha(tip_a)
    tip_b_hash = wheel_sha(tip_b)
    if tip_a_hash != builds["tip_a_sha256"] or tip_b_hash != builds["tip_b_sha256"]:
        fail("tip wheel hash does not match the first campaign")
    release_pin = PINS["readcon_release"]
    release_wheel = WORK / "wheels-release" / release_pin["wheel"]
    run_bench.download(release_pin["url"], release_wheel, release_pin["sha256"])
    prefix = {
        "readcon_tip_a": WORK / "prefix-tip-a",
        "readcon_tip_b": WORK / "prefix-tip-b",
        "readcon_release": WORK / "prefix-release",
        "readcon_positions_1": WORK / "prefix-tip-a",
        "readcon_positions_all": WORK / "prefix-tip-a",
    }
    run_bench.install_wheel(next(tip_a.glob("readcon-*.whl")), prefix["readcon_tip_a"])
    run_bench.install_wheel(next(tip_b.glob("readcon-*.whl")), prefix["readcon_tip_b"])
    run_bench.install_wheel(release_wheel, prefix["readcon_release"])
    prefixes = {name: str(path) for name, path in prefix.items()}
    eon_root = str(arms.fetch_eon(WORK / "eon-src"))
    tip_version = run_bench.installed_version(prefix["readcon_tip_a"])
    if run_bench.installed_version(prefix["readcon_tip_b"]) != tip_version:
        fail("tip builds report different versions")
    labels = {
        "readcon_tip_a": f"{tip_version} {revision} tip-a {tip_a_hash}",
        "readcon_tip_b": f"{tip_version} {revision} tip-b {tip_b_hash}",
        "readcon_release": release_pin["version"],
        "ase": PINS["ase"]["version"],
        "eon": PINS["eon_reader"]["commit"],
        "readcon_positions_1": f"{tip_version} {revision} tip-a {tip_a_hash}",
        "readcon_positions_all": f"{tip_version} {revision} tip-a {tip_a_hash}",
    }
    units = [
        (arm, work, threads, spec) for arm, work, threads in run_bench.arm_table(cores)
    ]
    samples: list[dict] = []
    log_path = WORK / "campaign-al.log"
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        run_bench.append_log(log, f"revision {revision}")
        run_bench.append_log(log, f"machine {machine}")
        run_bench.append_log(log, f"nproc {cores}")
        run_bench.append_log(log, f"repeats {REPEATS}")
        run_bench.append_log(log, "schedule ABBA-rotated")
        run_bench.append_log(log, "warmup_discard no")
        run_bench.append_log(log, "blas_threads 1")
        run_bench.append_log(log, "taskset full-frame and coords-1 on cpu 0")
        run_bench.append_log(
            log,
            f"input name={spec['name']} kind={spec['kind']} sha256={spec['sha256']}",
        )
        expected = None
        for arm, work, threads, item in units:
            doc = run_bench.one(arm, item["path"], threads, prefixes, eon_root)
            run_bench.append_log(
                log,
                "equal-work "
                f"arm={arm} work={work} threads={threads} input={item['name']} "
                f"seconds={doc.get('seconds')} frames={doc.get('n_frames')} "
                f"atoms={doc.get('n_atoms')} checksum={doc.get('checksum')} "
                f"version={doc.get('version')} error={doc.get('error', '')}",
            )
            if doc.get("error") or doc.get("seconds") is None:
                fail(f"equal-work failed for {arm}: {doc.get('error')}")
            run_bench._check_version(arm, doc["version"])
            found = (int(doc["n_frames"]), int(doc["n_atoms"]), doc["checksum"])
            if found[0] != int(PINS["simulation"]["n_frames"]) or found[1] != int(
                PINS["simulation"]["n_atoms"]
            ):
                fail(f"equal-work shape {found} != pin")
            if expected is None:
                expected = found
            elif found != expected:
                fail(f"equal-work mismatch {arm} {found} != {expected}")
        for rep in range(REPEATS):
            for arm, work, threads, item in arms.abba_order(units, rep):
                doc = run_bench.one(arm, item["path"], threads, prefixes, eon_root)
                run_bench.append_log(
                    log,
                    "sample "
                    f"rep={rep} arm={arm} work={work} threads={threads} "
                    f"input={item['name']} seconds={doc.get('seconds')} "
                    f"frames={doc.get('n_frames')} atoms={doc.get('n_atoms')} "
                    f"checksum={doc.get('checksum')} version={doc.get('version')} "
                    f"error={doc.get('error', '')}",
                )
                if doc.get("error") or doc.get("seconds") is None:
                    fail(f"sample failed for {arm} rep {rep}: {doc.get('error')}")
                run_bench._check_version(arm, doc["version"])
                found = (int(doc["n_frames"]), int(doc["n_atoms"]), doc["checksum"])
                if found != expected:
                    fail(f"sample mismatch {arm} rep {rep} {found} != {expected}")
                samples.append(
                    {
                        "arm": arm,
                        "work": work,
                        "threads": str(threads),
                        "input": item["name"],
                        "input_kind": item["kind"],
                        "input_sha256": item["sha256"],
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
    records, summary = summarize_new(samples)
    extend_csv(BENCH / "results" / "rows.csv", records)
    extend_csv(BENCH / "results" / "samples.csv", samples)
    extend_csv(BENCH / "results" / "summary.csv", summary)
    print(f"added rows {len(records)} samples {len(samples)} revision {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
