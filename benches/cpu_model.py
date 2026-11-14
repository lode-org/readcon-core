"""CPU model and platform label for bench provenance."""

from __future__ import annotations

import platform
from pathlib import Path


def normalize_cpu(raw: str) -> str:
    """The hardware string the records write.

    The kernel prints trademark marks. The records use one plain name.
    """
    cleaned = " ".join(
        raw.replace("(R)", "").replace("(TM)", "").replace("®", "").split()
    )
    if "Xeon" in cleaned:
        return "Intel Xeon Processor"
    return cleaned or "unknown"


def cpu_model() -> str:
    """Return the normalized model name from ``/proc/cpuinfo``, or ``unknown``."""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return normalize_cpu(value)
    except OSError:
        pass
    return "unknown"


def strip_host_token(label: str, node: str) -> str:
    """Drop dash-separated components that equal the machine name."""
    node = node.strip()
    if not node:
        return label
    return "-".join(part for part in label.split("-") if part != node)


def platform_label() -> str:
    """System, machine, and libc, without the kernel release.

    ``platform.platform()`` embeds ``uname -r``. A localversion on that
    release is machine-specific, so a rerun would record it again. A
    component equal to the machine name is still removed.
    """
    system = platform.system().strip() or "unknown"
    machine = platform.machine().strip() or "unknown"
    libc = ""
    full = platform.platform()
    marker = "-with-"
    if marker in full:
        libc = full.rsplit(marker, 1)[1]
    parts = [system, machine]
    if libc:
        parts.extend(["with", libc])
    return strip_host_token("-".join(parts), platform.node())
