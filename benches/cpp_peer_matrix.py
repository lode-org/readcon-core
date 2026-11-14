#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Build one C++ head-to-head cell.

The cell links this checkout's ``libreadcon_core`` and one chemfiles 0.10.4
build. ``CELLS`` is the compiler and the optimization level, in the order
``h2h.py`` interleaves.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SOURCE = REPO / "paper" / "cpc" / "bench" / "native" / "cpp_ratio.cpp"
INCLUDE = REPO / "include"

# compiler name, optimization flag, chemfiles build directory
CELLS = (
    ("gcc", "-O2", "build-gcc-o2"),
    ("gcc", "-O3", "build-gcc-o3"),
    ("clang", "-O2", "build-clang-o2"),
    ("clang", "-O3", "build-clang-o3"),
)


def compiler_version(compiler: str) -> str:
    proc = subprocess.run(
        [compiler, "--version"],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.splitlines()[0].strip()


def build_cell(
    name: str,
    compiler: str,
    opt: str,
    chemfiles_src: Path,
    chem_build: Path,
    library_dir: Path,
    work: Path,
    gcc_major: str,
) -> tuple[Path, Path]:
    del name
    binary = Path(work) / f"cpp_ratio-{Path(compiler).name}-{opt.lstrip('-')}"
    command = [
        compiler,
        opt,
        "-std=c++17",
        "-DNDEBUG",
        f"-I{INCLUDE}",
        f"-I{chemfiles_src}/include",
        f"-I{chem_build}/include",
        str(SOURCE),
        f"-L{library_dir}",
        f"-L{chem_build}",
        "-lreadcon_core",
        "-lchemfiles",
        f"-Wl,-rpath,{library_dir}",
        f"-Wl,-rpath,{chem_build}",
        "-o",
        str(binary),
    ]
    if Path(compiler).name.startswith("clang"):
        libstdcxx = f"/usr/lib/gcc/x86_64-linux-gnu/{gcc_major}"
        command[1:1] = [
            f"-I/usr/include/c++/{gcc_major}",
            f"-I/usr/include/x86_64-linux-gnu/c++/{gcc_major}",
            f"-L{libstdcxx}",
        ]
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-2000:] or proc.stdout[-2000:])
    return binary, chem_build
