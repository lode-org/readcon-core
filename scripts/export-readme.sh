#!/usr/bin/env bash
# Export readme_src.org -> README.md and keep docs/orgmode/*.org hrefs as .org.
# ox-md rewrites file:…org links to .md; GitHub has only the .org sources.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

emacs --batch \
  --eval "(progn (require 'package) (package-initialize) (require 'ox-md) \
                  (find-file \"readme_src.org\") \
                  (org-export-to-file 'md \"README.md\"))"

python3 - <<'PY'
from pathlib import Path
import re
p = Path("README.md")
text = p.read_text()
# ox-md turns file:docs/orgmode/foo.org into (docs/orgmode/foo.md)
fixed = re.sub(
    r"(\]\()?docs/orgmode/([A-Za-z0-9_./-]+)\.md(\))?",
    lambda m: (
        (m.group(1) or "")
        + f"docs/orgmode/{m.group(2)}.org"
        + (m.group(3) or "")
    ),
    text,
)
if fixed != text:
    p.write_text(fixed)
    print("export-readme: rewrote docs/orgmode/*.md hrefs to .org")
else:
    print("export-readme: no .md orgmode hrefs to rewrite")
# Fail if any remain
bad = re.findall(r"docs/orgmode/[A-Za-z0-9_./-]+\.md", p.read_text())
if bad:
    raise SystemExit(f"export-readme: still have .md orgmode links: {bad}")
print("export-readme: OK README.md")
PY
