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
# Commands that reach the system scratch directory. The Rust call is built
# below so this file does not contain it. The others are shell and CMake.
BUILD_TOKENS = ("mktemp", "GetTempPath", "get_tempdir")
PYTHON_SCRATCH = ("mkdtemp", "gettempdir", "TemporaryDirectory")
CMAKE_ENV = ("$ENV{TEMP}", "$ENV{TMP}")
TEMP_DIR_CALL = "temp_" + "dir("
TMPDIR_READ = re.compile(r"(?<![A-Za-z0-9_])TMPDIR(?![A-Za-z0-9_])")

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


# Saved records that already name a machine path. Exact paths only.
# New records are scanned and must stay clean.
SAVED_MACHINE_RECORDS = frozenset(
    {
        "bench/h2h/logs/mem-r1/massif.out",
        "bench/h2h/logs/mem-r1/time-v.log",
        "bench/h2h/reader-exchange/perf21/reader-exchange.json",
        "bench/h2h/reader-exchange/perf21/reader-exchange.log",
        "bench/h2h/results/serial-c-walker.log",
        "bench/h2h/results/serial-column.log",
        "bench/h2h/scaling/camp12/cachegrind.txt",
        "bench/h2h/scaling/camp12/logs/camp12.log",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-con-write-1.json",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-con-write-2.json",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-con-write-4.json",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-con-write-8.json",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-convel-write-1.json",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-convel-write-2.json",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-convel-write-4.json",
        "bench/h2h/scaling/camp12/weak-ext4-ranks-convel-write-8.json",
        "bench/h2h/scaling/camp16b/host.json",
        "bench/h2h/scaling/camp16b/reconcile.json",
        "bench/h2h/scaling/camp17/host.json",
        "bench/h2h/scaling/camp18/host.json",
        "bench/h2h/scaling/camp19/host.json",
        "bench/h2h/scaling/camp20/host.json",
        "bench/h2h/scaling/camp21/host.json",
        "bench/h2h/scaling/camp21/weak-mpi-write-1-disk.json",
        "bench/h2h/scaling/camp21/weak-mpi-write-2-disk.json",
        "bench/h2h/scaling/camp21/weak-mpi-write-4-disk.json",
        "bench/h2h/scaling/camp21/weak-mpi-write-8-disk.json",
        "bench/h2h/scaling/camp22/host.json",
        "bench/h2h/scaling/camp22/weak-mpi-write-1-disk.json",
        "bench/h2h/scaling/camp22/weak-mpi-write-2-disk.json",
        "bench/h2h/scaling/camp22/weak-mpi-write-4-disk.json",
        "bench/h2h/scaling/camp22/weak-mpi-write-8-disk.json",
        "bench/h2h/scaling/camp23/host.json",
        "bench/h2h/scaling/camp23/weak-mpi-write-1-disk.json",
        "bench/h2h/scaling/camp23/weak-mpi-write-2-disk.json",
        "bench/h2h/scaling/camp23/weak-mpi-write-4-disk.json",
        "bench/h2h/scaling/camp23/weak-mpi-write-8-disk.json",
        "bench/h2h/scaling/h2h10/chemfiles-write-profile.txt",
        "bench/h2h/scaling/h2h10/cross-format.json",
        "bench/h2h/scaling/h2h10/cross-format.log",
        "bench/h2h/scaling/h2h11/chemfiles-write-profile.txt",
        "bench/h2h/scaling/h2h11/cross-format.json",
        "bench/h2h/scaling/h2h11/cross-format.log",
        "bench/h2h/scaling/h2h12/chemfiles-write-profile.txt",
        "bench/h2h/scaling/h2h12/cross-format.json",
        "bench/h2h/scaling/h2h12/cross-format.log",
        "bench/h2h/scaling/h2h13/chemfiles-write-profile.txt",
        "bench/h2h/scaling/h2h13/cross-format.json",
        "bench/h2h/scaling/h2h13/cross-format.log",
        "bench/h2h/scaling/h2h4/run1/con-h2h.json",
        "bench/h2h/scaling/h2h4/run1/con-h2h.log",
        "bench/h2h/scaling/h2h4/run1/h2h.json",
        "bench/h2h/scaling/h2h4/run1/h2h.log",
        "bench/h2h/scaling/h2h4/run2/con-h2h.json",
        "bench/h2h/scaling/h2h4/run2/con-h2h.log",
        "bench/h2h/scaling/h2h4/run2/h2h.json",
        "bench/h2h/scaling/h2h4/run2/h2h.log",
        "bench/h2h/scaling/h2h6/cross-format.json",
        "bench/h2h/scaling/h2h7/cross-format.json",
        "bench/h2h/scaling/h2h7/cross-format.log",
        "bench/h2h/scaling/h2h8/cross-format.json",
        "bench/h2h/scaling/h2h8/cross-format.log",
        "bench/h2h/scaling/h2h9/chemfiles-write-profile.txt",
        "bench/h2h/scaling/h2h9/cross-format.json",
        "bench/h2h/scaling/h2h9/cross-format.log",
        "bench/h2h/scaling/perf17/NOTES.txt",
        "bench/h2h/scaling/perf17/sink-ceiling.json",
        "bench/h2h/scaling/rel1/c.time",
        "bench/h2h/scaling/rel1/con-h2h.json",
        "bench/h2h/scaling/rel1/con-h2h.log",
        "bench/h2h/scaling/rel1/cpp.time",
        "bench/h2h/scaling/rel1/cross-format.json",
        "bench/h2h/scaling/rel1/cross-format.log",
        "bench/h2h/scaling/rel1/fidelity.log",
        "bench/h2h/scaling/rel1/fortran.time",
        "bench/h2h/scaling/rel1/h2h.json",
        "bench/h2h/scaling/rel1/h2h.log",
        "bench/h2h/scaling/rel1/perf2-samples.json",
        "bench/h2h/scaling/rel1/perf3-samples.json",
        "bench/h2h/scaling/rel1/perf5-samples.json",
        "bench/h2h/scaling/rel1/python.time",
        "bench/h2h/scaling/rel1/rust-gzip.time",
        "bench/h2h/scaling/rel1/rust-path.time",
    }
)


