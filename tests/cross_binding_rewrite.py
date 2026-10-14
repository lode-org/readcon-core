#!/usr/bin/env python3
"""Rewrite every accepted conformance file through C, Python, Julia, and Fortran.

The four outputs must be byte-identical. Accepted files are the [[valid]]
entries in resources/conformance/manifest.toml.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "resources" / "conformance" / "manifest.toml"


def unquote(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def accepted_paths() -> list[Path]:
    paths: list[Path] = []
    kind = None
    current: dict[str, str] = {}
    for raw in MANIFEST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in ("[[valid]]", "[[invalid]]"):
            if kind == "valid" and current.get("path"):
                paths.append(ROOT / "resources" / "conformance" / current["path"])
            kind = "valid" if line == "[[valid]]" else "invalid"
            current = {}
            continue
        if kind != "valid" or "=" not in line:
            continue
        key, val = [part.strip() for part in line.split("=", 1)]
        if key == "path":
            current["path"] = unquote(val)
    if kind == "valid" and current.get("path"):
        paths.append(ROOT / "resources" / "conformance" / current["path"])
    return paths


def exports_symbol(lib: Path, symbol: str) -> bool:
    proc = subprocess.run(
        ["nm", "-D", str(lib)], capture_output=True, text=True, check=False
    )
    return any(line.split()[-1:] == [symbol] for line in proc.stdout.splitlines())


def python_link_flags() -> list[str]:
    """The Python-enabled cdylib leaves libpython unresolved (extension-module)."""
    proc = subprocess.run(
        ["python3-config", "--ldflags", "--embed"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        return proc.stdout.split()
    return ["-lpython3.12"]


def run(cmd: list[str], **kwargs) -> None:
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True, **kwargs)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def show_diff(label: str, expected: bytes, actual: bytes) -> None:
    diff = difflib.unified_diff(
        expected.decode().splitlines(keepends=True),
        actual.decode(errors="replace").splitlines(keepends=True),
        fromfile="python",
        tofile=label,
    )
    sys.stderr.write(f"\n{label} differs from Python\n")
    sys.stderr.writelines(diff)


def main() -> None:
    lib = Path(os.environ["READCON_CORE_LIB"])
    py_lib = Path(os.environ.get("READCON_PYTHON_LIB", str(lib)))
    if not lib.is_file():
        raise SystemExit(f"missing shared library: {lib}")
    if not py_lib.is_file():
        raise SystemExit(f"missing Python extension: {py_lib}")
    files = accepted_paths()
    if not files:
        raise SystemExit("manifest has no accepted files")

    env = os.environ.copy()
    lib_dir = str(lib.parent)
    env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    env["READCON_CORE_LIB"] = str(lib)
    env["READCON_CORE_ROOT"] = str(ROOT)

    with tempfile.TemporaryDirectory(prefix="readcon-rewrite-") as tmp:
        work = Path(tmp)
        py_dir = work / "pyimport"
        py_dir.mkdir()
        shutil.copy(py_lib, py_dir / "readcon.so")
        env["PYTHONPATH"] = str(py_dir) + os.pathsep + env.get("PYTHONPATH", "")

        py_link = python_link_flags() if exports_symbol(lib, "PyInit_readcon") else []
        cc = work / "rewrite_corpus_c"
        run(
            [
                "cc",
                "-O2",
                f"-I{ROOT / 'include'}",
                str(ROOT / "tests" / "c" / "rewrite_corpus.c"),
                f"-L{lib_dir}",
                "-lreadcon_core",
                *py_link,
                "-lpthread",
                "-o",
                str(cc),
            ],
            env=env,
        )

        mod_dir = work / "fmod"
        mod_dir.mkdir()
        run(
            [
                "gfortran",
                "-J",
                str(mod_dir),
                "-c",
                str(ROOT / "fortran" / "ReadCon" / "src" / "readcon.f90"),
                "-o",
                str(work / "readcon.o"),
            ],
            env=env,
        )
        fc = work / "rewrite_corpus_f"
        run(
            [
                "gfortran",
                "-I",
                str(mod_dir),
                str(ROOT / "tests" / "fortran" / "rewrite_corpus.f90"),
                str(work / "readcon.o"),
                f"-L{lib_dir}",
                "-lreadcon_core",
                *py_link,
                "-lpthread",
                "-lstdc++",
                "-o",
                str(fc),
            ],
            env=env,
        )

        julia_snippet = (
            "using ReadCon\nframes = read_con(ARGS[1])\nwrite_con(ARGS[2], frames)\n"
        )

        mismatches = 0
        for src in files:
            out = work / src.name
            py_out = out.with_suffix(".py.con")
            c_out = out.with_suffix(".c.con")
            jl_out = out.with_suffix(".jl.con")
            f_out = out.with_suffix(".f.con")
            run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import readcon, sys\n"
                        "frames = readcon.read_con(sys.argv[1])\n"
                        "readcon.write_con(sys.argv[2], frames)\n"
                    ),
                    str(src),
                    str(py_out),
                ],
                env=env,
            )
            run([str(cc), str(src), str(c_out)], env=env)
            run(
                [
                    "julia",
                    f"--project={ROOT / 'julia' / 'ReadCon'}",
                    "-e",
                    julia_snippet,
                    str(src),
                    str(jl_out),
                ],
                env=env,
            )
            run([str(fc), str(src), str(f_out)], env=env)
            py_bytes = py_out.read_bytes()
            for label, path in (("C", c_out), ("Julia", jl_out), ("Fortran", f_out)):
                got = path.read_bytes()
                if got != py_bytes:
                    mismatches += 1
                    show_diff(f"{label} {src.name}", py_bytes, got)
            print(f"ok {src.name} ({len(py_bytes)} bytes)")

    if mismatches:
        raise SystemExit(f"{mismatches} rewrite(s) were not byte-identical")
    print(
        f"byte-identical rewrites: {len(files)} accepted files, C Python Julia Fortran"
    )


if __name__ == "__main__":
    main()
