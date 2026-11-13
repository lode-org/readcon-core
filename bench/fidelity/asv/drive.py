"""Entry point for the fidelity Snakemake rule.

The rule pins the process to one core. ``all`` writes the fidelity table and
the timing table. ``read-once`` and ``write-once`` are the calls the asv
classes time.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import campaign


def main() -> None:
    campaign.main(sys.argv[1:])


if __name__ == "__main__":
    main()