def scanned(path: str) -> bool:
    """Every tracked file. Saved records that already name a machine stay listed."""
    return path not in SAVED_MACHINE_RECORDS


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


def _library_scope(path: str) -> bool:
    """The library and the build script, outside doctests and ``#[cfg(test)]``."""
    return path == "build.rs" or (path.startswith("src/") and path.endswith(".rs"))


def _tool_scope(path: str) -> bool:
    """Sources that build or ship the library, plus the workflows and scripts."""
    return (
        path == "build.rs"
        or path == "CMakeLists.txt"
        or path.endswith("/CMakeLists.txt")
        or path.startswith(("src/", ".github/", "cmake/", "scripts/"))
    )


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
        if (path.startswith("scripts/") or path.startswith("bench/")) and any(
            token in line for token in PYTHON_SCRATCH
        ):
            found.append(f"{path}:{number}: {stripped}")
        if (
            path == "CMakeLists.txt"
            or path.endswith("/CMakeLists.txt")
            or path.startswith("cmake/")
        ) and any(token in line for token in CMAKE_ENV):
            found.append(f"{path}:{number}: {stripped}")
        rust = path == "build.rs" or path.endswith(".rs")
        in_test = bool(manifest_ok and manifest_ok[number - 1]) if rust else False
        if (
            TEMP_DIR_CALL in line
            and not in_test
            and (
                _library_scope(path)
                or not (path.startswith("src/") or path == "build.rs")
            )
        ):
            if (
                scanned(path)
                or path.endswith("planted.rs")
                or path.endswith("planted.py")
            ):
                found.append(f"{path}:{number}: {stripped}")
        if _tool_scope(path) and any(token in line for token in BUILD_TOKENS):
            found.append(f"{path}:{number}: {stripped}")
        if _tool_scope(path) and TMPDIR_READ.search(line):
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
    assert scanned("bench/h2h/scaling/rel1/raw/run.log")
    assert scanned("bench/h2h/camp7_ceiling.py")
    assert scanned("bench/h2h/Snakefile")
    assert scanned("src/conbin.rs")
    assert scanned("benchmarks/weak_scale.py")
    assert scanned("fortran/ReadCon/test/test_add_atom_frame.f90")
    assert scanned("build.rs")
    assert scanned("CMakeLists.txt")
    assert scanned(".github/workflows/ci_cxx.yml")
    for path in SAVED_MACHINE_RECORDS:
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        assert any(prefix in text for prefix in PATHS), path


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


