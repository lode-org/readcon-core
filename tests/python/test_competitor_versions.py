"""MDAnalysis and OVITO are pinned to one version in every place the paper runs them."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MDA = "2.11.0"
OVITO = "3.17.2"


def _pixi() -> tuple[str, str]:
    text = (ROOT / "paper/cpc/pixi.toml").read_text(encoding="utf-8")
    mda = re.search(r'(?m)^mdanalysis\s*=\s*"==([^"]+)"', text)
    ovito = re.search(r'(?m)^ovito\s*=\s*"==([^"]+)"', text)
    assert mda and ovito
    return mda.group(1), ovito.group(1)


def _pin(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    found = re.search(rf"(?m)^{name}==(\S+)\s*$", text)
    assert found, f"{path} has no {name} pin"
    return found.group(1)


def _requirements(path: Path) -> tuple[str, str]:
    return _pin(path, "MDAnalysis"), _pin(path, "ovito")


def _lock_has(name: str, version: str) -> bool:
    text = (ROOT / "paper/cpc/pixi.lock").read_text(encoding="utf-8")
    return f"{name}-{version}-" in text or f"{name}-{version}." in text


def _conda_has(package: str, version: str) -> bool:
    text = (ROOT / "paper/cpc/environment/conda-linux-64.txt").read_text(
        encoding="utf-8"
    )
    return f"/{package}-{version}-" in text


def _library_versions() -> tuple[str, str]:
    text = (ROOT / "bench/h2h/cross_format.py").read_text(encoding="utf-8")
    block = re.search(r"required = \{([^}]+)\}", text)
    assert block, "library_versions() has no required pin"
    body = block.group(1)
    mda = re.search(r'"MDAnalysis": "([^"]+)"', body)
    ovito = re.search(r'"ovito": "([^"]+)"', body)
    assert mda and ovito
    return mda.group(1), ovito.group(1)


def _ci_python() -> str:
    """CI installs MDAnalysis for the arm tests. It does not install OVITO."""
    text = (ROOT / ".github/workflows/ci_python.yml").read_text(encoding="utf-8")
    mda = re.search(r"'MDAnalysis==([^']+)'", text)
    assert mda, "ci_python.yml installs no pinned MDAnalysis"
    return mda.group(1)


def test_competitor_versions_are_one_set() -> None:
    found = {
        "paper/cpc/pixi.toml": _pixi(),
        "bench/h2h/requirements.txt": _requirements(
            ROOT / "bench/h2h/requirements.txt"
        ),
        "library_versions()": _library_versions(),
    }
    for name, pair in found.items():
        assert pair == (MDA, OVITO), (name, pair)
    assert _ci_python() == MDA
    paper_req = ROOT / "paper/cpc/environment/requirements.txt"
    assert _pin(paper_req, "ovito") == OVITO
    assert _lock_has("mdanalysis", MDA)
    assert _lock_has("ovito", OVITO)
    assert _conda_has("mdanalysis", MDA)


def _canonical(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _lock_pypi() -> set[tuple[str, str]]:
    """Pinned PyPI distributions in pixi.lock, not conda packages or optional extras."""
    text = (ROOT / "paper/cpc/pixi.lock").read_text(encoding="utf-8")
    found = set()
    for url in re.findall(r"(?m)^- pypi: (\S+)", text):
        filename = url.rstrip("/").rsplit("/", 1)[-1]
        match = re.match(r"^(.*?)-(\d[\w.]*)-", filename)
        assert match, filename
        found.add((_canonical(match.group(1)), match.group(2)))
    return found


def test_requirements_match_the_locked_pypi_entries() -> None:
    locked = _lock_pypi()
    bad = []
    pinned = set()
    for line in (
        (ROOT / "paper/cpc/environment/requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==(\S+)", line)
        assert match, line
        pin = (_canonical(match.group(1)), match.group(2))
        pinned.add(pin)
        if pin not in locked:
            bad.append(line)
    # A locked PyPI entry with no requirements line is drift too.
    bad += [f"{name}=={version}" for name, version in sorted(locked - pinned)]
    assert not bad, (
        "requirements.txt and the pixi.lock pip entries differ:\n" + "\n".join(bad)
    )
