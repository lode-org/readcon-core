"""Bootstrap for one-line cogapp markers. Run python -m cogapp from the repository root.

https://cog.readthedocs.io/en/latest/
"""

import sys
from pathlib import Path

_root = Path("scripts/cog_inline.py").resolve().parents[1]
sys.path.insert(0, str(_root / "scripts"))
from version_sot import (  # noqa: E402
    emit,
    emit_c_version,
    emit_changelog_links,
)

# cogapp execs this file. The names have to stay bound for the markers.
__all__ = ["emit", "emit_c_version", "emit_changelog_links"]
