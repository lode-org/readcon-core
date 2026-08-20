# CPC manuscript (readcon-core)

`main.tex` is the Computer Physics Communications software paper.
`references.bib` is the manuscript bibliography (elsarticle-num).

Numbers in the Performance section come from committed artifacts only:

- Cachegrind I-refs: `docs/source/_generated/cachegrind_results.rst`
- Equal-geometry wall: `benches/results/ase_traj_vs_con.json`,
  `benches/results/h5md_vs_con.json`,
  `benches/results/compare_readers.json`
- Sizes (CON.gz / CON.zst / H5MD): `benches/results/h5md_vs_con.json`

Do not paste a wall-clock number that lacks host, date, and commit.
Do not invent a DOI.

Build (TeX Live with `elsarticle`):

```
latexmk -pdf main.tex
```
