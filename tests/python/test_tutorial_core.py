"""Drive the Org Babel One Good Tutorial via scripts/run-tutorial-core.sh.

Org source: docs/orgmode/tutorial.org → docs/notebooks/tutorial_core.py.
"""

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


@pytest.mark.skipif(not _emacs_available(), reason="emacs required for org-babel-tangle")
def test_org_babel_tutorial_core_script():
    assert ORG.is_file() and SCRIPT.is_file()
    env = os.environ.copy()
    env["READCON_TUT_ROOT"] = str(REPO)
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
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"run-tutorial-core.sh failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    out = proc.stdout + proc.stderr
    assert "OK — tangled and ran" in out
    summary = REPO / "docs" / "notebooks" / "out" / "tutorial_core" / "summary.json"
    assert summary.is_file(), f"missing {summary}\n{out}"
    assert "built_energy" in summary.read_text(encoding="utf-8")
    assert TANGLE_PY.is_file()
    tangled = TANGLE_PY.read_text(encoding="utf-8")
    assert "iter_con" in tangled and "iter_frames" not in tangled


def test_org_source_declares_tangle():
    org = ORG.read_text(encoding="utf-8")
    assert ":tangle ../notebooks/tutorial_core.py" in org
    assert "run-tutorial-core.sh" in org
