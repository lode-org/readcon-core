"""A measured version comes from that measurement's record.

``\\readconCargoVersion`` names this release. The 0.17.3 reader-exchange arm,
the drift wheels, and a release tag beside a commit do not borrow it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_from_log
import spec_version_drift

CPC = Path(__file__).resolve().parents[1]
SRC = CPC / "src"
RELEASE_0173 = "12ca800bc2212c565941e04094cba6b4d99a62e0"
VERSION = re.compile(r"\d+\.\d+\.\d+")
DOCS = ("rg_main.tex", "rg_supp.tex", "si_from_main.tex")


def _docs() -> str:
    return "\n".join((SRC / name).read_text(encoding="utf-8") for name in DOCS)


def test_release_arm_uses_the_log_tag() -> None:
    log = CPC / "logs" / "reader-exchange.log"
    text = log.read_text(encoding="utf-8")
    version = host_from_log.release_version(text)
    if version != "0.17.3":
        raise SystemExit(f"release_commit {RELEASE_0173} resolved to {version}")
    if host_from_log.LABELS["readcon_v0173"] != r"readcon-core \rcReleaseVersion{}":
        raise SystemExit(host_from_log.LABELS["readcon_v0173"])
    source = Path(host_from_log.__file__).read_text(encoding="utf-8")
    if "readconCargoVersion" in source:
        raise SystemExit("host_from_log.py still labels a measured arm with the cargo version")


def test_a_commit_without_a_tag_is_unknown() -> None:
    text = "release_commit 2e879613e1471297e49e8d0294246ed37ee6cacf\n"
    version = host_from_log.release_version(text)
    if version != "unknown":
        raise SystemExit(f"an untagged commit was named {version}")


def test_drift_wheels_come_from_the_record_or_are_unknown() -> None:
    if spec_version_drift.drift_versions() != []:
        raise SystemExit("version_drift.json is absent, so the wheels are unknown")
    text = spec_version_drift.drift_macros_text()
    for name in ("driftWheelOne", "driftWheelTwo", "driftWheelThree", "driftWheelFour", "driftWheels"):
        if f"\\newcommand{{\\{name}}}{{unknown}}" not in text:
            raise SystemExit(text)
    record = {
        "readers": ["0.17.0", "0.17.1", "0.17.2", "0.17.3"],
        "reported_versions": {
            "0.17.0": "0.17.0",
            "0.17.1": "0.17.1",
            "0.17.2": "0.17.2",
            "0.17.3": "0.17.3",
        },
    }
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "version_drift.json"
        target.write_text(json.dumps(record), encoding="utf-8")
        found = spec_version_drift.drift_versions(target)
    if found != ["0.17.0", "0.17.1", "0.17.2", "0.17.3"]:
        raise SystemExit(found)
    prose = _docs()
    for line in prose.splitlines():
        if "driftWheel" not in line and "wheel versions" not in line and "driftWheels" not in line:
            continue
        if VERSION.search(line):
            raise SystemExit(f"a drift sentence names a version beside the macro: {line}")


def test_cargo_version_is_not_a_measured_arm() -> None:
    for line in _docs().splitlines():
        if "readconCargoVersion" in line and (
            "rcReleaseMedian" in line or "rcTipMedian" in line
        ):
            raise SystemExit(line)
        lowered = line.lower()
        if "latest release tag" in lowered and (
            "12ca800b" in line or "readconCargoVersion" in line
        ):
            raise SystemExit(line)
        if "12ca800b" in line and "v0.23" in line:
            raise SystemExit(line)
    main = (SRC / "rg_main.tex").read_text(encoding="utf-8")
    if "v0.23.2" not in main or "8c2d9984" not in main:
        raise SystemExit("data availability no longer names v0.23.2 as 8c2d9984")
    rules = (CPC / "scripts" / "number_rules" / "versions.py").read_text(encoding="utf-8")
    if "_cargo_version" in rules:
        raise SystemExit("drift rules still take the cargo version")


def test_v0233_is_not_a_release() -> None:
    if "0.23.3" in _docs():
        raise SystemExit("the manuscript names v0.23.3, and that tag does not exist")


if __name__ == "__main__":
    test_release_arm_uses_the_log_tag()
    test_a_commit_without_a_tag_is_unknown()
    test_drift_wheels_come_from_the_record_or_are_unknown()
    test_cargo_version_is_not_a_measured_arm()
    test_v0233_is_not_a_release()
    print("measured versions ok")
