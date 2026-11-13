#!/usr/bin/env python3
"""Rerun the paper's reader-exchange campaign on this commit.

The workload is the one in ``paper/cpc/scripts/bench_readers.py``: one
trajectory of 32 copper atoms, fresh process per sample, VmHWM after the
read minus VmHWM after the import. The paper's log used 100000 frames
and six repeats. This run is serial and pinned to the process affinity
set, with one untimed round and then the timed rounds. The raw log keeps
every sample. ``reader-exchange.json`` is what
``paper/cpc/scripts/plot_union_extra.py`` reads for the timing, ratio and
memory figures.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from campaign_protocol import head_sha, stamp_file
from sample_protocol import core_list, pin_cores

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "paper" / "cpc" / "scripts"))
import bench_readers as br  # noqa: E402

WORK = ROOT / "bench" / "h2h" / "work" / "reader-exchange"


def _type7(values: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray(values, dtype=float)
    q1, med, q3 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(med), float(q3 - q1), float(q1), float(q3)


def ensure_pinned(commit: str, dest: Path) -> str | None:
    """Install ``commit`` so ``import readcon`` from ``dest`` is that tree.

    A missing directory must not fall through to the ambient wheel: that
    would time this commit twice and label one copy as 0.17.3.
    """
    marker = dest / ".pinned-commit"
    if (
        marker.is_file()
        and marker.read_text().strip() == commit
        and (dest / "readcon").is_dir()
    ):
        return None
    if dest.exists():
        shutil.rmtree(dest)
    checkout = Path(f"/tmp/readcon-pin-{commit[:12]}")
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(checkout)],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(checkout), commit],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(dest),
                str(checkout),
            ],
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(checkout)],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout)[-400:].replace("\n", " ")
        return f"pinned build {commit[:12]} failed: {tail}"
    marker.write_text(commit + "\n")
    return None


def _pin_subprocess() -> None:
    """The reader script starts one interpreter. Pin that process."""
    cores = core_list()
    real = br.subprocess.run

    def pinned(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and argv and argv[0] == sys.executable:
            argv = ["taskset", "-c", cores, *argv]
        return real(argv, *args, **kwargs)

    br.subprocess.run = pinned


def run(out: Path, frames: int, repeats: int) -> None:
    if frames < 1 or repeats < 1:
        raise SystemExit("frames and repeats must be positive")
    pin_cores()
    _pin_subprocess()
    br.N_FRAMES = frames
    br.REPEATS = repeats
    br.WORK = WORK
    sha = head_sha()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--short"], cwd=ROOT, text=True
    ).strip()
    lines = [
        f"commit {sha}",
        f"rev_parse {sha}",
        f"tree {tree}",
        f"frames {frames}",
        f"atoms {br.N_ATOMS}",
        f"repeats {repeats}",
        "warmup 1",
        "schedule interleaved",
        "process fresh",
        f"affinity taskset -c {core_list()}",
        "serial 1",
        "memory VmHWM_after_read_minus_VmHWM_after_import_MiB",
        "numpy_percentile method=linear type=7",
        "git_status_begin",
        status or "(clean)",
        "git_status_end",
    ]
    pin_errors = {
        "readcon_base": ensure_pinned(br.BASE_COMMIT, br.BASE_DIR),
        "readcon_v0173": ensure_pinned(br.RELEASE_COMMIT, br.RELEASE_DIR),
    }
    for name, err in pin_errors.items():
        if err:
            lines.append(f"note {name} {err}")
    frames_arr = br.reference(frames, br.N_ATOMS)
    br.write_files(frames_arr)
    con = WORK / "frames.con"
    xyz = WORK / "frames.xyz"
    h5 = WORK / "frames.h5md"
    arms = [
        ("readcon_tip", con),
        ("readcon_base", con),
        ("readcon_v0173", con),
        ("readcon_first", con),
        ("readcon_db", con),
        ("ase_eon", con),
        ("eon", con),
        ("eon_py", con),
        ("readcon_eon_api", con),
        ("conbin", WORK / "frames.conbin"),
        ("numpy", xyz),
        ("chemfiles", xyz),
        ("ovito", xyz),
        ("ase_extxyz", xyz),
        ("pymatgen", xyz),
        ("h5py", h5),
        ("mdanalysis", h5),
    ]
    names = [name for name, _ in arms]
    paths = dict(arms)
    lines.append("warmup round")
    for name in names:
        if pin_errors.get(name):
            doc = {
                "error": pin_errors[name],
                "seconds": None,
                "mib": None,
                "exit": 1,
            }
        else:
            doc = br.one(name, paths[name])
        lines.append(
            f"warmup arm={name} seconds={doc.get('seconds')} mib={doc.get('mib')} "
            f"exit={doc.get('exit')} error={doc.get('error', '')}"
        )
    samples: dict[str, list[dict]] = {name: [] for name in names}
    for rep in range(repeats):
        order = names[rep % len(names) :] + names[: rep % len(names)]
        lines.append("order " + " ".join(order))
        for name in order:
            if pin_errors.get(name):
                doc = {
                    "error": pin_errors[name],
                    "seconds": None,
                    "matched": 0,
                    "got": 0,
                    "requested": frames,
                    "mib": None,
                    "exit": 1,
                }
            else:
                doc = br.one(name, paths[name])
            samples[name].append(doc)
            lines.append(
                f"sample arm={name} rep={rep} seconds={doc.get('seconds')} "
                f"mib={doc.get('mib')} matched={doc.get('matched')} got={doc.get('got')} "
                f"requested={doc.get('requested')} exit={doc.get('exit')} "
                f"error={doc.get('error', '')}"
            )
    payload_arms: dict[str, dict] = {}
    for name in names:
        got = [
            row
            for row in samples[name]
            if row.get("seconds") is not None and not row.get("error")
        ]
        if len(got) < repeats:
            err = next(
                (row.get("error") for row in samples[name] if row.get("error")),
                "short",
            )
            lines.append(f"summary arm={name} error={err} exit=1")
            payload_arms[name] = {
                "seconds": [row.get("seconds") for row in samples[name]],
                "mib": [row.get("mib") for row in samples[name]],
                "error": err,
            }
            continue
        med, iqr, q1, q3 = _type7([row["seconds"] for row in got])
        mib, mib_iqr, mib_q1, mib_q3 = _type7([row["mib"] for row in got])
        matched = min(row["matched"] for row in got)
        requested = got[0]["requested"]
        scope = "first_frame" if name in {"eon", "readcon_first"} else "all_frames"
        if name == "readcon_eon_api":
            scope = "readcon_through_eon"
        lines.append(
            f"summary arm={name} scope={scope} n_rep={len(got)} median_s={med:.9e} "
            f"iqr_s={iqr:.9e} mib_median={mib:.6f} mib_iqr={mib_iqr:.6f} "
            f"requested={requested} matched={matched} failed={requested - matched} exit=0"
        )
        payload_arms[name] = {
            "scope": scope,
            "seconds": [row["seconds"] for row in got],
            "mib": [row["mib"] for row in got],
            "median_s": med,
            "iqr_s": iqr,
            "q1_s": q1,
            "q3_s": q3,
            "mib_median": mib,
            "mib_iqr": mib_iqr,
            "mib_q1": mib_q1,
            "mib_q3": mib_q3,
            "requested": requested,
            "matched": matched,
        }
    tip = payload_arms.get("readcon_tip", {})
    if tip.get("error") or len(tip.get("seconds") or []) < repeats:
        raise SystemExit(
            "readcon_tip did not complete: "
            + str(tip.get("error") or "too few samples")
        )
    lines.append("exit_code 0")
    out.mkdir(parents=True, exist_ok=True)
    log = out / "reader-exchange.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "frames": frames,
        "atoms": br.N_ATOMS,
        "repeats": repeats,
        "warmup": 1,
        "serial": True,
        "pinned": f"taskset -c {core_list()}",
        "percentile": "numpy linear (type-7)",
        "memory": "VmHWM after the read minus VmHWM after the import, MiB",
        "arms": payload_arms,
    }
    path = out / "reader-exchange.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    stamp_file(path, sha, repeats, None)
    stamp_file(log, sha, repeats, None)
    print(f"readcon_tip {tip['median_s']:.6f}s rss {tip['mib_median']:.3f} MiB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    run(args.out, args.frames, args.repeats)


if __name__ == "__main__":
    main()
