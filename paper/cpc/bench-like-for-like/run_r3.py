"""Like-for-like campaign that writes results/r3-*.csv and leaves earlier rows untouched.

synthetic and cuh2_band use six repeats. al_eam_md uses twelve. Repeats share
one ABBA schedule: the first six cover every arm and input, and the next six
continue the aluminum input only.
"""

from __future__ import annotations

import csv
import subprocess
import sys

import arms
import run_bench

BENCH = arms.BENCH
WORK = arms.WORK
PINS = arms.PINS
SHORT_REPEATS = int(PINS["protocol"]["repeats"])
AL_REPEATS = int(PINS["simulation_protocol"]["repeats"])
INPUT_ORDER = ["synthetic", "cuh2_band", "al_eam_md"]


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def arm_table(cores: int) -> list[tuple[str, str, int]]:
    return [
        ("readcon_tip_a", "full-frame", 1),
        ("readcon_tip_b", "full-frame", 1),
        ("readcon_release", "full-frame", 1),
        ("ase", "full-frame", 1),
        ("eon_svn_cxx", "full-frame", 1),
        ("eon_legacy_python", "full-frame", 1),
        ("readcon_positions_1", "coords-only", 1),
        ("readcon_positions_all", "coords-only", cores),
    ]


def regenerate_simulation() -> dict[str, str]:
    pin = PINS["simulation"]
    completed = subprocess.run(
        [sys.executable, str(BENCH / "make_al_md.py")],
        cwd=BENCH,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        fail((completed.stderr or completed.stdout)[-500:])
    path = BENCH / pin["path"]
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


def wheel_sha(directory):
    wheels = sorted(directory.glob("readcon-*.whl"))
    if len(wheels) != 1:
        fail(f"{directory.name} has {len(wheels)} wheels")
    return wheels[0], arms.file_sha256(wheels[0])


def summarize(
    samples: list[dict], machine: str, cores: int
) -> tuple[list[dict], list[dict]]:
    sys.path.insert(0, str(arms.REPO / "paper" / "cpc" / "scripts"))
    import host_from_log

    grouped: dict[tuple, list[dict]] = {}
    for sample in samples:
        grouped.setdefault((sample["arm"], sample["input"]), []).append(sample)
    order = [name for name, _work, _threads in arm_table(cores)]
    records = []
    keys = sorted(
        grouped,
        key=lambda item: (order.index(item[0]), INPUT_ORDER.index(item[1])),
    )
    for arm, input_name in keys:
        group = grouped[(arm, input_name)]
        wanted = AL_REPEATS if input_name == "al_eam_md" else SHORT_REPEATS
        if len(group) != wanted:
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
        item["historical_unequal_ratio"] = ""
        if row["work"] == "full-frame":
            tip = by_key[("readcon_tip_a", row["input"])]
            other_b = by_key[("readcon_tip_b", row["input"])]
            ratio = host_from_log.require_same(row, tip)
            if row["arm"] == "eon_svn_cxx" and row["input"] == "cuh2_band":
                item["historical_unequal_ratio"] = f"{ratio:.16g}"
            else:
                item["ratio_over_tip"] = f"{ratio:.16g}"
            item["aa_ratio"] = f"{host_from_log.require_same(other_b, tip):.16g}"
        summary.append(item)
    return records, summary


def write_summaries(samples: list[dict], machine: str, cores: int) -> None:
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
    out = BENCH / "results"
    run_bench.write_csv(out / "r3-rows.csv", fields, records)
    run_bench.write_csv(
        out / "r3-summary.csv",
        fields + ["ratio_over_tip", "aa_ratio", "historical_unequal_ratio"],
        summary,
    )


def regenerate_summaries() -> int:
    path = BENCH / "results" / "r3-samples.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        samples = list(csv.DictReader(stream))
    if not samples:
        fail(f"{path} has no samples")
    machines = {row["machine"] for row in samples}
    cores = {row["nproc"] for row in samples}
    if len(machines) != 1 or len(cores) != 1:
        fail("r3 samples contain inconsistent machine metadata")
    write_summaries(samples, machines.pop(), int(cores.pop()))
    return 0


def main() -> int:
    if sys.argv[1:] == ["--summarize-existing"]:
        return regenerate_summaries()
    if sys.argv[1:]:
        fail("usage: run_r3.py [--summarize-existing]")
    if SHORT_REPEATS != 6 or AL_REPEATS != 12:
        fail(f"repeat pins {SHORT_REPEATS} {AL_REPEATS}")
    arms.assert_schedule()
    revision = run_bench.require_clean()
    machine = arms.machine_hash()
    cores = arms.nproc()
    WORK.mkdir(parents=True, exist_ok=True)
    inputs = arms.ensure_inputs()
    inputs["al_eam_md"] = regenerate_simulation()
    builds = PINS["tip_builds"]
    tip_a_wheel, tip_a_hash = wheel_sha(WORK / "wheels-tip-a")
    tip_b_wheel, tip_b_hash = wheel_sha(WORK / "wheels-tip-b")
    if tip_a_hash != builds["tip_a_sha256"] or tip_b_hash != builds["tip_b_sha256"]:
        fail("tip wheel hash does not match the pinned builds")
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
    run_bench.install_wheel(tip_a_wheel, prefix["readcon_tip_a"])
    run_bench.install_wheel(tip_b_wheel, prefix["readcon_tip_b"])
    run_bench.install_wheel(release_wheel, prefix["readcon_release"])
    prefixes = {name: str(path) for name, path in prefix.items()}
    tip_version = run_bench.installed_version(prefix["readcon_tip_a"])
    if run_bench.installed_version(prefix["readcon_tip_b"]) != tip_version:
        fail("tip builds report different versions")
    eon_root = str(arms.fetch_eon(WORK / "eon-src"))
    arms.ensure_eon_svn()
    labels = {
        "readcon_tip_a": f"{tip_version} {revision} tip-a {tip_a_hash}",
        "readcon_tip_b": f"{tip_version} {revision} tip-b {tip_b_hash}",
        "readcon_release": release_pin["version"],
        "ase": PINS["ase"]["version"],
        "eon_svn_cxx": str(PINS["eon_svn_cxx"]["revision"]),
        "eon_legacy_python": PINS["eon_reader"]["commit"],
        "readcon_positions_1": f"{tip_version} {revision} tip-a {tip_a_hash}",
        "readcon_positions_all": f"{tip_version} {revision} tip-a {tip_a_hash}",
    }
    table = arm_table(cores)
    units = [
        (arm, work, threads, spec)
        for arm, work, threads in table
        for spec in (inputs[name] for name in INPUT_ORDER)
    ]
    al_units = [item for item in units if item[3]["name"] == "al_eam_md"]
    log_path = WORK / "campaign-r3.log"
    samples: list[dict] = []
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        run_bench.append_log(log, f"revision {revision}")
        run_bench.append_log(log, f"machine {machine}")
        run_bench.append_log(log, f"nproc {cores}")
        run_bench.append_log(
            log,
            f"repeats synthetic={SHORT_REPEATS} cuh2_band={SHORT_REPEATS} al_eam_md={AL_REPEATS}",
        )
        run_bench.append_log(log, "schedule ABBA-rotated")
        run_bench.append_log(log, "warmup_discard no")
        run_bench.append_log(log, "blas_threads 1")
        run_bench.append_log(log, "taskset full-frame and coords-1 on cpu 0")
        for name in INPUT_ORDER:
            spec = inputs[name]
            run_bench.append_log(
                log,
                f"input name={name} kind={spec['kind']} sha256={spec['sha256']}",
            )
        expected: dict[str, tuple[int, int, str]] = {}
        for arm, work, threads, spec in units:
            doc = run_bench.one(arm, spec["path"], threads, prefixes, eon_root)
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
        for rep in range(AL_REPEATS):
            batch = units if rep < SHORT_REPEATS else al_units
            for arm, work, threads, spec in arms.abba_order(batch, rep):
                doc = run_bench.one(arm, spec["path"], threads, prefixes, eon_root)
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
    write_summaries(samples, machine, cores)
    out = BENCH / "results"
    run_bench.write_csv(out / "r3-samples.csv", list(samples[0].keys()), samples)
    records, _summary = summarize(samples, machine, cores)
    print(f"rows {len(records)} samples {len(samples)} revision {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
