"""Replace host-specific paths and the node name in the bench records.

The records keep the commands that built and ran the measurements; the
repository becomes ``$REPO``, the environment of the running Python
``$ENV``, and an install prefix named by one of ``VARIABLES`` outside both
becomes that variable, so the records carry no host paths
(``scripts/check_manuscript.py`` refuses them).  The build directory of
conda-forge packages, which their debug information names, becomes
``$CONDA_BUILD``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ENV = Path(sys.prefix).resolve()
BENCH = Path(__file__).resolve().parent
VARIABLES = ("READCON_SRC", "CHEMFILES_PREFIX", "OPENBABEL_INCLUDE", "BENCH_NATIVE_OUT", "BENCH_WORK",
             "BENCH_RESULTS", "RC_PAYLOADS", "CHEMFILES_BUILDS", "CARGO_TARGET_DIR")
DEFAULTS = {
    "READCON_SRC": str(REPO),
    "CHEMFILES_BUILDS": str(BENCH / "work" / "chemfiles"),
    "CARGO_TARGET_DIR": str(REPO / "target"),
    "CHEMFILES_PREFIX": str(ENV),
    "OPENBABEL_INCLUDE": str(ENV / "include" / "openbabel3"),
    "BENCH_NATIVE_OUT": str(BENCH / "work" / "native"),
    "BENCH_WORK": str(BENCH / "work" / "r0174"),
    "BENCH_RESULTS": str(BENCH / "results" / "r0174"),
    "RC_PAYLOADS": str(BENCH / "work" / "r0174"),
}
CONDA_BUILD = os.environ.get("CONDA_BUILD_PREFIX", "").strip()


def prefixes() -> list[tuple[str, str]]:
    pairs = [(str(REPO), "$REPO"), (str(ENV), "$ENV"), (sys.prefix.rstrip("/"), "$ENV")]
    if CONDA_BUILD:
        pairs.append((CONDA_BUILD, "$CONDA_BUILD"))
    for name in VARIABLES:
        value = os.environ.get(name, "").strip()
        if value and Path(value).resolve() != Path(DEFAULTS[name]).resolve():
            pairs.append((str(Path(value).resolve()), f"${name}"))
            pairs.append((value.rstrip("/"), f"${name}"))
    return sorted(set(pairs), key=lambda pair: -len(pair[0]))


def portable_text(text: str) -> str:
    """``text`` with the prefixes of ``prefixes`` replaced, then the home directory as ``$HOME``."""
    for prefix, name in [*prefixes(), (str(Path.home()), "$HOME")]:
        text = text.replace(prefix, name)
    return text


def portable(value, pairs: list[tuple[str, str]] | None = None):
    pairs = prefixes() if pairs is None else pairs
    if isinstance(value, dict):
        return {key: portable(item, pairs) for key, item in value.items() if key != "node"}
    if isinstance(value, list):
        return [portable(item, pairs) for item in value]
    if isinstance(value, str):
        for prefix, name in pairs:
            value = value.replace(prefix, name)
        return value
    return value
