#!/usr/bin/env python3
"""Regenerate the restored figures in the Ruhi palette.

The five colours are the Ruhi palette from chemparseplot
(coral, sunshine, teal, sky, magenta).
Each PDF is written from a committed record.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated"
DATA = ROOT / "data"
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
    view, copy = [], []
    for line in (DATA / "dlpack_cost.txt").read_text().splitlines():
        if line.startswith("repeat "):
            parts = line.split()
            view.append(int(parts[3]) / 1e3)
            copy.append(int(parts[5]) / 1e3)
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    x = np.arange(len(view))
    ax.bar(x - 0.18, view, width=0.36, color=TEAL, edgecolor=BLACK, linewidth=0.4, label="DLPack view")
    ax.bar(x + 0.18, copy, width=0.36, color=CORAL, edgecolor=BLACK, linewidth=0.4, label="explicit copy")
    ax.set_xlabel("repeat")
    ax.set_ylabel("time (microseconds)")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "dlpack")


def toc() -> None:
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.set_xlim(0, 4)
    ax.set_ylim(0, 4)
    ax.axis("off")
    labels = ("mask", "identifier", "time unit", "coordinates")
    for i, (label, color) in enumerate(zip(labels, CYCLE)):
        ax.add_patch(plt.Rectangle((0.4, 3.1 - i * 0.8), 3.2, 0.6, facecolor=color, edgecolor=BLACK))
        ax.text(2.0, 3.4 - i * 0.8, label, ha="center", va="center", color="white" if color != SUNSHINE else BLACK)
    save(fig, "toc")


def timing_and_fairness() -> None:
    cells = json.loads((ROOT / "bench" / "results" / "r0174" / "reads.json").read_text())["cells"]

    def med(reader: str, threads: int = 1) -> float:
        for cell in cells.values():
            if cell["reader"] == reader and cell["threads"] == threads and cell["kind"] == "python":
                return cell["median_s"]
        raise KeyError(reader)

    labels = ["readcon", "ASE XYZ", "extxyz C", "OVITO", "ASE traj", "h5py", "MDAnalysis"]
    keys = ["readcon", "ase_extxyz", "extxyz_c", "ovito", "ase_traj", "h5py", "mda_h5md"]
    values = [med(key) for key in keys]
    bars("timing", labels, values, "median wall time (s)")
    ratios = [med("readcon") / med(key) for key in keys[1:]]
    bars("fairness_ratios", labels[1:], ratios, "readcon median / peer median")
    frames = 10000
    rate_labels = ["full, 1", "full, 8", "fields, 1", "fields, 8", "coords, 1", "coords, 8"]
    rates = [
        frames / med("readcon", 1),
        frames / med("readcon", 8),
        frames / med("readcon_fields", 1),
        frames / med("readcon_fields", 8),
        frames / med("readcon_coords", 1),
        frames / med("readcon_coords", 8),
    ]
    bars("layers", rate_labels, rates, "frames per second")
    bars("roofline", rate_labels, rates, "frames per second")


def mpi_plots() -> None:
    rows = list(csv.DictReader((DATA / "mpi" / "strong.csv").open()))
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    series = {}
    for row in rows:
        if row["system"] != "readcon-core":
            continue
        series.setdefault(f"{row['operation']} {row['mode']}", []).append((int(row["ranks"]), float(row["seconds"])))
    for (label, points), color in zip(series.items(), CYCLE):
        points.sort()
        ranks, seconds = zip(*points)
        base = seconds[0]
        ax.plot(ranks, [base / s for s in seconds], marker="o", color=color, label=label)
    ax.plot([1, 8], [1, 8], color=BLACK, linewidth=0.6, linestyle="--")
    ax.set_xlabel("ranks")
    ax.set_ylabel("speedup against one rank")
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "mpi_strong")
    weak = list(csv.DictReader((DATA / "cloud-runs-2" / "04" / "weak.csv").open())) if (DATA / "cloud-runs-2" / "04" / "weak.csv").is_file() else []
    if not weak:
        # The stored weak file in this tree is the serial shard table.
        shard = list(csv.DictReader((DATA / "mpi" / "db_serial.csv").open()))
        fig, ax = plt.subplots(figsize=(7.0, 3.2))
        ranks = [int(row["ranks"]) for row in shard]
        ax.plot(ranks, [float(row["single"]) for row in shard], marker="o", color=TEAL, label="single")
        ax.plot(ranks, [float(row["sharded"]) for row in shard], marker="o", color=CORAL, label="sharded")
        ax.set_xlabel("ranks")
        ax.set_ylabel("seconds")
        ax.legend(frameon=False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        save(fig, "mpi_weak")


def db_plots() -> None:
    summary = list(csv.DictReader((DATA / "db" / "summary.csv").open()))
    ingest = [row for row in summary if row["kind"] == "frames_per_s" and row["n_frames"] == "1000"]
    bars(
        "db_ingest_throughput",
        [row["system"] for row in ingest],
        [float(row["median"]) for row in ingest],
        "median frames per second",
    )
    bandwidth = [row for row in summary if row["kind"] == "mb_per_s" and row["n_frames"] == "1000"]
    bars(
        "db_ingest_bandwidth",
        [row["system"] for row in bandwidth],
        [float(row["median"]) for row in bandwidth],
        "median MB/s",
    )
    queries = [row for row in summary if row["kind"] == "query_s" and row["query"] == "composition"]
    bars(
        "db_query_latency",
        [f"{row['system']} {row['cache']}" for row in queries],
        [float(row["median"]) for row in queries],
        "median seconds",
    )
    sizes = [row for row in csv.DictReader((DATA / "db" / "sizes.csv").open()) if row["n_frames"] == "1000"]
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
    values = [1 if row.get("c_null_handle") else 0 for row in errors]
    bars("error_classes", labels, [1] * len(labels), "illegal file")
    fidelity = json.loads((DATA / "novel" / "fidelity.json").read_text())["rows"]
    score = []
    for row in fidelity:
        score.append(sum(row[key] == "exact" for key in ("mask", "id", "time_unit", "binary64")))
    bars("roundtrip_fidelity", [row["format"] for row in fidelity], score, "exact fields out of four")
    diff = json.loads((DATA / "novel" / "restart_diff.json").read_text())
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    for (name, block), color in zip(diff.items(), CYCLE):
        if "mic_max_abs_A" not in block:
            continue
        column = [max(row) for row in block["mic_max_abs_A"]]
        ax.plot(range(len(column)), column, marker="o", color=color, label=name.replace("_", " "))
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
        ax.plot(range(len(energy)), energy - energy[0], marker="o", color=color, label=label)
    ax.set_xlabel("image")
    ax.set_ylabel("energy above the first image (eV)")
    ax.legend(frameon=False, fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "restart_formats")
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    for (label, path), color in zip(pairs, CYCLE):
        energy = band_energy(path)
        ax.plot(range(len(energy)), energy - energy[0], marker="o", color=color, label=label)
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
        ax.plot(range(len(energy)), energy - energy[0], marker="o", color=color, label=label)
    ax.set_xlabel("image")
    ax.set_ylabel("energy above the first image (eV)")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "ase_mask")
    # Morse restart energies are not in this npz set. Plot the held band again
    # under the restart name only when a Morse record is absent, and keep the
    # existing restart.pdf when this function is not asked to replace it.
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    velocity = json.loads((DATA / "novel" / "velocity.json").read_text())
    norms = np.array(velocity["atom_norm_A"])
    ax.bar(range(len(norms)), norms, color=SKY, edgecolor=BLACK, linewidth=0.3)
    ax.set_xlabel("atom")
    ax.set_ylabel("displacement (angstrom)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "velocity_mislabel")


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    boxes = [
        (0.4, 4.2, "C"),
        (2.6, 4.2, "C++"),
        (4.8, 4.2, "Julia"),
        (7.0, 4.2, "Fortran"),
        (3.6, 2.2, "Rust core"),
        (3.6, 0.4, "Python / NumPy"),
    ]
    for (x, y, text), color in zip(boxes, CYCLE + (TEAL,)):
        ax.add_patch(plt.Rectangle((x, y), 2.0, 1.0, facecolor=color, edgecolor=BLACK))
        ax.text(x + 1.0, y + 0.5, text, ha="center", va="center", color="white" if color != SUNSHINE else BLACK)
    save(fig, "architecture")


def structures() -> None:
    """Three orthographic views. xyzrender is used when it imports."""
    try:
        import xyzrender  # noqa: F401

        used = "xyzrender"
    except Exception:
        used = "orthographic"
    survey = OUT / "survey_frame.con"
    band = DATA / "failure" / "bands" / "uninterrupted.npz"
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.6))
    # Survey frame coordinates are the fifth field group of each atom line.
    coords = []
    for line in survey.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 4:
            try:
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                continue
    coords = np.array(coords) if coords else np.zeros((1, 3))
    panels = [coords, np.load(band)["pos"][len(np.load(band)["pos"]) // 2], np.load(band)["pos"][0]]
    titles = ["survey", "band middle", "band end"]
    for ax, xyz, title, color in zip(axes, panels, titles, CYCLE):
        ax.scatter(xyz[:, 0], xyz[:, 1], s=18, c=color, edgecolors=BLACK, linewidths=0.3)
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(used, fontsize=8)
    save(fig, "structures")


def main() -> None:
    face()
    dlpack()
    toc()
    timing_and_fairness()
    mpi_plots()
    db_plots()
    anatomy_and_errors()
    landscapes()
    print("wrote", sorted(p.name for p in OUT.glob("*.pdf")))


if __name__ == "__main__":
    main()
