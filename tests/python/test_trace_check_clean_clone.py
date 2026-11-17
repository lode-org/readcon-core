"""``trace_numbers.py --check`` on a clean clone.

``paper/cpc/data/trace/`` and the ``src/figures/generated/`` fragments the
manuscript inputs are gitignored, so a fresh checkout has neither. ``--check``
must build the ledger and the missing fragments it needs, write no tracked
file, and fail on a number that the Org source of the manuscript prints
differently from the TeX it exports to.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "trace_numbers.py"
LEDGER = ROOT / "paper" / "cpc" / "data" / "trace" / "numbers.csv"

CPC = Path("paper") / "cpc"
GENERATED = CPC / "src" / "figures" / "generated"
IDENTITY = ("-c", "user.name=trace test", "-c", "user.email=trace@test.invalid")

BLOCK_ASE = """\
import importlib.abc
import sys


class BlockAse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "ase" or name.startswith("ase."):
            raise ImportError("ase is blocked for this test")


sys.meta_path.insert(0, BlockAse())
"""


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _listed(*flags: str) -> list[str]:
    out = _git(ROOT, "ls-files", "-z", *flags)
    return [name for name in out.split("\0") if name]


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone of this checkout's commit, with the uncommitted changes of the working tree committed on top."""
    dst = tmp_path / "clone"
    _git(ROOT, "clone", "-q", "--local", str(ROOT), str(dst))
    _git(dst, "checkout", "-q", "--detach", _git(ROOT, "rev-parse", "HEAD").strip())
    changed = _listed("--modified", "--others", "--exclude-standard")
    removed = _listed("--deleted")
    for name in changed:
        if (ROOT / name).is_file():
            (dst / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dst / name)
    for name in removed:
        (dst / name).unlink(missing_ok=True)
    if changed or removed:
        _git(dst, "add", "-A")
        _git(
            dst,
            *IDENTITY,
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-q",
            "-m",
            "working tree",
        )
    assert _git(dst, "status", "--porcelain") == ""
    return dst


def _check(
    clone: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(clone / CPC / "scripts" / "trace_numbers.py"), "--check"],
        cwd=clone,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def _path_without_emacs(directory: Path) -> str:
    """A ``PATH`` of one directory that links every program of the current ``PATH`` but ``emacs``."""
    directory.mkdir()
    for entry in os.environ["PATH"].split(os.pathsep):
        if not entry or not Path(entry).is_dir():
            continue
        for program in Path(entry).iterdir():
            link = directory / program.name
            if (
                not program.name.startswith("emacs")
                and not link.exists()
                and os.access(program, os.X_OK)
            ):
                link.symlink_to(program)
    return str(directory)


def _status(clone: Path) -> str:
    return _git(clone, "status", "--porcelain")


