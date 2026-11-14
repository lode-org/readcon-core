"""Git-tracked sources must not name a machine scratch path.

Recorded benchmark JSON and raw logs are not source. A line is allowed
only when it lists or rejects one of these prefixes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The prefixes this scanner rejects. Not a destination.
PREFIXES = ("/tmp", "/var/tmp", "/home/", "/agent", "temp_dir()")

ROOTS = ("src/", "tests/", "examples/", "docs/", "scripts/")


def scanned(path: str) -> bool:
    """Source and bench scripts. Recorded JSON and raw logs stay out."""
    if path.startswith("bench/"):
        if path.endswith((".json", ".jsonl", ".log")) or "/raw/" in path:
            return False
        name = path.rsplit("/", 1)[-1]
        return name.endswith(".py") or name == "Snakefile" or name.endswith(".smk")
    return path.startswith(ROOTS)


def allowlist() -> dict[str, list[tuple[str, str]]]:
    """Exact lines, each with the reason it may contain a prefix."""
    system_temp = PREFIXES[0]
    alternate_temp = PREFIXES[1]
    listed = "PREFIXES = (" + ", ".join('"' + item + '"' for item in PREFIXES) + ")"
    return {
        "tests/python/test_no_machine_paths.py": [
            (listed, "lists the prefixes this scanner rejects"),
        ],
        "tests/python/test_bench_disk.py": [
            (
                'value == "' + system_temp + '"',
                "rejects a bench script whose string constant is the system temporary directory",
            ),
            (
                'or value.startswith("' + system_temp + '/")',
                "rejects a bench script constant under the system temporary directory",
            ),
            (
                'or value.startswith("' + alternate_temp + '")',
                "rejects a bench script constant under the alternate temporary directory",
            ),
        ],
    }


def offenders(path: str, lines: list[str]) -> list[str]:
    allowed = {text for text, _reason in allowlist().get(path, [])}
    found = []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped in allowed:
            continue
        if any(prefix in line for prefix in PREFIXES):
            found.append(f"{path}:{number}: {stripped}")
    return found


def tracked_sources() -> list[str]:
    listed = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-z",
            "src",
            "tests",
            "examples",
            "docs",
            "scripts",
            "bench",
        ],
        cwd=ROOT,
    )
    return [
        path.decode() for path in listed.split(b"\0") if path and scanned(path.decode())
    ]


def test_allowlist_matches_the_lines_it_names() -> None:
    for path, entries in allowlist().items():
        present = {
            line.strip()
            for line in (ROOT / path).read_text(encoding="utf-8").splitlines()
        }
        for text, reason in entries:
            assert reason
            assert text in present, text


def test_recorded_bench_records_are_not_scanned() -> None:
    assert not scanned("bench/h2h/scaling/camp17/host.json")
    assert not scanned("bench/h2h/scaling/rel1/cross-format.json")
    assert not scanned("bench/h2h/scaling/rel1/raw/run.log")
    assert scanned("bench/h2h/camp7_ceiling.py")
    assert scanned("bench/h2h/Snakefile")
    assert scanned("src/conbin.rs")
    assert not scanned("benchmarks/weak_scale.py")


def test_a_reintroduced_prefix_is_reported() -> None:
    planted = [
        "let dir = std::env::" + PREFIXES[-1] + ";",
        "let path = " + repr(PREFIXES[0] + "/planted") + ";",
        "fn scratch() -> PathBuf { crate::scratch::root() }",
    ]
    found = offenders("src/planted.rs", planted)
    assert len(found) == 2, found
    assert (
        offenders(
            "tests/python/test_no_machine_paths.py",
            [allowlist()["tests/python/test_no_machine_paths.py"][0][0]],
        )
        == []
    )


def test_tracked_sources_have_no_machine_scratch_paths() -> None:
    found: list[str] = []
    for path in tracked_sources():
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        found.extend(offenders(path, text.splitlines()))
    assert not found, "machine scratch path reintroduced:\n" + "\n".join(found)
