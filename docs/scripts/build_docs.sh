#!/usr/bin/env bash
# Sphinx after org export and link rewrite. A docutils ERROR fails the job.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mkdir -p docs/build
sphinx-build -w docs/build/sphinx.log -b html docs/source docs/build
python3 docs/scripts/check_sphinx_log.py docs/build/sphinx.log
