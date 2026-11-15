"""Every included figure is written by a step regen_paper.py runs."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPC = ROOT / "paper" / "cpc"
TEXTS = (CPC / "src" / "rg_main.tex", CPC / "src" / "rg_supp.tex")
GRAPHIC = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{figures/generated/([^}]+)\.pdf\}"
)
# A quoted figure stem passed to a saver, or a generated pdf path.
PRODUCED = re.compile(
    r"""(?:_save|bars|save)\(\s*(?:fig,\s*)?["']([A-Za-z][A-Za-z0-9_]*)["']"""
    r"""|["']([A-Za-z][A-Za-z0-9_]*)\.pdf["']"""
)


def _format_scripts() -> list[str]:
    tree = ast.parse((CPC / "scripts" / "regen_paper.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "FORMAT" for target in node.targets
        ):
            steps = ast.literal_eval(node.value)
            return [step[0] for step in steps]
    raise AssertionError("regen_paper.py has no FORMAT list")


def _producers() -> set[str]:
    found: set[str] = set()
    for script in _format_scripts():
        lines = []
        for line in (CPC / script).read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            lines.append(line)
        for stem, path in PRODUCED.findall("\n".join(lines)):
            found.add(stem or path)
    return found


def test_included_figures_have_a_regen_producer() -> None:
    produced = _producers()
    missing = []
    for path in TEXTS:
        text = "\n".join(
            re.sub(r"(?<!\\)%.*", "", line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        for stem in GRAPHIC.findall(text):
            if stem not in produced:
                missing.append(f"{path.name}: {stem}.pdf")
    assert not missing, "included figure with no regen producer:\n" + "\n".join(missing)