def test_temp_dir_in_library_code_is_reported() -> None:
    planted = ["let directory = std::env::" + TEMP_DIR_CALL + ");"]
    assert offenders("src/planted.rs", planted)
    assert offenders("build.rs", planted)
    assert offenders("scripts/planted.rs", planted)
    assert offenders("cmake/planted.rs", planted)
    inside_test = [
        "#[cfg(test)]",
        "mod tests {",
        "    let directory = std::env::" + TEMP_DIR_CALL + ");",
        "}",
    ]
    assert offenders("src/planted.rs", inside_test) == []
    assert offenders("tests/planted.rs", planted)
    assert (
        offenders("tests/planted.rs", ["let directory = tempfile::tempdir().unwrap();"])
        == []
    )


def test_each_scratch_command_is_reported() -> None:
    samples = {
        "mktemp": "tmp=$(mktemp -d)",
        "GetTempPath": "[System.IO.Path]::GetTempPath()",
        "get_tempdir": "get_tempdir(OUT)",
        "TMPDIR": 'dir="${TMPDIR}/work"',
    }
    for token, line in samples.items():
        assert offenders("scripts/planted.sh", [line]), token
        assert offenders(".github/workflows/planted.yml", [line]), token
        assert offenders("cmake/planted.cmake", [line]), token
        assert offenders("CMakeLists.txt", [line]), token
        assert offenders("src/planted.rs", [line]), token
        assert offenders("build.rs", [line]), token
        assert offenders("tests/planted.sh", [line]) == [], token
    assert offenders(
        "scripts/planted.py",
        ["with tempfile." + PYTHON_SCRATCH[2] + "() as work:"],
    )
    assert offenders("bench/planted.py", ["path = " + PYTHON_SCRATCH[0] + "()"])
    assert offenders("tests/planted.py", ["path = " + PYTHON_SCRATCH[0] + "()"]) == []
    assert offenders("CMakeLists.txt", ["set(dir $ENV{TEMP}/work)"])
    assert offenders("cmake/planted.cmake", ["set(dir $ENV{TMP}/work)"])


def machine_path_in_record(text: str) -> str | None:
    """A bench record may not name a machine prefix. Historical campaigns stay put."""
    for prefix in (PATHS[0], PATHS[3]):
        if prefix in text:
            return prefix
    return None


def test_bench_records_have_no_machine_paths() -> None:
    """h2h15 records are scanned. Earlier campaigns are not rewritten."""
    planted = "profile " + PATHS[0] + "/venv/site-packages/chemfiles/frame.py"
    assert machine_path_in_record(planted) == PATHS[0]
    assert machine_path_in_record("bench/h2h/scaling/h2h15/host.json") is None
    listed = subprocess.check_output(
        ["git", "ls-files", "-z", "bench/h2h/scaling/h2h15"],
        cwd=ROOT,
    )
    bad: list[str] = []
    for raw in listed.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode()
        if not rel.endswith((".json", ".txt", ".log", ".tsv", ".md")):
            continue
        body = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if machine_path_in_record(body):
            bad.append(rel)
    assert not bad, "machine path in a bench record:\n" + "\n".join(bad)


def test_tracked_sources_have_no_machine_paths() -> None:
    found: list[str] = []
    for path in tracked_sources():
        file = ROOT / path
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        found.extend(offenders(path, text.splitlines()))
    assert not found, "machine path reintroduced:\n" + "\n".join(found)
