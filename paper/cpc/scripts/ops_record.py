#!/usr/bin/env python3
"""Record the readcon-ops version named by its pyproject on the default branch.

The package is not in this repository. The script reads the pyproject and
the public names from GitHub and writes the log the program summary uses.

    python3 paper/cpc/scripts/ops_record.py
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "paper" / "cpc" / "logs" / "readcon-ops.json"
MACROS = ROOT / "paper" / "cpc" / "src" / "figures" / "generated" / "ops_macros.tex"
PYPROJECT = "https://raw.githubusercontent.com/lode-org/readcon-ops/master/pyproject.toml"
INIT = "https://raw.githubusercontent.com/lode-org/readcon-ops/master/src/readcon_ops/__init__.py"
NAMED = ("identical", "internal_motion", "rotational_match", "wulff_vertices")


def fetch(url: str) -> str:
    with urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def field(text: str, key: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(key):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{key} is not in the readcon-ops pyproject")


def main() -> None:
    project = fetch(PYPROJECT)
    public = fetch(INIT)
    version = field(project, "version")
    license_text = "BSD-3-Clause"
    if 'license = {text = "BSD-3-Clause"}' not in project:
        raise SystemExit("readcon-ops is not BSD-3-Clause")
    requires = field(project, "requires-python")
    if not requires.startswith(">="):
        raise SystemExit(f"unexpected requires-python {requires}")
    names = [name for name in NAMED if name not in public]
    if names:
        raise SystemExit(f"readcon-ops no longer exports {names}")
    if "[project.scripts]" in project:
        raise SystemExit("readcon-ops gained a command line")
    record = {
        "url": "https://github.com/lode-org/readcon-ops",
        "pyproject": PYPROJECT,
        "version": version,
        "license": "BSD 3-clause",
        "license_identifier": license_text,
        "requires_python": requires.removeprefix(">=").strip(),
        "exports": list(NAMED),
        "command_line": False,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    lines = [
        "% Written by paper/cpc/scripts/ops_record.py from paper/cpc/logs/readcon-ops.json.",
        f"\\newcommand{{\\opsVersion}}{{{record['version']}}}",
        f"\\newcommand{{\\opsLicense}}{{{record['license']}}}",
        f"\\newcommand{{\\opsPy}}{{{record['requires_python']}}}",
        "",
    ]
    MACROS.parent.mkdir(parents=True, exist_ok=True)
    MACROS.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
