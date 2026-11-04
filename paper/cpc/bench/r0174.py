"""Provenance of the readcon-core 0.17.4 measurements: commit, library digest, module, host, tools.

The measured library is the tree of the commit that ``provenance.source_identity``
finds: tag v0.17.4 once it holds these library files, and until then the
release candidate at HEAD, which descends from commit ``BASE``, the head of
pull request 80 to the main branch after the published release 0.17.3, and
adds the version bump and the changes that CHANGELOG.md lists under 0.17.4.
``build()`` records that commit, the number of commits after ``BASE``, the
library digest of the working tree and of the commit's git objects, which must
agree, and the imported module, which must be newer than every library file.
``record()`` adds the host, its hardware line (``provenance.hardware``), the
peers and the tools.

    python bench/r0174.py     # write BENCH_RESULTS/provenance.json
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import portable  # noqa: E402
import provenance  # noqa: E402

BASE = "d0b7d3c7a5a7e7d7a6a963d515e9524c575c09fd"
RESULTS = Path(os.environ.get("BENCH_RESULTS", HERE / "results" / "r0174"))


def _out(*cmd: str) -> str | None:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git(*args: str) -> str | None:
    return _out("git", "-C", str(provenance.REPO), *args)


def tools() -> dict:
    versions = {"python": platform.python_version()}
    for name in ("memray",):
        try:
            versions[name] = __import__(name).__version__
        except Exception:  # noqa: BLE001
            versions[name] = None
    versions["valgrind"] = _out("valgrind", "--version")
    versions["rustc"] = _out("rustc", "--version")
    return versions


def host() -> dict:
    info = provenance.host()
    for line in (_out("lscpu") or "").splitlines():
        key, _, value = line.partition(":")
        if key.strip() in ("Hypervisor vendor", "Stepping", "Thread(s) per core", "L2 cache", "L3 cache"):
            info[key.strip().lower().replace(" ", "_").replace("(s)", "s")] = value.strip()
    os_release = Path("/etc/os-release")
    if os_release.exists():
        for line in os_release.read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                info["os"] = line.split("=", 1)[1].strip('"')
    return info


def build() -> dict:
    identity = provenance.source_identity()
    commit = identity["source_commit"]
    if commit is None:
        raise SystemExit("no tag or HEAD holds this tree's library files; the measurements need a commit")
    if _git("merge-base", "--is-ancestor", BASE, commit) is None:
        raise SystemExit(f"commit {commit[:12]} does not descend from {BASE[:12]}")
    at_commit = provenance.library_digest_at(commit)
    if at_commit != identity["library_digest"]:
        raise SystemExit(f"commit {commit[:12]} holds library {at_commit}, the tree {identity['library_digest']}")
    record = {
        "release": provenance.library_version(),
        "commit": commit,
        "tag": identity["source_tag"],
        "base": BASE,
        "commits_after_base": int(_git("rev-list", "--count", f"{BASE}..{commit}")),
        "library_digest": identity["library_digest"],
        "library_digest_of_source": identity["library_digest"],
        "library_digest_at_commit": at_commit,
        "source_files": identity["source_files"],
    }
    record.update({key: value for key, value in provenance.readcon_build().items()
                   if key in ("readcon_version", "readcon_module", "readcon_module_sha256", "rustc", "newer_sources")})
    if record["newer_sources"]:
        raise SystemExit(f"the readcon module is older than {record['newer_sources'][:5]}; rebuild it (cpc-readcon)")
    return record


def record() -> dict:
    return {"build": build(), "host": host(), "hardware": provenance.hardware(), "peers": provenance.peers(),
            "tools": tools()}


if __name__ == "__main__":
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "provenance.json").write_text(json.dumps(portable.portable(record()), indent=2) + "\n")
    print("wrote", RESULTS / "provenance.json")
