"""Build and host record for every regenerated measurement.

Each field is read from the running library, the shared object it loaded,
the source tree and the host; nothing is typed in by hand.

The library is named by ``library_digest``, a SHA-256 over the files it is
built from, so a record, a clean clone and a tarball of the release tag give
the same name without git.  The same value is printed by

    (find src include build.rs Cargo.toml Cargo.lock pyproject.toml -type f | LC_ALL=C sort | xargs sha256sum) | sha256sum

run in the repository root.

    python paper/cpc/scripts/provenance.py            # the record every measurement stores
    python paper/cpc/scripts/provenance.py --digest   # the library digest of this tree
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LIBRARY_PATHS = ("src", "include", "build.rs", "Cargo.toml", "Cargo.lock", "pyproject.toml")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def library_files(root: Path = REPO) -> list[str]:
    """The files the Python module and the C library are built from, relative to ``root``."""
    files: list[str] = []
    for entry in LIBRARY_PATHS:
        path = root / entry
        if path.is_file():
            files.append(entry)
        elif path.is_dir():
            files.extend(p.relative_to(root).as_posix() for p in path.rglob("*") if p.is_file())
    return sorted(files)


def library_digest(root: Path = REPO) -> str:
    """SHA-256 of the ``sha256sum`` lines of ``library_files(root)`` in byte order of their paths."""
    lines = "".join(f"{_sha256(root / rel)}  {rel}\n" for rel in library_files(root))
    return hashlib.sha256(lines.encode()).hexdigest()


def library_digest_at(commit: str) -> str | None:
    """``library_digest`` of the library files in the tree of ``commit``, read from the git objects."""
    listing = _git("ls-tree", "-r", commit, "--", *LIBRARY_PATHS)
    if not listing:
        return None
    entries = sorted((line.split("\t", 1)[1], line.split()[2]) for line in listing.splitlines())
    out = subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "--batch"],
        input="".join(f"{blob}\n" for _, blob in entries).encode(),
        capture_output=True,
        check=True,
    ).stdout
    lines, at = [], 0
    for rel, _ in entries:
        header_end = out.index(b"\n", at)
        size = int(out[at:header_end].split()[2])
        content = out[header_end + 1:header_end + 1 + size]
        at = header_end + 1 + size + 1
        lines.append(f"{hashlib.sha256(content).hexdigest()}  {rel}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def library_version(root: Path = REPO) -> str:
    return re.search(r'^version = "([^"]+)"', (root / "Cargo.toml").read_text(), re.M).group(1)


def newer_sources(built: Path, root: Path = REPO) -> list[str]:
    """Library files modified after ``built`` was written; a module or binary older than one of them is stale."""
    stamp = Path(built).stat().st_mtime
    return [rel for rel in library_files(root) if (root / rel).stat().st_mtime > stamp]


def source_identity() -> dict:
    """The library digest, and the commit whose library files equal the working tree, if one does.

    That commit is the tag of the version in Cargo.toml when the tag holds these
    files, and otherwise HEAD when HEAD holds them; ``source_tag`` is None for
    HEAD.  Blob hashes of the working files are compared with the commit's tree,
    so the answer does not depend on what the index holds.  When neither holds
    them, tag and commit are None and the digest alone names the sources.
    """
    files = library_files()
    identity = {"library_digest": library_digest(), "source_files": len(files),
                "source_tag": None, "source_commit": None}
    hashed = None
    tag = f"v{library_version()}"
    for ref, name in ((f"{tag}^{{commit}}", tag), ("HEAD^{commit}", None)):
        commit = _git("rev-parse", "--verify", "-q", ref)
        listing = _git("ls-tree", "-r", commit, "--", *LIBRARY_PATHS) if commit else None
        if not listing:
            continue
        if hashed is None:
            hashed = dict(zip(files, subprocess.run(
                ["git", "-C", str(REPO), "hash-object", "--stdin-paths"],
                input="\n".join(files) + "\n",
                capture_output=True,
                text=True,
                check=False,
            ).stdout.split()))
        held = {}
        for line in listing.splitlines():
            meta, path = line.split("\t", 1)
            held[path] = meta.split()[2]
        if held == hashed:
            identity.update(source_tag=name, source_commit=commit)
            break
    return identity


def portable(path: Path) -> str:
    """A path that names no home directory: repository-relative or from site-packages on."""
    path = Path(path).resolve()
    if path.is_relative_to(REPO):
        return str(path.relative_to(REPO))
    if "site-packages" in path.parts:
        return str(Path(*path.parts[path.parts.index("site-packages"):]))
    return path.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _rustc_of(shared_object: Path) -> str | None:
    try:
        out = subprocess.run(
            ["readelf", "-p", ".comment", str(shared_object)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines():
        if "rustc version" in line:
            return line.split("rustc version", 1)[1].strip()
    return None


def readcon_module() -> Path | None:
    """The shared object of the imported readcon package."""
    import readcon

    package = Path(readcon.__file__).resolve().parent
    shared = sorted(package.glob("readcon*.so")) + sorted(package.glob("readcon*.pyd"))
    return shared[0] if shared else None


def readcon_build() -> dict:
    """Version, module path, module hash and compiler of the imported readcon, and the library sources.

    ``newer_sources`` lists the library files changed after the module was
    built; the library digest names the module's sources only when it is empty.
    """
    import readcon

    shared = readcon_module()
    record = {
        "readcon_version": readcon.__version__,
        "readcon_module": portable(shared if shared else Path(readcon.__file__).parent),
        "readcon_module_sha256": _sha256(shared) if shared else None,
        "rustc": _rustc_of(shared) if shared else None,
        "newer_sources": newer_sources(shared) if shared else None,
    }
    record.update(source_identity())
    return record


def binary_build(binary: Path) -> dict:
    """Hash and compiler of a native binary or library built from this tree, and the sources changed since."""
    return {
        "binary": portable(binary),
        "binary_sha256": _sha256(binary),
        "rustc": _rustc_of(binary),
        "newer_sources": newer_sources(binary),
        **source_identity(),
    }


def _command(*cmd: str) -> str | None:
    # nproc prints OMP_NUM_THREADS or OMP_THREAD_LIMIT when either is set, not the processing units.
    env = {key: value for key, value in os.environ.items() if not key.startswith("OMP_")}
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, env=env).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def hardware() -> dict:
    """The hardware line of a timing record: ``uname -m``, ``nproc`` and the CPU model as the host prints them."""
    nproc = _command("nproc")
    return {"uname_m": _command("uname", "-m"), "nproc": int(nproc) if nproc else None,
            "cpu_model": host().get("cpu_model")}


def hardware_tex(line: dict) -> str:
    """The hardware line in TeX: the CPU model as the host prints it, in typewriter type, then what ``uname -m``
    and ``nproc`` print."""
    def tex(text: str) -> str:
        return re.sub(r"([&%$#_{}])", r"\\\1", text)

    return f"\\texttt{{{tex(line['cpu_model'])}}}, {tex(line['uname_m'])}, {line['nproc']} processing units"


def normalize_cpu(raw: str) -> str:
    """Plain processor name written into every record.

    A Xeon model becomes ``Intel Xeon Processor``.
    """
    cleaned = " ".join(raw.replace("(R)", "").replace("(TM)", "").replace("®", "").split())
    if "Xeon" in cleaned:
        return "Intel Xeon Processor"
    return cleaned or "unknown"


def host() -> dict:
    info: dict = {"kernel": platform.release(), "uname_m": platform.machine(), "nproc": os.cpu_count()}
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        text = ""
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key == "model name" and "cpu_model" not in info:
            info["cpu_model"] = normalize_cpu(value.strip())
        elif key == "cpu family" and "family" not in info:
            info["family"] = value.strip()
        elif key == "model" and "model" not in info:
            info["model"] = value.strip()
        elif key == "cpu MHz" and "mhz" not in info:
            info["mhz"] = float(value)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                info["mem_kb"] = int(line.split()[1])
    except OSError:
        pass
    return info


def peers() -> dict:
    versions: dict = {}
    for name in ("ase", "chemfiles", "MDAnalysis", "h5py", "numpy", "scipy", "ovito", "openbabel"):
        try:
            module = __import__(name)
        except Exception:  # noqa: BLE001
            continue
        version = getattr(module, "__version__", None) or getattr(module, "version_string", None)
        versions[name] = str(version)
    versions["python"] = platform.python_version()
    return versions


def record() -> dict:
    return {"build": readcon_build(), "host": host(), "peers": peers()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--digest", nargs="?", const=str(REPO), metavar="ROOT",
                        help="print the library digest of ROOT (default: this tree) and exit")
    args = parser.parse_args()
    if args.digest:
        print(library_digest(Path(args.digest).resolve()))
    else:
        print(json.dumps(record(), indent=2))
