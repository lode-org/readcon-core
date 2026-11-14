"""Git-tracked sources must not name a machine path.

Recorded JSON and raw logs are not source. A line is allowed only when
it lists or rejects one of these prefixes. ``CARGO_MANIFEST_DIR`` is
allowed in test code and doctests. It is not allowed in the library or
the build script, except the build script's own manifest lookup, which
is not compiled into the library.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The path prefixes this scanner rejects. Not a destination.
PATHS = ("/tmp", "/var/tmp", "/home/", "/agent")
MANIFEST = "CARGO_MANIFEST_DIR"
RESULT_TOKENS = (
    "mkstemp",
    "gettempdir",
    "TemporaryDirectory",
    "temp_directory_path",
    "tempfile",
)

ROOTS = (
    "src/",
    "tests/",
    "examples/",
    "docs/",
    "scripts/",
    "fortran/",
    "benchmarks/",
    "benches/",
    "fuzz/",
    "paper/",
    ".github/",
    "cmake/",
    "packaging/",
)
NAMED = {"CMakeLists.txt", "build.rs"}


def scanned(path: str) -> bool:
    """Source, scripts, and build files. Recorded JSON and raw logs stay out."""
    if path.endswith((".json", ".jsonl", ".log")) or "/raw/" in path:
        return False
    if path.startswith("bench/"):
        name = path.rsplit("/", 1)[-1]
        return name.endswith(".py") or name == "Snakefile" or name.endswith(".smk")
    if path in NAMED or path.endswith("/CMakeLists.txt"):
        return True
    return path.startswith(ROOTS)


def _manifest_is_test_code(lines: list[str]) -> list[bool]:
    """Doc comments and ``#[cfg(test)]`` regions are test code."""
    flags = [False] * len(lines)
    depth = 0
    test_at: list[int] = []
    pending = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("///"):
            flags[index] = True
        elif (
            "cfg(test)" in stripped
            or "cfg(all(test" in stripped
            or "cfg(any(test" in stripped
        ):
            pending = True
        opens = line.count("{")
        closes = line.count("}")
        if pending and opens:
            test_at.append(depth + 1)
            pending = False
        if test_at and depth + (1 if opens else 0) >= test_at[-1]:
            flags[index] = True
        depth += opens - closes
        while test_at and depth < test_at[-1]:
            test_at.pop()
    return flags


def allowlist() -> dict[str, list[tuple[str, str]]]:
    """Exact lines, each with the reason it may contain a prefix."""
    system_temp = PATHS[0]
    alternate_temp = PATHS[1]
    home = PATHS[2][:-1]
    agent = PATHS[3]
    listed = "PATHS = (" + ", ".join('"' + item + '"' for item in PATHS) + ")"
    manifest_lookup = (
        "build script reads the manifest directory while it runs; "
        "that value is not compiled into the library"
    )
    redacts = "replaces a machine path in a published log; it is not a destination"
    rejects = "asserts a published log does not contain a machine path"
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
        "benchmarks/weak_scale.py": [
            (
                "Other ``"
                + agent
                + "`` and ``"
                + system_temp
                + "`` tokens become ``$ARTIFACTS``.",
                redacts,
            ),
            (
                'text = text.replace("' + agent + '/repos/readcon-core", ".")',
                redacts,
            ),
            (
                'text = text.replace("' + agent + '", "$ARTIFACTS")',
                redacts,
            ),
            (
                'text = text.replace("' + system_temp + '", "$ARTIFACTS")',
                redacts,
            ),
        ],
        "benchmarks/workflow/test_weak_scale.py": [
            ('self.assertNotIn("' + system_temp + '", text)', rejects),
            ('self.assertNotIn("' + agent + '", text)', rejects),
        ],
        "paper/cpc/scripts/logged_cmd.py": [
            (
                'for token in ("'
                + agent
                + '", "'
                + system_temp
                + '", "'
                + home
                + '", "/cursor", "~/", "_home_")',
                "drops a log line that still contains a machine path",
            ),
        ],
        "paper/cpc/scripts/eon_build_log.py": [
            (
                'for token in ("'
                + agent
                + '", "'
                + system_temp
                + '", "'
                + home
                + '", "/cursor", "~/", "_home_")',
                "drops a log line that still contains a machine path",
            ),
        ],
        "build.rs": [
            (
                'let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());',
                manifest_lookup,
            ),
            (
                'let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();',
                manifest_lookup,
            ),
        ],
    }


