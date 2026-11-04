"""Write the environment of the Python that runs this script to ``paper/cpc/environment``.

    python3 paper/cpc/scripts/export_env.py

``conda-linux-64.txt`` is the conda explicit list of the conda prefix of this
Python (its base prefix when it runs in a venv): the URL and MD5 of every
package of the prefix's ``conda-meta`` records, each after the packages it
depends on.  ``requirements.txt`` pins every other distribution on this
Python's path, the first of each name as the import system finds it, except
readcon, which ``pip install .`` builds from the checkout, and pip.
"""

from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "environment"
CONDA = Path(sys.base_prefix)
HEADER = "# Written by paper/cpc/scripts/export_env.py.\n"
SKIP = {"readcon", "pip"}


def canonical(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def conda_records() -> list[dict]:
    records = [json.loads(p.read_text()) for p in sorted((CONDA / "conda-meta").glob("*.json"))]
    if not records:
        raise SystemExit(f"{CONDA} holds no conda-meta records")
    return records


def explicit(records: list[dict]) -> str:
    platforms = {r["subdir"] for r in records} - {"noarch"}
    if len(platforms) != 1:
        raise SystemExit(f"conda-meta records of {sorted(platforms)}, not of one platform")
    by_name = {r["name"]: r for r in records}
    needs = {r["name"]: {d.split()[0] for d in r.get("depends", [])} & by_name.keys() for r in records}
    order: list[str] = []
    while needs:
        ready = sorted(name for name, deps in needs.items() if deps <= set(order))
        if not ready:
            raise SystemExit(f"conda packages that depend on each other: {sorted(needs)}")
        order += ready
        for name in ready:
            del needs[name]
    lines = [f"{by_name[name]['url']}#{by_name[name]['md5']}\n" for name in order]
    return f"{HEADER}# platform: {platforms.pop()}\n@EXPLICIT\n" + "".join(lines)


def pins(records: list[dict]) -> str:
    conda_files = {f for r in records for f in r.get("files", [])}
    found: dict[str, str] = {}
    for entry in sys.path:
        if not entry or not Path(entry).is_dir():
            continue
        for info in sorted(Path(entry).glob("*.dist-info")):
            dist = metadata.PathDistribution(info)
            name = dist.metadata["Name"]
            if canonical(name) in found or canonical(name) in SKIP:
                found.setdefault(canonical(name), "")
                continue
            if info.is_relative_to(CONDA) and f"{info.relative_to(CONDA)}/METADATA" in conda_files:
                found[canonical(name)] = ""
                continue
            found[canonical(name)] = f"{name}=={dist.version}\n"
    return HEADER + "".join(line for _, line in sorted(found.items()) if line)


def main() -> None:
    records = conda_records()
    ENV.mkdir(exist_ok=True)
    (ENV / "conda-linux-64.txt").write_text(explicit(records))
    (ENV / "requirements.txt").write_text(pins(records))
    print(f"wrote {ENV.relative_to(ROOT.parents[1])}: {len(records)} conda packages, "
          f"{(ENV / 'requirements.txt').read_text().count(chr(10)) - 1} pip pins")


if __name__ == "__main__":
    main()
