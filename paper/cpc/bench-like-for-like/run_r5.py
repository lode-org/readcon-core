"""Twelve-repeat tip and SVN run after the pin check left the clock.

readcon_tip_a, readcon_tip_b, the SVN end-to-end read, and the SVN
binary alone, on synthetic, cuh2_band, and al_eam_md. The source-hash
pin runs once before any timed repeat. Earlier result files stay put.
"""

from __future__ import annotations

import sys
import time

import arms
import run_bench

BENCH = arms.BENCH
WORK = arms.WORK
PINS = arms.PINS
REPEATS = 12
INPUT_ORDER = ["synthetic", "cuh2_band", "al_eam_md"]


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def arm_table() -> list[tuple[str, str, int]]:
    return [
        ("readcon_tip_a", "full-frame", 1),
        ("readcon_tip_b", "full-frame", 1),
        ("eon_svn_cxx", "full-frame", 1),
        ("eon_svn_binary", "binary", 1),
    ]


def wheel_sha(directory):
    wheels = sorted(directory.glob("readcon-*.whl"))
    if len(wheels) != 1:
        fail(f"{directory.name} has {len(wheels)} wheels")
    return wheels[0], arms.file_sha256(wheels[0])


def simulation_input() -> dict[str, str]:
    pin = PINS["simulation"]
    path = BENCH / pin["path"]
    if not path.is_file():
        fail(f"missing {pin['path']}")
    digest = arms.file_sha256(path)
    if digest != pin["sha256"]:
        fail(f"al_eam_md sha256 {digest} != {pin['sha256']}")
    if path.stat().st_size != int(pin["bytes"]):
        fail(f"al_eam_md bytes {path.stat().st_size} != {pin['bytes']}")
    return {
        "name": pin["name"],
        "kind": pin["kind"],
        "sha256": digest,
        "path": str(path),
    }


def session_pin() -> dict[str, str]:
    started = time.perf_counter()
    binary = arms.ensure_eon_svn()
    seconds = time.perf_counter() - started
    pin = PINS["eon_svn_cxx"]
    driver = arms.file_sha256(BENCH / "eon_svn_driver.cpp")
    return {
        "check": "svn_pin",
        "result": "ok",
        "seconds": f"{seconds:.16g}",
        "n_files": str(len(pin["files"])),
        "eigen_tree_sha256": pin["eigen_tree_sha256"],
        "driver_sha256": driver,
        "revision": str(pin["revision"]),
        "binary": binary.name,
    }


def summarize(
    samples: list[dict], machine: str, cores: int
) -> tuple[list[dict], list[dict]]:
    sys.path.insert(0, str(arms.REPO / "paper" / "cpc" / "scripts"))
    import host_from_log

    grouped: dict[tuple, list[dict]] = {}
    for sample in samples:
        grouped.setdefault((sample["arm"], sample["input"]), []).append(sample)
    order = [name for name, _work, _threads in arm_table()]
    records = []
    keys = sorted(
        grouped,
        key=lambda item: (order.index(item[0]), INPUT_ORDER.index(item[1])),
    )
    for arm, input_name in keys:
        group = grouped[(arm, input_name)]
        if len(group) != REPEATS:
            fail(f"{arm} {input_name} has {len(group)} repeats")
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
        tip = by_key[("readcon_tip_a", row["input"])]
        other_b = by_key[("readcon_tip_b", row["input"])]
        item["aa_ratio"] = f"{host_from_log.require_same(other_b, tip):.16g}"
        if row["work"] == "full-frame":
            item["ratio_over_tip"] = f"{host_from_log.require_same(row, tip):.16g}"
        summary.append(item)
    return records, summary


