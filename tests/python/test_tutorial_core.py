"""Drive scripts/run-tutorial-core.sh (Org tangle + drift check + run)."""

from __future__ import annotations

import os
import shutil
import subprocess
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
    assert "python3 \"$TANGLE_PY\"" in script or 'python3 "$TANGLE_PY"' in script


def test_org_babel_tutorial_core_script():
    if _emacs_path() is None:
        if os.environ.get("CI"):
            pytest.fail("emacs required on CI for Org Babel tutorials")
        pytest.skip("emacs required for org-babel-tangle")
    assert ORG.is_file() and SCRIPT.is_file()
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(REPO),
        env=_env(),
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
