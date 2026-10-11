#!/usr/bin/env bash
# README.md is handwritten. Check the GitHub render contract.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 - <<'PY'
from pathlib import Path
import re

text = Path("README.md").read_text(encoding="utf-8")
if "<table" in text.lower() or "<td" in text.lower():
    raise SystemExit("export-readme: README.md has a raw HTML table")
if "10.5281/zenodo.18753567" not in text:
    raise SystemExit("export-readme: README.md must state concept DOI 10.5281/zenodo.18753567")
bad = re.findall(r"docs/orgmode/[A-Za-z0-9_./-]+\.md", text)
if bad:
    raise SystemExit(f"export-readme: README.md links missing .md paths: {bad}")
print("export-readme: OK README.md")
PY
