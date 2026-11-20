"""Twelve-repeat like-for-like run of synthetic and cuh2_band.

al_eam_md stays at the twelve repeats already in results/r3-*.csv. This
script does not rewrite those files. Ratios use the same require_same
check as the earlier campaigns. A short follow-up times the SVN client
process and its Python parse; those rows are not reader-arm samples.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import time

import arms
import run_bench

BENCH = arms.BENCH
WORK = arms.WORK
PINS = arms.PINS
REPEATS = 12
INPUT_ORDER = ["synthetic", "cuh2_band"]


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
        if row["work"] == "full-frame":
            tip = by_key[("readcon_tip_a", row["input"])]
            other_b = by_key[("readcon_tip_b", row["input"])]
            item["ratio_over_tip"] = f"{host_from_log.require_same(row, tip):.16g}"
            item["aa_ratio"] = f"{host_from_log.require_same(other_b, tip):.16g}"
        summary.append(item)
    return records, summary


def _seconds(samples: list[dict], arm: str, input_name: str) -> list[float]:
    found = [
        float(row["seconds"])
        for row in samples
        if row["arm"] == arm and row["input"] == input_name
    ]
    if len(found) != REPEATS:
        fail(f"{arm} {input_name} has {len(found)} samples for the rank test")
    return found


def load_r3_al() -> list[dict]:
    path = BENCH / "results" / "r3-samples.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["input"] == "al_eam_md" and row["work"] == "full-frame"
        ]
    if not rows:
        fail("r3 samples have no aluminum full-frame rows")
    return rows


def compare_pair(left: list[float], right: list[float]) -> tuple[float, float, float]:
    from scipy.stats import mannwhitneyu

    ratio = arms.type7(left)[0] / arms.type7(right)[0]
    result = mannwhitneyu(left, right, alternative="two-sided", method="auto")
    return ratio, float(result.statistic), float(result.pvalue)


def comparisons(samples: list[dict]) -> list[dict]:
    groups = [
        (
            "synthetic",
            _seconds(samples, "readcon_tip_b", "synthetic"),
            _seconds(samples, "readcon_tip_a", "synthetic"),
            _seconds(samples, "readcon_release", "synthetic"),
            "r4",
        ),
        (
            "cuh2_band",
            _seconds(samples, "readcon_tip_b", "cuh2_band"),
            _seconds(samples, "readcon_tip_a", "cuh2_band"),
            _seconds(samples, "readcon_release", "cuh2_band"),
            "r4",
        ),
    ]
    al = load_r3_al()
    groups.append(
        (
            "al_eam_md",
            [float(row["seconds"]) for row in al if row["arm"] == "readcon_tip_b"],
            [float(row["seconds"]) for row in al if row["arm"] == "readcon_tip_a"],
            [float(row["seconds"]) for row in al if row["arm"] == "readcon_release"],
            "r3",
        )
    )
    rows = []
    for input_name, tip_b, tip_a, release, source in groups:
        if not (len(tip_a) == len(tip_b) == len(release) == REPEATS):
            fail(f"{input_name} rank test has unequal repeat counts")
        aa_ratio, aa_u, aa_p = compare_pair(tip_b, tip_a)
        rel_ratio, rel_u, rel_p = compare_pair(release, tip_a)
        med_a = arms.type7(tip_a)[0]
        med_b = arms.type7(tip_b)[0]
        med_r = arms.type7(release)[0]
        low, high = min(med_a, med_b), max(med_a, med_b)
        outside = med_r < low or med_r > high
        rows.append(
            {
                "input": input_name,
                "source": source,
                "comparison": "tip_b_over_tip_a",
                "n": str(REPEATS),
                "median_left_s": f"{med_b:.16g}",
                "median_right_s": f"{med_a:.16g}",
                "ratio": f"{aa_ratio:.16g}",
                "mannwhitney_u": f"{aa_u:.16g}",
                "mannwhitney_p": f"{aa_p:.16g}",
                "aa_band_low_s": f"{low:.16g}",
                "aa_band_high_s": f"{high:.16g}",
                "release_outside_aa_band": "",
            }
        )
        rows.append(
            {
                "input": input_name,
                "source": source,
                "comparison": "release_over_tip_a",
                "n": str(REPEATS),
                "median_left_s": f"{med_r:.16g}",
                "median_right_s": f"{med_a:.16g}",
                "ratio": f"{rel_ratio:.16g}",
                "mannwhitney_u": f"{rel_u:.16g}",
                "mannwhitney_p": f"{rel_p:.16g}",
                "aa_band_low_s": f"{low:.16g}",
                "aa_band_high_s": f"{high:.16g}",
                "release_outside_aa_band": "yes" if outside else "no",
            }
        )
    return rows


def _thread_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(run_bench.BLAS)
    env["RAYON_NUM_THREADS"] = "1"
    return env


def overhead(inputs: dict[str, dict], log) -> list[dict]:
    """Time the SVN binary and the Python rebuild on cpu 0.

    The reader-arm clock starts after the worker import and includes this
    binary. These repeats are not part of that sample list.
    """
    binary = arms.ensure_eon_svn()
    env = _thread_env()
    previous = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {0})
    try:
        return _overhead_pinned(binary, env, inputs, log)
    finally:
        os.sched_setaffinity(0, previous)


def _overhead_pinned(binary, env, inputs, log) -> list[dict]:
    blobs = {}
    for name in INPUT_ORDER:
        completed = subprocess.run(
            [str(binary), inputs[name]["path"]],
            capture_output=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            fail(f"svn capture {name} exited {completed.returncode}")
        blobs[name] = completed.stdout

    def time_start() -> float:
        started = time.perf_counter()
        completed = subprocess.run(
            [str(binary)], capture_output=True, env=env, check=False
        )
        seconds = time.perf_counter() - started
        if completed.returncode != 2:
            fail(f"svn usage exit {completed.returncode}")
        return seconds

    def time_binary(name: str) -> float:
        started = time.perf_counter()
        completed = subprocess.run(
            [str(binary), inputs[name]["path"]],
            capture_output=True,
            env=env,
            check=False,
        )
        seconds = time.perf_counter() - started
        if completed.returncode != 0:
            fail(f"svn binary {name} exited {completed.returncode}")
        return seconds

    def time_parse(name: str) -> float:
        started = time.perf_counter()
        arms._parse_eon_svn(blobs[name])
        return time.perf_counter() - started

    def time_ensure() -> float:
        started = time.perf_counter()
        arms.ensure_eon_svn()
        return time.perf_counter() - started

    def time_full(name: str) -> float:
        started = time.perf_counter()
        arms._full_eon_svn(inputs[name]["path"])
        return time.perf_counter() - started

    units = [
        ("process_start", "", time_start),
        ("ensure_pin", "", time_ensure),
        ("binary", "cuh2_band", lambda: time_binary("cuh2_band")),
        ("binary", "synthetic", lambda: time_binary("synthetic")),
        ("python_parse", "cuh2_band", lambda: time_parse("cuh2_band")),
        ("python_parse", "synthetic", lambda: time_parse("synthetic")),
        ("full_call", "cuh2_band", lambda: time_full("cuh2_band")),
        ("full_call", "synthetic", lambda: time_full("synthetic")),
    ]
    taken: dict[tuple[str, str], list[float]] = {}
    for rep in range(REPEATS):
        for kind, input_name, action in arms.abba_order(units, rep):
            seconds = action()
            taken.setdefault((kind, input_name), []).append(seconds)
            run_bench.append_log(
                log,
                "overhead "
                f"rep={rep} kind={kind} input={input_name or '-'} "
                f"seconds={seconds:.16g}",
            )
    rows = []
    for kind, input_name, _action in units:
        values = taken[(kind, input_name)]
        if len(values) != REPEATS:
            fail(f"overhead {kind} {input_name} has {len(values)} repeats")
        median, iqr = arms.type7(values)
        rows.append(
            {
                "kind": kind,
                "input": input_name,
                "n": str(REPEATS),
                "median_s": f"{median:.16g}",
                "iqr_s": f"{iqr:.16g}",
            }
        )
    return rows


def main() -> int:
    if REPEATS < 12:
        fail(f"repeats {REPEATS}")
    arms.assert_schedule()
    revision = run_bench.require_clean()
    machine = arms.machine_hash()
    cores = arms.nproc()
    WORK.mkdir(parents=True, exist_ok=True)
    inputs = arms.ensure_inputs()
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
    log_path = WORK / "campaign-r4.log"
    samples: list[dict] = []
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        run_bench.append_log(log, f"revision {revision}")
        run_bench.append_log(log, f"machine {machine}")
        run_bench.append_log(log, f"nproc {cores}")
        run_bench.append_log(log, f"repeats synthetic={REPEATS} cuh2_band={REPEATS}")
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
        for rep in range(REPEATS):
            for arm, work, threads, spec in arms.abba_order(units, rep):
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
        overhead_rows = overhead(inputs, log)
    records, summary = summarize(samples, machine, cores)
    compared = comparisons(samples)
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
    run_bench.write_csv(out / "r4-rows.csv", fields, records)
    run_bench.write_csv(out / "r4-samples.csv", list(samples[0].keys()), samples)
    run_bench.write_csv(
        out / "r4-summary.csv",
        fields + ["ratio_over_tip", "aa_ratio"],
        summary,
    )
    run_bench.write_csv(
        out / "r4-overhead.csv",
        ["kind", "input", "n", "median_s", "iqr_s"],
        overhead_rows,
    )
    run_bench.write_csv(
        out / "r4-compare.csv",
        [
            "input",
            "source",
            "comparison",
            "n",
            "median_left_s",
            "median_right_s",
            "ratio",
            "mannwhitney_u",
            "mannwhitney_p",
            "aa_band_low_s",
            "aa_band_high_s",
            "release_outside_aa_band",
        ],
        compared,
    )
    print(f"rows {len(records)} samples {len(samples)} revision {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
