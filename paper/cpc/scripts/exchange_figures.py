#!/usr/bin/env python3
"""Draw the reader-exchange figures and write their caption macros.

perf19 writes ``logs/reader-exchange.json``. Until that file is present, the
numbers come from ``logs/reader-exchange.log``, whose release is 0.17.3.
The JSON record needs ``version``, ``host``, ``n``, ``frames``, ``atoms``
and either ``rss_mib`` or ``arms.readcon_tip.mib_median``. Each arm needs
``samples_s``. ``cpus`` is the host CPU count.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plot_union_extra as figures  # noqa: E402


def main() -> int:
    figures.reader_figures()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