def main() -> int:
    if REPEATS < 12:
        fail(f"repeats {REPEATS}")
    arms.assert_schedule()
    revision = run_bench.require_clean()
    machine = arms.machine_hash()
    cores = arms.nproc()
    WORK.mkdir(parents=True, exist_ok=True)
    pin_row = session_pin()
    inputs = arms.ensure_inputs()
    inputs["al_eam_md"] = simulation_input()
    builds = PINS["tip_builds"]
    tip_a_wheel, tip_a_hash = wheel_sha(WORK / "wheels-tip-a")
    tip_b_wheel, tip_b_hash = wheel_sha(WORK / "wheels-tip-b")
    if tip_a_hash != builds["tip_a_sha256"] or tip_b_hash != builds["tip_b_sha256"]:
        fail("tip wheel hash does not match the pinned builds")
    prefix = {
        "readcon_tip_a": WORK / "prefix-tip-a",
        "readcon_tip_b": WORK / "prefix-tip-b",
    }
    run_bench.install_wheel(tip_a_wheel, prefix["readcon_tip_a"])
    run_bench.install_wheel(tip_b_wheel, prefix["readcon_tip_b"])
    prefixes = {name: str(path) for name, path in prefix.items()}
    tip_version = run_bench.installed_version(prefix["readcon_tip_a"])
    if run_bench.installed_version(prefix["readcon_tip_b"]) != tip_version:
        fail("tip builds report different versions")
    labels = {
        "readcon_tip_a": f"{tip_version} {revision} tip-a {tip_a_hash}",
        "readcon_tip_b": f"{tip_version} {revision} tip-b {tip_b_hash}",
        "eon_svn_cxx": str(PINS["eon_svn_cxx"]["revision"]),
        "eon_svn_binary": str(PINS["eon_svn_cxx"]["revision"]),
    }
    table = arm_table()
    units = [
        (arm, work, threads, spec)
        for arm, work, threads in table
        for spec in (inputs[name] for name in INPUT_ORDER)
    ]
    log_path = WORK / "campaign-r5.log"
    samples: list[dict] = []
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        run_bench.append_log(
            log,
            "session " + " ".join(f"{key}={value}" for key, value in pin_row.items()),
        )
        run_bench.append_log(log, f"revision {revision}")
        run_bench.append_log(log, f"machine {machine}")
        run_bench.append_log(log, f"nproc {cores}")
        run_bench.append_log(log, f"repeats {REPEATS}")
        run_bench.append_log(log, "schedule ABBA-rotated")
        run_bench.append_log(log, "warmup_discard no")
        run_bench.append_log(log, "blas_threads 1")
        run_bench.append_log(log, "taskset single-thread arms on cpu 0")
        for name in INPUT_ORDER:
            spec = inputs[name]
            run_bench.append_log(
                log,
                f"input name={name} kind={spec['kind']} sha256={spec['sha256']}",
            )
        expected: dict[str, tuple[int, int, str]] = {}
        for arm, work, threads, spec in units:
            doc = run_bench.one(arm, spec["path"], threads, prefixes, "")
            run_bench.append_log(
                log,
                "equal-work "
                f"arm={arm} work={work} threads={threads} input={spec['name']} "
                f"seconds={doc.get('seconds')} frames={doc.get('n_frames')} "
                f"atoms={doc.get('n_atoms')} checksum={doc.get('checksum')} "
                f"version={doc.get('version')} error={doc.get('error', '')}",
            )
            if doc.get("error") or doc.get("seconds") is None:
                fail(f"equal-work failed for {arm} {spec['name']}: {doc.get('error')}")
            run_bench._check_version(arm, doc["version"])
            found = (int(doc["n_frames"]), int(doc["n_atoms"]), doc["checksum"])
            if spec["name"] not in expected:
                expected[spec["name"]] = found
            elif found != expected[spec["name"]]:
                fail(
                    f"equal-work mismatch {arm} {spec['name']} {found} != {expected[spec['name']]}"
                )
        for rep in range(REPEATS):
            for arm, work, threads, spec in arms.abba_order(units, rep):
                doc = run_bench.one(arm, spec["path"], threads, prefixes, "")
                run_bench.append_log(
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
                run_bench._check_version(arm, doc["version"])
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
    pin_row["machine"] = machine
    pin_row["nproc"] = str(cores)
    pin_row["git_revision"] = revision
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
    out = BENCH / "results"
    run_bench.write_csv(out / "r5-rows.csv", fields, records)
    run_bench.write_csv(out / "r5-samples.csv", list(samples[0].keys()), samples)
    run_bench.write_csv(
        out / "r5-summary.csv",
        fields + ["ratio_over_tip", "aa_ratio"],
        summary,
    )
    run_bench.write_csv(
        out / "r5-session.csv",
        [
            "check",
            "result",
            "seconds",
            "n_files",
            "eigen_tree_sha256",
            "driver_sha256",
            "revision",
            "binary",
            "machine",
            "nproc",
            "git_revision",
        ],
        [pin_row],
    )
    print(f"rows {len(records)} samples {len(samples)} revision {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