def _has_machine_path(line: str) -> bool:
    # The system temporary directory, not a filename that merely contains those letters.
    system_temp = PATHS[0]
    if re.search(
        r"(?<![A-Za-z0-9_])" + re.escape(system_temp) + r"(?![A-Za-z0-9_])",
        line,
    ):
        return True
    if PATHS[1] in line or PATHS[2] in line or PATHS[3] in line:
        return True
    home = PATHS[2][:-1]
    return ('"' + home + '"') in line or ("'" + home + "'") in line


def _result_scope(path: str) -> bool:
    """Benchmarks, paper scripts, and examples must not use the system scratch APIs."""
    if path.startswith(("benchmarks/", "benches/", "paper/", "examples/")):
        return True
    return path.startswith("bench/") and scanned(path)


def offenders(path: str, lines: list[str]) -> list[str]:
    allowed = {text for text, _reason in allowlist().get(path, [])}
    manifest_ok = (
        _manifest_is_test_code(lines)
        if path == "build.rs" or path.startswith("src/")
        else None
    )
    check_manifest = path == "build.rs" or (
        path.startswith("src/") and path.endswith(".rs")
    )
    found = []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped in allowed:
            continue
        if _has_machine_path(line):
            found.append(f"{path}:{number}: {stripped}")
            continue
        if _result_scope(path) and any(token in line for token in RESULT_TOKENS):
            found.append(f"{path}:{number}: {stripped}")
        if (
            check_manifest
            and MANIFEST in line
            and not (manifest_ok and manifest_ok[number - 1])
        ):
            found.append(f"{path}:{number}: {stripped}")
    return found


def tracked_sources() -> list[str]:
    listed = subprocess.check_output(
        ["git", "ls-files", "-z"],
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


def test_recorded_results_are_not_scanned() -> None:
    assert not scanned("bench/h2h/scaling/camp17/host.json")
    assert not scanned("bench/h2h/scaling/rel1/cross-format.json")
    assert not scanned("bench/h2h/scaling/rel1/raw/run.log")
    assert scanned("bench/h2h/camp7_ceiling.py")
    assert scanned("bench/h2h/Snakefile")
    assert scanned("src/conbin.rs")
    assert scanned("benchmarks/weak_scale.py")
    assert scanned("fortran/ReadCon/test/test_add_atom_frame.f90")
    assert scanned("build.rs")
    assert scanned("CMakeLists.txt")
    assert scanned(".github/workflows/ci_cxx.yml")


def test_a_reintroduced_prefix_is_reported() -> None:
    planted = [
        "let path = " + repr(PATHS[0] + "/planted") + ";",
        'let root = env!("' + MANIFEST + '");',
        "fn scratch() {}",
    ]
    found = offenders("src/planted.rs", planted)
    assert len(found) == 2, found
    planted_result = ["handle, path = " + RESULT_TOKENS[0] + "(suffix='.con')"]
    assert offenders("benchmarks/planted.py", planted_result)
    assert offenders("src/planted.rs", planted_result) == []
    doctest = ['/// let root = env!("' + MANIFEST + '");']
    assert offenders("src/planted.rs", doctest) == []
    inside_test = [
        "#[cfg(test)]",
        "mod tests {",
        '    let root = env!("' + MANIFEST + '");',
        "}",
    ]
    assert offenders("src/planted.rs", inside_test) == []
    assert (
        offenders(
            "tests/python/test_no_machine_paths.py",
            [allowlist()["tests/python/test_no_machine_paths.py"][0][0]],
        )
        == []
    )


def test_tracked_sources_have_no_machine_paths() -> None:
    found: list[str] = []
    for path in tracked_sources():
        file = ROOT / path
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        found.extend(offenders(path, text.splitlines()))
    assert not found, "machine path reintroduced:\n" + "\n".join(found)
