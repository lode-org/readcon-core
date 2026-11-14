"""Verify the ELF identity used by consumers of the shared C ABI."""

import os
from pathlib import Path
import re
import subprocess
import sys


library = Path(sys.argv[1])
report = subprocess.check_output(
    ["readelf", "-d", str(library)], text=True, env={**os.environ, "LC_ALL": "C"}
)
names = re.findall(r"\(SONAME\).*?\[([^\]]+)\]", report)
if names != [library.name]:
    raise SystemExit(f"{library}: expected SONAME {library.name}, found {names}")
if "STATIC_TLS" in report:
    raise SystemExit(
        f"{library}: DF_STATIC_TLS is set; dlopen fails with "
        "'cannot allocate memory in static TLS block'. "
        "Build the cdylib with -Z tls-model=global-dynamic and "
        "CFLAGS=-ftls-model=global-dynamic (mimalloc)."
    )
print(f"{library.name}: SONAME verified, no DF_STATIC_TLS")
