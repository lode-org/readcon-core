"""Where this release's million-atom records live.

``bench/results/r0174/million`` is superseded. Readers use this directory.
"""

from __future__ import annotations

from pathlib import Path

BENCH = Path(__file__).resolve().parent
VERSION = "v0.23.3"
MILLION = BENCH / "results" / VERSION / "million"
HOLD = MILLION / "million_hold.json"
PEERS = MILLION / "peers_n1e6.json"
SUPERSEDED = BENCH / "results" / "r0174" / "million"