def _load_trace_numbers():
    spec = importlib.util.spec_from_file_location("trace_numbers_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _edit_first_org_number(clone: Path, name: str) -> int:
    """Change one printed number of ``name`` in the clone, and return its line."""
    trace = _load_trace_numbers()
    org = (clone / CPC / "src" / "rg_main.org").read_text().splitlines()
    start = trace._document_start(org, "rg_main.org")
    printed, _ = trace.scan_lines(name, list(enumerate(org, start=1))[start:])
    first = next(item for item in printed if item.text.isdigit() and len(item.text) > 1)
    path = clone / CPC / "src" / name
    lines = path.read_text().splitlines(keepends=True)
    index = first.line - 1 if name.endswith(".org") else None
    if index is None:
        index = next(i for i, line in enumerate(lines) if first.context in line)
    changed = first.text[:-1] + str((int(first.text[-1]) + 1) % 10)
    assert first.text in lines[index], (first.text, lines[index])
    lines[index] = lines[index].replace(first.text, changed, 1)
    path.write_text("".join(lines))
    return index + 1


def test_check_builds_the_ledger_on_a_clean_tree() -> None:
    had_ledger = LEDGER.is_file()
    backup = LEDGER.read_bytes() if had_ledger else None
    if had_ledger:
        LEDGER.unlink()
    try:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "0 problems" in done.stdout, done.stdout
        assert LEDGER.is_file(), "--check did not build the missing ledger"
    finally:
        if backup is not None:
            LEDGER.write_bytes(backup)


def test_check_on_a_clean_clone_writes_no_tracked_file(clone: Path) -> None:
    done = _check(clone)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 problems" in done.stdout, done.stdout
    assert (clone / CPC / "data" / "trace" / "numbers.csv").is_file()
    for name in ("sizes_macros.tex", "sizes_table.tex"):
        assert (clone / GENERATED / name).is_file(), name
    assert _status(clone) == "", _status(clone)


def test_check_writes_only_the_missing_fragments(clone: Path) -> None:
    first = _check(clone)
    assert first.returncode == 0, first.stdout + first.stderr
    generated = clone / GENERATED
    gone = ("sizes_macros.tex", "sizes_table.tex")
    for name in gone:
        (generated / name).unlink()
    before = {
        path.name: path.stat().st_mtime_ns
        for path in generated.iterdir()
        if path.is_file()
    }
    done = _check(clone)
    assert done.returncode == 0, done.stdout + done.stderr
    for name in gone:
        assert (generated / name).is_file(), name
    after = {
        path.name: path.stat().st_mtime_ns
        for path in generated.iterdir()
        if path.is_file()
    }
    assert {k: v for k, v in after.items() if k not in gone} == before
    assert _status(clone) == "", _status(clone)


@pytest.mark.parametrize("name", ["rg_main.org", "rg_main.tex"])
def test_check_fails_on_a_number_edited_in_one_source(clone: Path, name: str) -> None:
    line = _edit_first_org_number(clone, name)
    done = _check(clone)
    assert done.returncode != 0, done.stdout + done.stderr
    assert f"{name}:{line}:" in done.stdout, done.stdout


def test_check_fails_on_an_org_number_without_emacs(
    clone: Path, tmp_path: Path
) -> None:
    first = _check(clone)
    assert first.returncode == 0, first.stdout + first.stderr
    line = _edit_first_org_number(clone, "rg_main.org")
    bare = _path_without_emacs(tmp_path / "bare")
    done = _check(clone, {"PATH": bare})
    assert shutil.which("emacs", path=bare) is None
    assert done.returncode != 0, done.stdout + done.stderr
    assert f"rg_main.org:{line}:" in done.stdout, done.stdout
    assert "rg_main.tex is not the Org export" not in done.stdout
    assert "emacs is not on PATH" in done.stderr, done.stderr


def test_check_fails_when_the_tex_is_not_the_org_export(clone: Path) -> None:
    assert shutil.which("emacs"), "emacs is required to export rg_main.org"
    tex = clone / CPC / "src" / "rg_main.tex"
    text = tex.read_text()
    assert "geometry checkpoint" in text
    tex.write_text(text.replace("geometry checkpoint", "geometry check-point", 1))
    done = _check(clone)
    assert done.returncode != 0, done.stdout + done.stderr
    assert "rg_main.tex is not the Org export of rg_main.org" in done.stdout


def test_check_needs_no_ase(clone: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(BLOCK_ASE)
    inherited = os.environ.get("PYTHONPATH")
    env = {"PYTHONPATH": os.pathsep.join([p for p in (str(blocker), inherited) if p])}
    probe = subprocess.run(
        [sys.executable, "-c", "import ase"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode != 0 and "ase is blocked" in probe.stderr, probe.stderr
    done = _check(clone, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 problems" in done.stdout, done.stdout
    assert "ModuleNotFoundError" not in done.stderr + done.stdout
    for name in ("spec_macros.tex", "versions_table.tex", "sizes_table.tex"):
        assert (clone / GENERATED / name).is_file(), name
    assert _status(clone) == "", _status(clone)


DRIVER = """\
import json
import sys

sys.path.insert(0, sys.argv[1])
import trace_numbers

keep = set(sys.argv[2:])
every = trace_numbers.generated_tex_inputs
trace_numbers.generated_tex_inputs = lambda: [p for p in every() if p.name in keep]
print(json.dumps(trace_numbers.ensure_generated() or []))
"""
SIZES = ("sizes_macros.tex", "sizes_table.tex")
TABLE = Path("src") / "figures" / "generated" / "sizes_table.tex"
MACROS = Path("src") / "figures" / "generated" / "sizes_macros.tex"
FILE_SIZES = Path("scripts") / "file_sizes.py"
SIZES_CSV = Path("data") / "sizes.csv"


def _ensure(
    clone: Path, names: tuple[str, ...] = SIZES
) -> subprocess.CompletedProcess[str]:
    """``ensure_generated`` of the clone, limited to the named fragments, by default those of ``file_sizes.py --table``.

    The fragments of the other generators do not matter to what it does with
    these, and a record elsewhere that a generator refuses does not stop it.
    """
    return subprocess.run(
        [
            sys.executable,
            "-c",
            DRIVER,
            str(clone / CPC / "scripts"),
            *names,
        ],
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
    )


def _problems(done: subprocess.CompletedProcess[str]) -> list[str]:
    assert done.returncode == 0, done.stdout + done.stderr
    value = json.loads(done.stdout.strip().splitlines()[-1])
    return value


def _bump_a_cell(text: str) -> str:
    """The first two-decimal number of the table with its last digit raised."""
    cell = re.search(r"(?<![\d.])\d+\.\d(\d)(?!\d)", text)
    assert cell is not None
    digit = str((int(cell.group(1)) + 1) % 10)
    return text[: cell.end() - 1] + digit + text[cell.end() :]


def _generated(clone: Path) -> Path:
    first = _problems(_ensure(clone))
    assert first == []
    return clone / CPC / TABLE


def test_a_stale_table_cell_is_reported_with_a_diff(clone: Path) -> None:
    table = _generated(clone)
    macros = clone / CPC / MACROS
    kept = macros.read_bytes()
    edited = _bump_a_cell(table.read_text())
    table.write_text(edited)
    problems = _problems(_ensure(clone))
    assert len(problems) == 1, problems
    assert problems[0].startswith("figures/generated/sizes_table.tex: differs"), (
        problems
    )
    assert "file_sizes.py" in problems[0], problems
    removed = [ln for ln in problems[0].splitlines() if ln.startswith("  -")]
    added = [ln for ln in problems[0].splitlines() if ln.startswith("  +")]
    assert len(removed) > 1 and len(added) > 1, problems[0]
    assert table.read_text() == edited
    assert macros.read_bytes() == kept
    assert _status(clone) == "", _status(clone)


def test_a_stale_csv_leaves_its_fragments_reported(clone: Path) -> None:
    table = _generated(clone)
    macros = clone / CPC / MACROS
    before = (table.read_bytes(), macros.read_bytes())
    csv_path = clone / CPC / SIZES_CSV
    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = list(rows[0])
    rows[0]["bytes_per_atom"] = f"{float(rows[0]['bytes_per_atom']) + 1:.2f}"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    dirty = _status(clone)
    assert dirty.strip() == f"M {(CPC / SIZES_CSV).as_posix()}", dirty
    problems = _problems(_ensure(clone))
    assert any(
        p.startswith("figures/generated/sizes_macros.tex: differs") for p in problems
    ), problems
    assert (table.read_bytes(), macros.read_bytes()) == before
    assert _status(clone) == dirty


def test_a_present_sibling_is_not_overwritten_when_one_output_is_missing(
    clone: Path,
) -> None:
    table = _generated(clone)
    macros = clone / CPC / MACROS
    original = macros.read_bytes()
    edited = _bump_a_cell(table.read_text())
    table.write_text(edited)
    macros.unlink()
    problems = _problems(_ensure(clone))
    assert macros.read_bytes() == original
    assert table.read_text() == edited
    assert [p.split(":")[0] for p in problems] == ["figures/generated/sizes_table.tex"]
    assert _status(clone) == "", _status(clone)


def _fail_after_writing(clone: Path, junk: bool) -> None:
    """Make ``file_sizes.py --table`` exit 3 after it has written its outputs, and optionally after a wrong one."""
    script = clone / CPC / FILE_SIZES
    text = script.read_text()
    assert text.endswith("    table()\n")
    extra = (
        '    (GENERATED / "sizes_table.tex").write_text("% wrong\\n")\n' if junk else ""
    )
    script.write_text(text + extra + "    sys.exit(3)\n")


def test_the_outputs_of_a_failing_generator_are_not_kept(clone: Path) -> None:
    _fail_after_writing(clone, junk=False)
    done = _ensure(clone)
    assert done.returncode != 0, done.stdout
    assert "scripts/file_sizes.py --table exited 3" in done.stderr, done.stderr
    for name in SIZES:
        assert not (clone / GENERATED / name).exists(), name


def test_a_failing_generator_is_reported_and_leaves_present_fragments(
    clone: Path,
) -> None:
    table = _generated(clone)
    kept = (table.read_bytes(), (clone / CPC / MACROS).read_bytes())
    _fail_after_writing(clone, junk=True)
    problems = _problems(_ensure(clone))
    assert any("scripts/file_sizes.py --table exited 3" in p for p in problems), (
        problems
    )
    assert not any("wrong" in p for p in problems), problems
    assert (table.read_bytes(), (clone / CPC / MACROS).read_bytes()) == kept


DLPACK = "dlpack_macros.tex"
DLPACK_RECORD = Path("data") / "dlpack_cost.txt"
VERSION_MAP = "version_map.tex"
STUB_VERSION_MAP = Path("scripts") / "stub_version_map.py"

STUB = """\
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
steps = json.loads((CPC / "data" / "trace" / "reads.json").read_text())["steps"]
rows = "".join(f"readcon-core 0.17.4: {step['step']}\\n" for step in steps)
(CPC / "src" / "figures" / "generated" / "version_map.tex").write_text(rows)
sys.exit(EXIT_CODE)
"""


def _fragment(clone: Path, name: str) -> Path:
    return clone / CPC / "src" / "figures" / "generated" / name


def _stub_exits(clone: Path, code: int) -> None:
    (clone / CPC / STUB_VERSION_MAP).write_text(STUB.replace("EXIT_CODE", str(code)))


def _version_map_from_a_stub(clone: Path) -> None:
    """Point ``regen_paper.py`` of the clone at one format step and a stand-in for ``gen_version_map.py``.

    The records of the readcon-db campaigns name no build, so the real map is
    refused here whatever is traced; the stand-in writes ``version_map.tex``
    from the ledger of the steps, as the real one does, and exits zero.
    """
    _stub_exits(clone, 0)
    path = clone / CPC / "scripts" / "regen_paper.py"
    text = path.read_text()
    steps, count = re.subn(
        r"^FORMAT = \[\n.*?^\]\n",
        'FORMAT = [\n    ["scripts/file_sizes.py", "--table"],\n]\n',
        text,
        count=1,
        flags=re.M | re.S,
    )
    assert count == 1
    swapped = steps.replace(
        'VERSION_MAP = ["scripts/gen_version_map.py"]',
        f'VERSION_MAP = ["{STUB_VERSION_MAP.as_posix()}"]',
    )
    assert swapped != steps
    path.write_text(swapped)


def _regenerate_version_map(clone: Path) -> Path:
    done = subprocess.run(
        [sys.executable, str(clone / CPC / "scripts" / "regen_paper.py")],
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return _fragment(clone, VERSION_MAP)


def test_the_tracked_dlpack_macros_equal_their_generator(clone: Path) -> None:
    macros = _fragment(clone, DLPACK)
    before = macros.read_bytes()
    assert _problems(_ensure(clone, (DLPACK,))) == []
    assert macros.read_bytes() == before
    assert _status(clone) == "", _status(clone)


def test_an_edited_dlpack_macros_file_is_reported_with_a_diff(clone: Path) -> None:
    macros = _fragment(clone, DLPACK)
    text = macros.read_text()
    assert r"\newcommand{\dlpackViewUs}{98.523}" in text
    edited = text.replace("{98.523}", "{98.524}", 1)
    macros.write_text(edited)
    problems = _problems(_ensure(clone, (DLPACK,)))
    assert len(problems) == 1, problems
    assert problems[0].startswith("figures/generated/dlpack_macros.tex: differs"), (
        problems
    )
    assert "gen_dlpack_macros.py" in problems[0], problems
    assert r"-\newcommand{\dlpackViewUs}{98.524}" in problems[0], problems[0]
    assert r"+\newcommand{\dlpackViewUs}{98.523}" in problems[0], problems[0]
    assert macros.read_text() == edited
    assert _status(clone).strip() == f"M {(GENERATED / DLPACK).as_posix()}"


def test_a_dlpack_record_that_changed_leaves_the_macros_reported(clone: Path) -> None:
    record = clone / CPC / DLPACK_RECORD
    text = record.read_text()
    assert "repeat 3 view_ns 98521 copy_ns" in text
    record.write_text(
        text.replace("repeat 3 view_ns 98521", "repeat 3 view_ns 98999", 1)
    )
    problems = _problems(_ensure(clone, (DLPACK,)))
    assert [p.split(":")[0] for p in problems] == [
        "figures/generated/dlpack_macros.tex"
    ]
    assert _status(clone).strip() == f"M {(CPC / DLPACK_RECORD).as_posix()}"


def _input_a_stray_fragment(clone: Path) -> None:
    """Make ``rg_supp.tex`` input ``stray_fragment.tex``, which no step of ``regen_paper.py`` writes."""
    supp = clone / CPC / "src" / "rg_supp.tex"
    text = supp.read_text()
    anchor = "\\input{figures/generated/dlpack_macros}\n"
    assert anchor in text
    supp.write_text(
        text.replace(anchor, anchor + "\\input{figures/generated/stray_fragment}\n", 1)
    )


def test_a_generated_input_that_no_step_writes_is_reported_by_name(
    clone: Path,
) -> None:
    _input_a_stray_fragment(clone)
    stray = _fragment(clone, "stray_fragment.tex")
    stray.write_text("\\newcommand{\\strayValue}{42}\n")
    problems = _problems(_ensure(clone, ("stray_fragment.tex",)))
    assert len(problems) == 1, problems
    assert problems[0].startswith("figures/generated/stray_fragment.tex:"), problems
    assert "no format step" in problems[0] and "cannot be validated" in problems[0]
    assert stray.read_text() == "\\newcommand{\\strayValue}{42}\n"


def test_a_missing_generated_input_that_no_step_writes_is_refused(
    clone: Path,
) -> None:
    _input_a_stray_fragment(clone)
    done = _ensure(clone, ("stray_fragment.tex",))
    assert done.returncode != 0, done.stdout
    assert "no format step writes figures/generated/stray_fragment.tex" in done.stderr


def test_an_edited_version_map_is_reported_with_a_diff(clone: Path) -> None:
    _version_map_from_a_stub(clone)
    version_map = _regenerate_version_map(clone)
    assert "readcon-core 0.17.4" in version_map.read_text()
    assert _problems(_ensure(clone, (VERSION_MAP,))) == []
    edited = version_map.read_text().replace("0.17.4", "0.17.5", 1)
    version_map.write_text(edited)
    problems = _problems(_ensure(clone, (VERSION_MAP,)))
    assert len(problems) == 1, problems
    assert problems[0].startswith("figures/generated/version_map.tex: differs"), (
        problems
    )
    assert "-readcon-core 0.17.5:" in problems[0], problems[0]
    assert "+readcon-core 0.17.4:" in problems[0], problems[0]
    assert version_map.read_text() == edited


def test_the_version_map_is_checked_without_writing_a_tracked_file(
    clone: Path,
) -> None:
    _version_map_from_a_stub(clone)
    _regenerate_version_map(clone)
    before = _status(clone)
    assert _problems(_ensure(clone, (VERSION_MAP,))) == []
    assert _status(clone) == before
    assert (clone / CPC / "data" / "trace" / "reads.json").is_file()


def test_a_version_map_that_cannot_be_built_is_reported_not_skipped(
    clone: Path,
) -> None:
    _version_map_from_a_stub(clone)
    version_map = _regenerate_version_map(clone)
    kept = version_map.read_text()
    _stub_exits(clone, 4)
    problems = _problems(_ensure(clone, (VERSION_MAP,)))
    assert any(
        p.startswith("figures/generated/version_map.tex: no successful format step")
        for p in problems
    ), problems
    assert any(
        p.startswith("scripts/regen_paper.py exited")
        and "stub_version_map.py exited 4" in p
        for p in problems
    ), problems
    assert version_map.read_text() == kept
