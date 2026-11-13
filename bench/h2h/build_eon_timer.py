#!/usr/bin/env python3
"""Build bench/h2h/work/eon_time against eOn's release library.

eOn is pinned at the commit in bench/h2h/versions.json. Meson is configured
with --buildtype=release, which is -O3 and not the debugoptimized default
(that default also defines EON_CHECKS). ConFileIO.cpp is then recompiled
with the empty corpus-mirror header in bench/h2h/eon_stub so the timed
read and write are the Matter conversion and the file write.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
EON_SRC = Path(os.environ.get("EON_ROOT", "/tmp/eOn"))
EON_BUILD = Path(os.environ.get("EON_BUILD", "/tmp/eon-build"))
BINARY = BENCH / "work" / "eon_time"
FLAGS = BENCH / "work" / "eon_time.flags"
STUB = BENCH / "eon_stub"
SOURCE = BENCH / "eon_time.cpp"
PIN = "579738a9387e8d0ea55496f45dd057812cfab892"
TIMER_FLAGS = "-O3"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(cmd, check=False, cwd=cwd, text=True)
    if completed.returncode != 0:
        raise SystemExit(f"failed: {' '.join(cmd)}")


def eon_commit() -> str:
    completed = subprocess.run(
        ["git", "-C", str(EON_SRC), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def confile_command() -> dict:
    commands = json.loads((EON_BUILD / "compile_commands.json").read_text())
    for item in commands:
        if item["file"].endswith("ConFileIO.cpp"):
            return item
    raise SystemExit("ConFileIO.cpp is not in the eOn build")


def require_o3(command: str) -> None:
    if "-O3" not in command.split():
        raise SystemExit("eOn ConFileIO.cpp was not compiled with -O3")
    if "EON_CHECKS" in command:
        raise SystemExit("eOn release build still defines EON_CHECKS")


def recompile_without_mirror(item: dict) -> None:
    """Replace ConFileIO.cpp.o so the corpus mirror is not in the .so.

    ``#include "ReadconDbMirror.h"`` searches the source directory first, so
    the translation unit is copied next to the empty header and compiled
    from there. The object replaces the one ninja built.
    """
    command = item["command"]
    require_o3(command)
    parts = command.split()
    if "-o" not in parts or "-c" not in parts:
        raise SystemExit("ConFileIO compile command has no -o/-c")
    output = Path(parts[parts.index("-o") + 1])
    if not output.is_absolute():
        output = EON_BUILD / output
    source = item["file"]
    if not Path(source).is_absolute():
        source = str(Path(item["directory"]) / source)
    copy_dir = BENCH / "work" / "eon-confile"
    copy_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, copy_dir / "ConFileIO.cpp")
    shutil.copy(STUB / "ReadconDbMirror.h", copy_dir / "ReadconDbMirror.h")
    patched = command.replace(item["file"], str(copy_dir / "ConFileIO.cpp"))
    subprocess.run(patched, cwd=item["directory"], shell=True, check=True)
    if not output.is_file():
        raise SystemExit(f"missing recompiled {output}")


def link_timer() -> None:
    library = EON_BUILD / "client" / "libeonclib.so"
    readcon = EON_BUILD / "subprojects" / "readcon-core" / "libreadcon_core.so"
    if not library.is_file() or not readcon.is_file():
        raise SystemExit(f"missing {library} or {readcon}")
    item = confile_command()
    includes = [
        token for token in item["command"].split() if token.startswith(("-I", "-D"))
    ]
    rpath = os.pathsep.join(
        [
            str(library.parent),
            str(readcon.parent),
            str(EON_BUILD / "client" / "potentials" / "EMT"),
            str(EON_BUILD / "client" / "potentials" / "ExtPot"),
            str(EON_BUILD / "client" / "potentials" / "SocketNWChem"),
            str(EON_BUILD / "client" / "potentials" / "Rgpot"),
            str(EON_BUILD / "client" / "potentials" / "LAMMPS"),
            str(EON_BUILD / "subprojects" / "rgpot" / "CppCore"),
        ]
    )
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "c++",
        "-O3",
        "-std=c++20",
        "-DNDEBUG",
        f'-DEON_TIMER_FLAGS="{TIMER_FLAGS}"',
        *includes,
        str(SOURCE),
        "-o",
        str(BINARY),
        str(library),
        str(readcon),
        "-pthread",
        "-ldl",
        "-lm",
        f"-Wl,-rpath,{rpath}",
    ]
    run(cmd, cwd=EON_BUILD)
    FLAGS.write_text(
        "\n".join(
            [
                f"eon {eon_commit()}",
                f"timer {TIMER_FLAGS}",
                f"library {library}",
                "confile -O3",
                "mirror bench/h2h/eon_stub/ReadconDbMirror.h",
                "buildtype release",
            ]
        )
        + "\n"
    )


def main() -> None:
    commit = eon_commit()
    if commit != PIN:
        raise SystemExit(f"eOn {commit} != pinned {PIN}")
    if not (EON_BUILD / "build.ninja").is_file():
        meson = shutil.which("meson") or sys.executable + " -m meson"
        raise SystemExit(
            "eOn is not configured. From a release buildtype tree run "
            f"{meson} setup {EON_BUILD} {EON_SRC} --buildtype=release"
        )
    run(["ninja", "-C", str(EON_BUILD), "client/libeonclib.so"])
    recompile_without_mirror(confile_command())
    run(["ninja", "-C", str(EON_BUILD), "client/libeonclib.so"])
    link_timer()
    print(BINARY, flush=True)


if __name__ == "__main__":
    main()
