"""A file a regen plotter reads, or a generated file the TeX inputs, has a writer."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPC = ROOT / "paper" / "cpc"
TEXTS = (CPC / "src" / "rg_main.tex", CPC / "src" / "rg_supp.tex")
INPUT = re.compile(r"\\(?:input|includegraphics)(?:\[[^\]]*\])?\{([^}]+)\}")
QUOTED = re.compile(r'["\']([^"\'\n]{1,180})["\']')
WRITE = re.compile(r"write_text|np\.savez|_json\(|open\([^)]*[\"']w|writerow")


def _named_steps(name: str) -> list[Path]:
    tree = ast.parse((CPC / "scripts" / "regen_paper.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == name for target in node.targets
        ):
            return [CPC / step[0] for step in ast.literal_eval(node.value)]
    raise AssertionError(f"regen_paper.py has no {name} list")


def _format_scripts() -> list[Path]:
    return _named_steps("FORMAT") + _named_steps("VERSION_MAP")


def _plotters() -> list[Path]:
    return [path for path in _format_scripts() if path.name.startswith("plot_")]


def _chunks(text: str) -> list[str]:
    parts = re.split(r"(?m)^(def |class )", text)
    chunks = [parts[0]]
    for marker, body in zip(parts[1::2], parts[2::2]):
        chunks.append(marker + body)
    return chunks


def _python_sources() -> list[Path]:
    found = []
    for folder in ("scripts", "bench", "evidence"):
        for path in (CPC / folder).rglob("*.py"):
            if ".pixi" in path.parts:
                continue
            found.append(path)
    return found


def _writes(rel: str) -> bool:
    """A committed script writes ``rel`` (relative to paper/cpc)."""
    name = Path(rel).name
    for path in _python_sources():
        if path.name.startswith("plot_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel.startswith("data/failure/bands/") and "data/failure/bands/*.npz" in text:
            if "np.savez" in text:
                return True
        for chunk in _chunks(text):
            if not WRITE.search(chunk):
                continue
            if rel in chunk:
                return True
            if f'"{name}"' in chunk or f"'{name}'" in chunk:
                return True
    return False


def _existing(rel: str) -> Path | None:
    path = CPC / rel
    return path if path.is_file() else None


def _plotter_inputs() -> set[str]:
    """Committed data, bench results, logs and evidence a FORMAT plotter reads."""
    found: set[str] = set()
    prefixes = ("data/", "bench/results/", "logs/", "evidence/results/")
    for script in _plotters():
        text = script.read_text(encoding="utf-8")
        for quoted in QUOTED.findall(text):
            if quoted.startswith(prefixes) and _existing(quoted):
                found.add(quoted)
            elif quoted.startswith("/") or quoted.startswith("~"):
                continue
            elif "/" in quoted and _existing(quoted):
                found.add(quoted)
            else:
                # A bare filename, joined onto a directory named in the same file.
                for prefix in prefixes:
                    candidate = prefix + quoted
                    if _existing(candidate):
                        found.add(candidate)
                    parent = quoted.split("/")
                    if len(parent) > 1 and _existing(prefix + quoted):
                        found.add(prefix + quoted)
    return found


def _generated_inputs() -> set[str]:
    found = set()
    for path in TEXTS:
        text = "\n".join(
            re.sub(r"(?<!\\)%.*", "", line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        for name in INPUT.findall(text):
            if name.startswith("figures/generated/"):
                found.add(name)
    return found


def test_plotter_inputs_have_committed_writers() -> None:
    missing = sorted(rel for rel in _plotter_inputs() if not _writes(rel))
    assert not missing, "plotter input with no committed writer:\n" + "\n".join(missing)


def test_tex_generated_inputs_have_format_writers() -> None:
    texts = [path.read_text(encoding="utf-8") for path in _python_sources()]
    missing = []
    for name in sorted(_generated_inputs()):
        stem = Path(name).stem
        tokens = (f'"{stem}"', f"'{stem}'", f"{stem}.tex", f"{stem}.pdf")
        if any(token in text for text in texts for token in tokens):
            continue
        missing.append(name)
    assert not missing, "TeX input with no committed writer:\n" + "\n".join(missing)
