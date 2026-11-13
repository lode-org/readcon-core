#!/usr/bin/env python3
"""Programming-language line of the program summary, from this repository.

Rust and the crate list come from Cargo.toml. Python comes from
pyproject.toml. C and C++ come from the compiler sentence in README.md.
Julia comes from julia/ReadCon/Project.toml. Fortran 2008 is recorded
when the fortran tree uses ``error stop``.

    python3 paper/cpc/scripts/lang_summary.py
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "paper" / "cpc" / "src" / "figures" / "generated" / "lang_macros.tex"

REQUIRED_ORDER = (
    "dlpk",
    "half",
    "ndarray",
    "fast-float2",
    "ryu",
    "flate2",
    "serde_json",
    "memchr",
    "memmap2",
    "libc",
    "rustc-hash",
    "mimalloc",
)
OPTIONAL_NAMES = {
    "rayon": "Rayon",
    "zstd": "zstd",
    "mpi": "MPI",
    "chemfiles": "chemfiles",
    "metatensor": "metatensor",
    "cudarc": "CUDA",
    "capnp": "Cap'n Proto",
    "pest": "Pest",
}


def tex_list(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def main() -> None:
    cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    python = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    julia = tomllib.loads((ROOT / "julia" / "ReadCon" / "Project.toml").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    package = cargo["package"]
    rust = str(package["rust-version"])
    deps = cargo["dependencies"]
    required = [name for name in REQUIRED_ORDER if name in deps and "optional" not in deps[name]]
    missing = [name for name in REQUIRED_ORDER if name not in deps]
    if missing:
        raise SystemExit(f"Cargo.toml has no {missing}")
    optional = []
    for key, label in OPTIONAL_NAMES.items():
        spec = deps.get(key)
        if not spec or not spec.get("optional"):
            raise SystemExit(f"{key} is not an optional dependency")
        optional.append(label)
    if "C99 (`readcon-core.h`) or C++17 (`readcon-core.hpp`)" not in readme:
        raise SystemExit("README.md does not name the C99 and C++17 headers")
    requires = python["project"]["requires-python"]
    if not str(requires).startswith(">="):
        raise SystemExit(f"unexpected requires-python {requires}")
    py = str(requires).removeprefix(">=").strip()
    julia_version = julia["compat"]["julia"]
    fortran = list((ROOT / "fortran").rglob("*.f90"))
    if not any("error stop" in path.read_text(encoding="utf-8") for path in fortran):
        raise SystemExit("the fortran tree has no error stop, so it is not Fortran 2008")
    lines = [
        "% Written by paper/cpc/scripts/lang_summary.py from Cargo.toml, pyproject.toml,",
        "% julia/ReadCon/Project.toml, README.md and the fortran tree.",
        f"\\newcommand{{\\langRust}}{{{rust}}}",
        "\\newcommand{\\langC}{C99}",
        "\\newcommand{\\langCxx}{C++17}",
        f"\\newcommand{{\\langPy}}{{{py}}}",
        f"\\newcommand{{\\langJulia}}{{{julia_version}}}",
        "\\newcommand{\\langFortran}{Fortran 2008}",
        f"\\newcommand{{\\langRequired}}{{{tex_list(required).replace("_", "\\_")}}}",
        f"\\newcommand{{\\langOptional}}{{{tex_list(optional)}}}",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
