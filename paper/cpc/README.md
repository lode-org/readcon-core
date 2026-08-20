# CPC manuscript (readcon-core)

`main.tex` is the Computer Physics Communications software paper.

Numbers in the Performance section come from committed artifacts only:

- Cachegrind I-refs: `docs/source/_generated/cachegrind_results.rst`
- Equal-geometry wall: `benches/results/ase_traj_vs_con.json`,
  `benches/results/h5md_vs_con.json`
- Refresh on the AMD Zen 5 x86_64 workstation used for the tables with
  `benches/compare_readers.py --out benches/results/compare_readers.json`
  and the other `benches/*.py` scripts.

Do not paste a wall-clock number that lacks host, date, and commit.

Build (TeX Live with `elsarticle`):

```
latexmk -pdf main.tex
```
