#!/usr/bin/env python3
"""readcon-db MPI ingest table: both modes and the same-host serial ingest."""
from pathlib import Path
import csv
ROOT = Path(__file__).resolve().parents[1]
rows = list(csv.DictReader(open(ROOT / "data" / "mpi" / "strong.csv")))
serial = {r["ranks"]: (r["single"], r["sharded"]) for r in csv.DictReader(open(ROOT / "data" / "mpi" / "db_serial.csv"))}
db = [r for r in rows if r["system"] == "readcon-db"]
ranks = sorted({int(r["ranks"]) for r in db})
def t(mode, n):
    return next(float(r["seconds"]) for r in db if r["mode"] == mode and int(r["ranks"]) == n)
body = []
for n in ranks:
    s1, s2 = serial[str(n)]
    body.append(f"{n} & {t('single writer', n):.2f} & {t('single writer', 1) / t('single writer', n):.2f} & {float(s1):.2f} & "
                f"{t('sharded', n):.2f} & {t('sharded', 1) / t('sharded', n):.2f} & {float(s2):.2f} \\\\")
tex = r"""\begin{table}[ht]
\centering
\small
\caption{readcon-db MPI ingest of four copies of a \(1.07\,\mathrm{GB}\) trajectory (30{,}965 frames each), batch 4096, MPICH 4.2.3, means of five runs in seconds.
Serial is the serial ingest that rank 0 runs on the same host right after each MPI run.
Every MPI corpus has the canonical dump of the serial one.}
\label{tab:dbmpi}
\begin{tabular}{rrrrrrr}
\toprule
& \multicolumn{3}{c}{One writer} & \multicolumn{3}{c}{Four shards} \\
Ranks & MPI & Speedup & Serial & MPI & Speedup & Serial \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
(ROOT / "src" / "figures" / "generated" / "dbmpi_table.tex").write_text(tex)
