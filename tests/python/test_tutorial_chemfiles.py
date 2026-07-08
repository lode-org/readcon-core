"""Drive Org Babel chemfiles notebook via scripts/run-chemfiles-notebook.sh."""

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


def _emacs_available() -> bool:
    if os.environ.get("EMACS") and Path(os.environ["EMACS"]).is_file():
        return True
    if shutil.which("emacs"):
        return True
    for cand in (
        REPO / ".pixi" / "envs" / "docs" / "bin" / "emacs",
        Path.home() / ".pixi" / "envs" / "docs" / "bin" / "emacs",
    ):
        if cand.is_file():
            return True
    return False


pytestmark = [
    pytest.mark.skipif(
        not getattr(readcon, "has_chemfiles_support", lambda: False)(),
        reason="chemfiles not linked (CI chemfiles matrix)",
    ),
    pytest.mark.skipif(not _emacs_available(), reason="emacs required for org-babel"),
]


def test_org_babel_chemfiles_notebook_script():
    assert ORG.is_file() and SCRIPT.is_file()
    env = os.environ.copy()
    if "EMACS" not in env:
        for cand in (
            REPO / ".pixi" / "envs" / "docs" / "bin" / "emacs",
            Path.home() / ".pixi" / "envs" / "docs" / "bin" / "emacs",
        ):
            if cand.is_file():
                env["EMACS"] = str(cand)
                break
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"run-chemfiles-notebook.sh failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    out = proc.stdout + proc.stderr
    summary = REPO / "docs" / "notebooks" / "out" / "work" / "summary.json"
    assert summary.is_file() or "OK — executed" in out, out
    assert TANGLE_PY.is_file()
    assert "read_chemfiles_first" in TANGLE_PY.read_text(encoding="utf-8")


def test_chemfiles_notebook_org_declares_tangle():
    org = ORG.read_text(encoding="utf-8")
    assert ":tangle ../notebooks/chemfiles_ingress.py" in org
