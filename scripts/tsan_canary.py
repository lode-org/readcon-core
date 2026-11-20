"""Call the extension's canary race.

The stress script runs this before the real stress. The extension is
built with the canary only for that sanitizer build. A runtime that is
watching the extension reports a data race in ``rkr_tsan_canary_race``.
"""

import ctypes
import glob
import os
import sys

import readcon

root = os.path.dirname(readcon.__file__)
matches = glob.glob(os.path.join(root, "*.so"))
if len(matches) != 1:
    raise SystemExit(f"expected one extension, found {matches}")
lib = ctypes.CDLL(matches[0])
fn = getattr(lib, "rkr_tsan_canary_launch", None)
if fn is None:
    raise SystemExit("rkr_tsan_canary_launch is not exported")
sys.stdout.flush()
sys.stderr.flush()
fn()
