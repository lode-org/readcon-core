#!/usr/bin/env python3
"""Regenerate the restored figures in the Ruhi palette.

The five colours are the Ruhi palette from chemparseplot
(coral, sunshine, teal, sky, magenta).
Each PDF is written from a committed record.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "src" / "figures" / "generated"
DATA = ROOT / "data"
LIMITER = DATA / "limiter-r15"
FONT = ROOT / "fonts" / "latin-modern" / "lmroman10-regular.otf"

CORAL = "#FF655D"
SUNSHINE = "#F1DB4B"
TEAL = "#004D40"
SKY = "#1E88E5"
MAGENTA = "#D81B60"
BLACK = "#000000"
CYCLE = (TEAL, SKY, CORAL, MAGENTA, SUNSHINE)
SEQ = LinearSegmentedColormap.from_list("ruhi_seq", [TEAL, SKY, SUNSHINE])


def face() -> None:
    fm.fontManager.addfont(str(FONT))
    name = fm.FontProperties(fname=str(FONT)).get_name()
    plt.rcParams.update(
        {
            "font.family": name,
            "font.size": 8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.edgecolor": BLACK,
            "axes.labelcolor": BLACK,
            "xtick.color": BLACK,
            "ytick.color": BLACK,
            "text.color": BLACK,
        }
    )


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def bars(name: str, labels, values, ylabel: str, colors=None) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    colors = colors or [CYCLE[i % len(CYCLE)] for i in range(len(labels))]
    ax.bar(range(len(labels)), values, color=colors, edgecolor=BLACK, linewidth=0.4)
    ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    ax.set_ylabel(ylabel)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, name)


def dlpack() -> None:
    """Median of the recorded repeats of each arm, with the type 7 interquartile range."""
    view, copy = [], []
    record = Path(os.environ.get("DLPACK_COST_RECORD", str(DATA / "dlpack_cost.txt")))
    for line in record.read_text().splitlines():
        if line.startswith("repeat "):
            parts = line.split()
            view.append(int(parts[3]) / 1e3)
            copy.append(int(parts[5]) / 1e3)
    if not view or len(view) != len(copy):
        raise SystemExit(f"{record}: no repeats, or unequal view and copy repeats")
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    for x, values, color, label in (
        (0, view, TEAL, "DLPack view"),
        (1, copy, CORAL, "explicit copy"),
    ):
        low, median, high = np.percentile(values, [25, 50, 75], method="linear")
        ax.bar(
            x,
            median,
            width=0.5,
            color=color,
            edgecolor=BLACK,
            linewidth=0.4,
            label=label,
            yerr=[[median - low], [high - median]],
            error_kw={"ecolor": BLACK, "capsize": 4, "linewidth": 0.8},
        )
    ax.set_xticks([0, 1], ["DLPack view", "explicit copy"])
    ax.set_ylabel(f"time (microseconds), median of {len(view)} repeats")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "dlpack")


def toc() -> None:
    """Schematic graphical abstract. The words are readcon and competitors. No digits."""
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    fig, ax = plt.subplots(figsize=(5.6, 3.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fields = ("mask", "identifier", "time unit", "coordinates")
    for index, label in enumerate(fields):
        y = 0.78 - index * 0.22
        ax.add_patch(
            FancyBboxPatch(
                (0.02, y),
                0.26,
                0.16,
                boxstyle="round,pad=0.01,rounding_size=0.02",
                facecolor="white",
                edgecolor=BLACK,
                linewidth=0.6,
            )
        )
        ax.text(
            0.15,
            y + 0.08,
            label,
            ha="center",
            va="center",
            color=BLACK,
            fontsize=7,
        )
        ax.add_patch(
            FancyArrowPatch(
                (0.29, y + 0.08),
                (0.36, 0.50),
                arrowstyle="-|>",
                mutation_scale=8,
                color=BLACK,
                linewidth=0.5,
            )
        )
    for origin, label, width in (
        (0.38, "readcon", 0.24),
        (0.72, "competitors", 0.26),
    ):
        ax.add_patch(
            FancyBboxPatch(
                (origin, 0.28),
                width,
                0.44,
                boxstyle="round,pad=0.02,rounding_size=0.04",
                facecolor=TEAL if label == "readcon" else CORAL,
                edgecolor=BLACK,
                linewidth=0.8,
            )
        )
        ax.text(
            origin + width / 2,
            0.50,
            label,
            ha="center",
            va="center",
            color="white",
            fontsize=11,
        )
    ax.add_patch(
        FancyArrowPatch(
            (0.64, 0.50),
            (0.70, 0.50),
            arrowstyle="-|>",
            mutation_scale=14,
            color=BLACK,
            linewidth=0.8,
        )
    )
    save(fig, "toc")


def _reads_path() -> Path:
    """The reads record this build plots. A missing file stops the build."""
    path = (
        Path(os.environ["READS_JSON"])
        if os.environ.get("READS_JSON")
        else ROOT / "bench" / "results" / "r0174" / "reads.json"
    )
    if not path.is_file():
        raise SystemExit(f"{path} is absent; this build has no other reads record")
    return path


def timing_and_fairness() -> None:
    cells = json.loads(_reads_path().read_text())["cells"]

    def cell_of(reader: str, threads: int = 1) -> dict:
        key = f"python:{reader}:{threads}"
        if key not in cells:
            raise SystemExit(f"{_reads_path()}: no cell {key}")
        return cells[key]

    def med(reader: str, threads: int = 1) -> float:
        return cell_of(reader, threads)["median_s"]

    labels = [
        "readcon",
        "ASE XYZ",
        "extxyz C",
        "OVITO",
        "ASE traj",
        "h5py",
        "MDAnalysis",
    ]
    keys = [
        "readcon",
        "ase_extxyz",
        "extxyz_c",
        "ovito",
        "ase_traj",
        "h5py",
        "mda_h5md",
    ]
    ratios = [med("readcon") / med(key) for key in keys[1:]]
    bars("fairness_ratios", labels[1:], ratios, "readcon median / peer median")
    rate_labels = [
        "full, 1",
        "full, 8",
        "fields, 1",
        "fields, 8",
        "coords, 1",
        "coords, 8",
    ]
    rate_cells = [
        cell_of(reader, threads)
        for reader in ("readcon", "readcon_fields", "readcon_coords")
        for threads in (1, 8)
    ]
    counts = {cell["printed"]["frames"] for cell in rate_cells}
    if len(counts) != 1:
        raise SystemExit(
            f"{_reads_path()}: the rate cells read {sorted(counts)} frames"
        )
    frames = counts.pop()
    rates = [frames / cell["median_s"] for cell in rate_cells]
    bars("layers", rate_labels, rates, "frames per second")
    bars("roofline", rate_labels, rates, "frames per second")


MPI_STRONG_SERIES = (
    ("read", "con-100k-disk"),
    ("read", "con-1e6-disk"),
    ("read", "convel-disk"),
    ("write", "con-100k-disk"),
    ("write", "con-1e6-disk"),
)


def mpi_strong() -> None:
    """Speedup against one rank for the named series of ``data/mpi/strong.csv``.

    The record holds more series than the palette has colours. Five of the
    sixteen series are named here. A named series that the record lacks is
    an error.
    """
    rows = list(csv.DictReader((DATA / "mpi" / "strong.csv").open()))
    series: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for row in rows:
        if row["system"] != "readcon-core":
            continue
        series.setdefault((row["operation"], row["mode"]), []).append(
            (int(row["ranks"]), float(row["seconds"]))
        )
    missing = [key for key in MPI_STRONG_SERIES if key not in series]
    if missing:
        raise SystemExit(f"data/mpi/strong.csv has no series {missing}")
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    for key, color in zip(MPI_STRONG_SERIES, CYCLE):
        points = sorted(series[key])
        ranks, seconds = zip(*points)
        if ranks[0] != 1:
            raise SystemExit(f"data/mpi/strong.csv series {key} has no one-rank row")
        base = seconds[0]
        ax.plot(
            ranks,
            [base / s for s in seconds],
            marker="o",
            color=color,
            label=" ".join(key),
        )
    ax.plot([1, 8], [1, 8], color=BLACK, linewidth=0.6, linestyle="--")
    ax.set_xlabel("ranks")
    ax.set_ylabel("speedup against one rank")
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "mpi_strong")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _type7(values: list[float], probability: float) -> float:
    """Hyndman-Fan type 7 quantile."""
    ordered = sorted(values)
    if not ordered:
        raise SystemExit("a weak-scaling point has no samples")
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    fraction = index - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def _limiter_record() -> dict:
    """The limiter-r15 read ladder. A missing or altered file stops the build."""
    prov_path = LIMITER / "provenance.json"
    if not prov_path.is_file():
        raise SystemExit(
            f"{prov_path} is absent; the weak-scaling figure has no other record"
        )
    provenance = json.loads(prov_path.read_text())
    files = provenance.get("files") or {}
    loaded = {}
    for name, digest in files.items():
        path = LIMITER / name
        if not path.is_file():
            raise SystemExit(
                f"{path} is absent; the weak-scaling figure has no other record"
            )
        found = _sha256(path)
        if found != digest:
            raise SystemExit(f"{path} sha256 {found} is not {digest}")
        loaded[name] = path
    if "limiter-r15.json" not in loaded or "measure.txt" not in loaded:
        raise SystemExit(f"{prov_path} does not name the limiter-r15 read files")
    return {
        "provenance": provenance,
        "after": json.loads(loaded["limiter-r15.json"].read_text()),
        "measure": loaded["measure.txt"].read_text(),
    }


def _before_samples(measure: str) -> dict[str, dict[int, list[float]]]:
    """Raw samples from the public-main arm of the campaign log."""
    head = measure.split("AFTER_BEGIN", 1)[0]
    patterns = {
        "touch": re.compile(r"before touch workers=(\d+) sample_s=([0-9.]+)"),
        "open-only": re.compile(r"before open-only workers=(\d+) sample_s=([0-9.]+)"),
        "ranks": re.compile(r"before ranks=(\d+) sample_s=([0-9.]+)"),
    }
    found = {name: {} for name in patterns}
    for line in head.splitlines():
        if "summary" in line or "meminfo" in line:
            continue
        for name, pattern in patterns.items():
            match = pattern.search(line)
            if match:
                found[name].setdefault(int(match.group(1)), []).append(
                    float(match.group(2))
                )
    return found


def _after_samples(record: dict) -> dict[str, dict[int, list[float]]]:
    """Raw samples from the tip arm. The JSON holds that arm only."""
    for key, label in (
        ("touch", "touch"),
        ("open_only", "open-only"),
        ("ranks", "ranks"),
    ):
        if key not in record:
            raise SystemExit(f"the limiter-r15 record has no {label} samples")
    found = {}
    for name, block in (("touch", record["touch"]), ("open-only", record["open_only"])):
        found[name] = {
            int(point["workers"]): [float(sample) for sample in point["samples_s"]]
            for point in block["points"]
        }
    found["ranks"] = {
        int(point["ranks"]): [float(sample) for sample in point["samples_s"]]
        for point in record["ranks"]
    }
    return found


def _ladder(
    samples: dict[int, list[float]], workers: list[int]
) -> list[tuple[int, float, float, float]]:
    points = []
    for worker in workers:
        values = samples.get(worker) or []
        if len(values) != 6:
            raise SystemExit(f"worker {worker} has {len(values)} samples, not 6")
        median = _type7(values, 0.5)
        low = _type7(values, 0.25)
        high = _type7(values, 0.75)
        points.append((worker, median, median - low, high - median))
    return points


def weak_figure() -> None:
    """Plot the limiter-r15 read ladder. A missing record stops the build."""
    record = _limiter_record()
    workers = [int(worker) for worker in record["provenance"]["workers"]]
    after = _after_samples(record["after"])
    before = _before_samples(record["measure"])
    if "touch" not in after or not after["touch"]:
        raise SystemExit("the limiter-r15 record has no touch samples")
    if "open-only" not in after or not after["open-only"]:
        raise SystemExit("the limiter-r15 record has no open-only samples")
    series = []
    for name, color in (("touch", TEAL), ("open-only", CORAL), ("ranks", SKY)):
        series.append((f"{name}, tip", color, "-", _ladder(after[name], workers)))
        main = before.get(name) or {}
        if name == "ranks" and not main:
            continue
        if not main:
            raise SystemExit(f"the campaign log has no {name} samples before the tip")
        series.append((f"{name}, main", color, "--", _ladder(main, workers)))
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    for label, color, style, points in series:
        ax.errorbar(
            [point[0] for point in points],
            [point[1] for point in points],
            yerr=[[point[2] for point in points], [point[3] for point in points]],
            marker="o",
            color=color,
            linestyle=style,
            linewidth=1.4,
            capsize=2,
            label=label,
        )
    ax.set_xlabel("width")
    ax.set_ylabel("seconds")
    ax.set_xticks(workers)
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "mpi_weak")


DB_FRAMES = "1000"


def _db_rows(rows, name: str, label, **where) -> list[dict[str, str]]:
    """The rows of one store size that match ``where``, one for each label."""
    found = [
        row for row in rows if all(row[key] == want for key, want in where.items())
    ]
    if not found:
        raise SystemExit(f"{name}: no row matches {where}")
    labels = [label(row) for row in found]
    if len(set(labels)) != len(labels):
        raise SystemExit(f"{name}: {where} leaves repeated labels {labels}")
    return found


def db_plots() -> None:
    summary = list(csv.DictReader((DATA / "db" / "summary.csv").open()))
    ingest = _db_rows(
        summary,
        "db_ingest_throughput",
        lambda row: row["system"],
        kind="frames_per_s",
        n_frames=DB_FRAMES,
    )
    bars(
        "db_ingest_throughput",
        [row["system"] for row in ingest],
        [float(row["median"]) for row in ingest],
        "median frames per second",
    )
    bandwidth = _db_rows(
        summary,
        "db_ingest_bandwidth",
        lambda row: row["system"],
        kind="mb_per_s",
        n_frames=DB_FRAMES,
    )
    bars(
        "db_ingest_bandwidth",
        [row["system"] for row in bandwidth],
        [float(row["median"]) for row in bandwidth],
        "median MB/s",
    )
    queries = _db_rows(
        summary,
        "db_query_latency",
        lambda row: f"{row['system']} {row['cache']}",
        kind="query_s",
        query="composition",
        n_frames=DB_FRAMES,
    )
    bars(
        "db_query_latency",
        [f"{row['system']} {row['cache']}" for row in queries],
        [float(row["median"]) for row in queries],
        "median seconds",
    )
    sizes = _db_rows(
        list(csv.DictReader((DATA / "db" / "sizes.csv").open())),
        "db_disk_footprint",
        lambda row: row["store"],
        n_frames=DB_FRAMES,
    )
    bars(
        "db_disk_footprint",
        [row["store"] for row in sizes],
        [float(row["allocated_bytes"]) / 1e6 for row in sizes],
        "allocated MB",
    )
    dedup = json.loads((DATA / "db" / "dedup.json").read_text())
    bars(
        "db_dedup",
        ["stored", "unique"],
        [float(dedup["n_frames"]), float(dedup["n_unique_hashes"])],
        "frames",
    )


def anatomy_and_errors() -> None:
    anatomy = json.loads((DATA / "novel" / "anatomy.json").read_text())["bytes"]
    bars("frame_anatomy", list(anatomy), [anatomy[key] for key in anatomy], "bytes")
    errors = json.loads((DATA / "novel" / "errors.json").read_text())["cases"]
    labels = [row["id"] for row in errors]
    bars("error_classes", labels, [1] * len(labels), "illegal file")
    fidelity = json.loads((DATA / "novel" / "fidelity.json").read_text())["rows"]
    score = []
    for row in fidelity:
        score.append(
            sum(row[key] == "exact" for key in ("mask", "id", "time_unit", "binary64"))
        )
    bars(
        "roundtrip_fidelity",
        [row["format"] for row in fidelity],
        score,
        "exact fields out of four",
    )
    diff = json.loads((DATA / "novel" / "restart_diff.json").read_text())
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    for (name, block), color in zip(diff.items(), CYCLE):
        if "mic_max_abs_A" not in block:
            continue
        column = [max(row) for row in block["mic_max_abs_A"]]
        ax.plot(
            range(len(column)),
            column,
            marker="o",
            color=color,
            label=name.replace("_", " "),
        )
    ax.set_xlabel("image")
    ax.set_ylabel("max component (angstrom)")
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "restart_diff")
    graph = json.loads((DATA / "novel" / "dedup_graph.json").read_text())
    runs = graph["runs"]
    counts = {run: 0 for run in runs}
    for edge in graph["edges"]:
        counts[edge["run"]] = counts.get(edge["run"], 0) + 1
    bars("dedup_graph", list(counts), list(counts.values()), "hashed images")


def band_energy(path: Path) -> np.ndarray:
    return np.load(path)["energies"]


def landscapes() -> None:
    bands = DATA / "failure" / "bands"
    pairs = [
        ("uninterrupted", bands / "uninterrupted.npz"),
        ("shortest", bands / "CON_3_1__shortest_round_trip.npz"),
        ("six decimals", bands / "CON_3_1__six_decimals.npz"),
        ("extended XYZ", bands / "extended_XYZ__ASE.npz"),
        ("ASE trajectory", bands / "ASE_trajectory__ids_in_tags.npz"),
    ]
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    for (label, path), color in zip(pairs, CYCLE):
        energy = band_energy(path)
        ax.plot(
            range(len(energy)), energy - energy[0], marker="o", color=color, label=label
        )
    ax.set_xlabel("image")
    ax.set_ylabel("energy above the first image (eV)")
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "neb_multiples")
    mask_pairs = [
        ("held", bands / "POSCAR__ASE___FixScaled_z.npz"),
        ("free", bands / "uninterrupted.npz"),
    ]
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    for (label, path), color in zip(mask_pairs, (TEAL, CORAL)):
        energy = band_energy(path)
        ax.plot(
            range(len(energy)), energy - energy[0], marker="o", color=color, label=label
        )
    ax.set_xlabel("image")
    ax.set_ylabel("energy above the first image (eV)")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "ase_mask")
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    velocity = json.loads((DATA / "novel" / "velocity.json").read_text())
    norms = np.array(velocity["atom_norm_A"])
    ax.bar(range(len(norms)), norms, color=SKY, edgecolor=BLACK, linewidth=0.3)
    ax.set_xlabel("atom")
    ax.set_ylabel("displacement (angstrom)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "velocity_mislabel")


def main() -> None:
    face()
    failures = []
    for step in (
        dlpack,
        toc,
        timing_and_fairness,
        mpi_strong,
        weak_figure,
        db_plots,
        anatomy_and_errors,
        landscapes,
    ):
        try:
            step()
        except (Exception, SystemExit) as exc:
            failures.append(f"{step.__name__}: {exc}")
    print("wrote", sorted(p.name for p in OUT.glob("*.pdf")))
    if failures:
        raise SystemExit("figures not drawn:\n" + "\n".join(failures))


if __name__ == "__main__":
    main()
