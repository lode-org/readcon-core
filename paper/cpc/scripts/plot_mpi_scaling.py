#!/usr/bin/env python3
"""Strong scaling of the MPI read, write and ingest paths.

Speedup over one rank for readcon-core (1.07 GB, 3,167,382 frames) and
readcon-db (four copies of a 1.07 GB file, 30,965 frames each). Every run's
output has the bytes of the serial result.
"""
from pathlib import Path
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import plot_figures as pf

ROOT = Path(__file__).resolve().parents[1]
df = pl.read_csv(ROOT / "data" / "mpi" / "strong.csv")


def main():
    theme, _ = pf.house_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.0), constrained_layout=True)
    colours = [pf.TEAL, pf.CORAL, pf.MAGENTA, pf.SKY]
    marks = ["o", "s", "D", "^"]
    for ax, system, title in zip(axes, ["readcon-core", "readcon-db"],
                                 ["(a) readcon-core read and write", "(b) readcon-db ingest"]):
        sub = df.filter(pl.col("system") == system)
        keys = sub.select("operation", "mode").unique(maintain_order=True).rows()
        rmax = sub["ranks"].max()
        for i, (op, mode) in enumerate(keys):
            s = sub.filter((pl.col("operation") == op) & (pl.col("mode") == mode)).sort("ranks")
            t1 = s.filter(pl.col("ranks") == 1)["seconds"][0]
            ax.plot(s["ranks"], t1 / s["seconds"], marker=marks[i], color=colours[i],
                    label=f"{op}, {mode}" if system == "readcon-core" else mode)
        ax.plot([1, rmax], [1, rmax], ls="--", color=pf.BLACK, lw=0.8, label="ideal")
        ax.set_xscale("log", base=2); ax.set_yscale("log", base=2)
        ax.set_xticks([r for r in [1, 2, 4, 8, 16] if r <= rmax])
        ax.set_xticklabels([str(r) for r in [1, 2, 4, 8, 16] if r <= rmax])
        ax.set_xlabel("MPI ranks"); ax.set_ylabel("speedup over one rank")
        ax.set_title(title, loc="left"); ax.legend(frameon=False, fontsize="small")
    pf._theme_axes(axes, theme)
    fig.savefig(pf.OUT / "mpi_strong.pdf")


if __name__ == "__main__":
    main()
