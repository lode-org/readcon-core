"""Drive scripts/run-chemfiles-notebook.sh (Org tangle + drift check + run)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import readcon

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "run-chemfiles-notebook.sh"
ORG = REPO / "docs" / "orgmode" / "chemfiles-notebook.org"
TANGLE_PY = REPO / "docs" / "notebooks" / "chemfiles_ingress.py"


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
    em = _emacs_path()
    if em:
        env["EMACS"] = em
    return env


pytestmark = pytest.mark.skipif(
    not getattr(readcon, "has_chemfiles_support", lambda: False)(),
    reason="chemfiles not linked (CI chemfiles matrix)",
)


def test_chemfiles_notebook_org_declares_tangle():
    org = ORG.read_text(encoding="utf-8")
    assert ":tangle ../notebooks/chemfiles_ingress.py" in org
    script = SCRIPT.read_text(encoding="utf-8")
    assert "tangle drift" in script
    assert "falling back" not in script
    # no soft-success paths (git-diff may use ``|| true`` only to print under set -e)
    assert "papermill" not in script or "|| true" not in script.split("papermill")[-1][:200]
    assert "missing after babel; trying tangled" not in script


def test_org_babel_chemfiles_notebook_script():
    if _emacs_path() is None:
        if os.environ.get("CI"):
            pytest.fail("emacs required on CI for Org Babel chemfiles notebook")
        pytest.skip("emacs required for org-babel-tangle")
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(REPO),
        env=_env(),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"run-chemfiles-notebook.sh failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    out = proc.stdout + proc.stderr
    assert "OK — tangled, drift-checked, and ran" in out
    summary = REPO / "docs" / "notebooks" / "out" / "work" / "summary.json"
    assert summary.is_file(), out
    body = summary.read_text(encoding="utf-8")
    assert "n_atoms" in body and "has_chemfiles_support" in body
    assert "read_chemfiles_first" in TANGLE_PY.read_text(encoding="utf-8")
