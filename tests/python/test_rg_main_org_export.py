"""The manuscript TeX is the Org export, byte for byte."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORG = ROOT / "paper/cpc/src/rg_main.org"
TEX = ROOT / "paper/cpc/src/rg_main.tex"
ELISP = ROOT / "paper/cpc/scripts/export_rg_main.el"


def test_rg_main_tex_is_the_org_export(tmp_path: Path) -> None:
    out = tmp_path / "rg_main.tex"
    done = subprocess.run(
        [
            "emacs",
            "--batch",
            "--eval",
            "(setq enable-local-eval t)",
            "-l",
            str(ELISP),
            "--eval",
            (
                f'(progn (find-file "{ORG}") '
                "(readcon-prepare-latex-export) "
                f'(org-export-to-file \'latex "{out}"))'
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert out.read_bytes() == TEX.read_bytes()
