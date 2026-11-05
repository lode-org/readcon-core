# Default con read stays on the calling thread

## What changed

The default read loads one buffer and parses it on the calling thread.
A worker pool starts only when the caller asks for two or more threads.
We also scan pdb and extended xyz into plain arrays, because those paths were losing matched rows.
The pdb scan and the extended xyz scan fill positions, masses and the cell in one pass.

## Why

The old default read mapped a wide file and started workers before the parse.
That startup made a warm read of 100 frames take 5.722 ms on a checkout of main.
The interquartile range on that row is 0.638 ms.
The calling-thread parse brings that same read to 2.073 ms, with an interquartile range of 0.021 ms.

## Example

```python
import readcon

frames = readcon.read_con("resources/test/cuh2.con")
pooled = readcon.read_con("resources/test/cuh2.con", 2)
```

## How the arms are timed

Every con reader sees the same con file.
ASE reads that file with format set to eon.
The eon arm is the upstream client built with meson.
That client calls read_all_frames and then con2matter on every frame.
The timer links that client.
It is not a separate C rewrite of the parser.
Codes that cannot read con are timed on extxyz, xyz and pdb.
readcon is timed on those same files.
One absolute tolerance of 1e-8 is applied to every code and every frame.
A miss exits 1.
The success rate is the fraction of repeats that pass.

## Before and after

The main row is a checkout of main.
The other row is this branch.
Both rows are warm default reads, seven repeats, one pinned core.
The median and the interquartile range use the type 7 quantile.

| arm | file | median ms | interquartile range ms |
| --- | --- | --- | --- |
| main | 100 frames | 5.722 | 0.638 |
| this branch | 100 frames | 2.073 | 0.021 |
| main | 1000000 atoms | 485.088 | 9.052 |
| this branch | 1000000 atoms | 105.504 | 1.206 |

## Win and loss on each row

A row is one cache, one file and one format.
readcon wins a row when its fastest full match is faster than every other full match.
A success of 0 means no repeat stayed inside the tolerance, so that row has no time winner.

con warm 100 frames. readcon wins at 2.057 ms by the mapped read.
The eon client takes 4.224 ms and ASE takes 36.144 ms.
con warm 200 frames. readcon wins at 4.069 ms.
The eon client takes 8.636 ms and ASE takes 71.703 ms.
con warm 100000 atoms. readcon wins at 8.150 ms.
The eon client takes 17.175 ms and ASE takes 133.519 ms.
con warm 1000000 atoms. readcon wins at 92.588 ms.
The eon client takes 302.989 ms and ASE takes 1752.489 ms.
con cold 100 frames. readcon wins at 4.813 ms.
con cold 200 frames. readcon wins at 8.594 ms.
con cold 100000 atoms. readcon wins at 13.583 ms.
con cold 1000000 atoms. readcon wins at 116.539 ms.

extxyz warm 100 frames. readcon wins at 3.080 ms.
extxyz warm 200 frames. readcon wins at 6.225 ms.
extxyz warm 100000 atoms. readcon wins at 16.150 ms.
extxyz warm 1000000 atoms. readcon wins at 168.750 ms.
extxyz cold 100 frames. readcon wins at 5.143 ms.
extxyz cold 200 frames. readcon wins at 10.657 ms.
extxyz cold 100000 atoms. readcon wins at 21.964 ms.
extxyz cold 1000000 atoms. readcon wins at 195.920 ms.

pdb warm 100000 atoms. readcon wins at 12.124 ms.
pdb warm 1000000 atoms. readcon wins at 125.844 ms.
pdb cold 100000 atoms. readcon wins at 18.315 ms.
pdb cold 1000000 atoms. readcon wins at 156.661 ms.

xyz has success 0 on every file, for readcon and for every other code, because the cell does not match.
The 100 frame pdb file and the 200 frame pdb file have success 0 for every code.
Those coordinates are rounded past the tolerance.

## How to reproduce

Install the pins in `bench/h2h/requirements.txt`.
Build this branch with `maturin develop --release --features python,chemfiles-from-sources`.
Build the upstream eon client with meson and link `bench/h2h/eon_time.cpp` to that client.
Run `python bench/h2h/run_h2h.py run --repeats 7 --source-dir . --log-dir bench/h2h/logs/tip`.
For the main row, use a checkout of main as `--source-dir` and write a second log directory.
Summarize with `python bench/h2h/report_h2h.py bench/h2h/logs/tip --out bench/h2h/tables/tip`.
