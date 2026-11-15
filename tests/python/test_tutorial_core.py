"""Drive scripts/run-tutorial-core.sh (Org tangle + drift check + run)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "run-tutorial-core.sh"
TANGLE_PY = REPO / "docs" / "notebooks" / "tutorial_core.py"
ORG = REPO / "docs" / "orgmode" / "tutorial.org"


def _emacs_path() -> str | None:
    if os.environ.get("EMACS") and Path(os.environ["EMACS"]).is_file():
        return os.environ["EMACS"]
    w = shutil.which("emacs")
    if w:
        return w
    for cand in (
        REPO / ".pixi" / "envs" / "docs" / "bin" / "emacs",
        Path.home() / ".pixi" / "envs" / "docs" / "bin" / "emacs",
    ):
        if cand.is_file():
            return str(cand)
    return None


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["READCON_TUT_ROOT"] = str(REPO)
    em = _emacs_path()
    if em:
        env["EMACS"] = em
    return env


def test_org_source_declares_tangle_and_ci_script():
    org = ORG.read_text(encoding="utf-8")
    assert ":tangle ../notebooks/tutorial_core.py" in org
    assert "run-tutorial-core.sh" in org
    assert "drift" in org.lower() or "READCON_TANGLE_UPDATE" in org
    script = SCRIPT.read_text(encoding="utf-8")
    assert "tangle drift" in script
    assert "falling back" not in script
    assert '"$PYTHON_BIN" "$TANGLE_PY"' in script


def test_tutorial_script_does_not_call_system_python3():
    """A bare python3 is the system interpreter, not the venv maturin used."""
    script = SCRIPT.read_text(encoding="utf-8")
    hits = []
    for number, line in enumerate(script.splitlines(), 1):
        code = line.split("#", 1)[0]
        if re.search(r"(^|[^$A-Za-z0-9_])python3\b", code):
            hits.append(f"{number}: {line.strip()}")
    assert not hits, "script hard-codes system python3:\n" + "\n".join(hits)


def _maturin_invocation(python: str) -> str | None:
    """Return how ``python`` can reach maturin, or None if it is not installed.

    A virtualenv keeps the maturin script beside the interpreter. Other
    layouts put that script elsewhere on PATH, or expose only
    ``python -m maturin``.
    """
    found = shutil.which("maturin")
    if found:
        return found
    sibling = Path(python).resolve().with_name("maturin")
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return str(sibling)
    proc = subprocess.run(
        [python, "-m", "maturin", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode == 0:
        return f"{python} -m maturin"
    return None


def _runner_env(python: str, maturin: str) -> dict[str, str]:
    """Use pytest's interpreter, and make the maturin we found visible."""
    env = _env()
    env["PYTHON"] = python
    exe = Path(python).resolve()
    venv = env.get("VIRTUAL_ENV")
    if venv and Path(venv).resolve() != exe.parent.parent:
        # Pytest is not the interpreter of the active virtualenv.
        env.pop("VIRTUAL_ENV", None)
    bins = [str(exe.parent)]
    maturin_path = Path(maturin)
    if maturin_path.is_file():
        bins.append(str(maturin_path.resolve().parent))
    env["PATH"] = os.pathsep.join(bins) + os.pathsep + env.get("PATH", "")
    return env


def test_org_babel_tutorial_core_script():
    if _emacs_path() is None:
        if os.environ.get("CI"):
            pytest.fail("emacs required on CI for Org Babel tutorials")
        pytest.skip("emacs required for org-babel-tangle")
    python = sys.executable
    maturin = _maturin_invocation(python)
    if maturin is None:
        pytest.skip(
            "maturin is unavailable: not on PATH, not beside the pytest "
            "interpreter, and `python -m maturin` failed"
        )
    assert ORG.is_file() and SCRIPT.is_file()
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(REPO),
        env=_runner_env(python, maturin),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"run-tutorial-core.sh failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    out = proc.stdout + proc.stderr
    assert "OK — tangled, drift-checked, and ran" in out
    summary = REPO / "docs" / "notebooks" / "out" / "tutorial_core" / "summary.json"
    assert summary.is_file()
    body = summary.read_text(encoding="utf-8")
    assert "built_energy" in body and "multi_frames" in body
    tangled = TANGLE_PY.read_text(encoding="utf-8")
    assert "iter_con" in tangled and "iter_frames" not in tangled
