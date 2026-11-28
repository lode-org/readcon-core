# Archives of the paper

The paper rests on two archives, both in its supplementary material.

- `readcon-core.bundle`, a git bundle of readcon-core that holds the measured commit `src/commit.tex` names, with its whole history; `git clone readcon-core.bundle` checks it out without a network.
  That commit is readcon-core 0.17.3 and is not a release tag. Tag v0.17.3 names a different commit. The measurement logs name tree `7df8390b6ee7cfd73f0b849b02313a365121d4a2`, which is the tree of this commit.
  It holds the library and its bindings, the specification `docs/orgmode/spec.org` of that commit, the conformance corpus `resources/conformance/`, and `paper/cpc`.
  Besides that commit, the bundle holds the branch `main`, the branch `paper/cpc-v7.16` of the previous submission, and the release tags. The logs do not name a second commit with tree `7df8390b6ee7cfd73f0b849b02313a365121d4a2`.
  A clone of the bundle keeps the objects of that commit, and `scripts/gen_version_map.py` and `scripts/check_manuscript.py` read the library of that commit from them.
  The concept record of readcon-core is https://doi.org/10.5281/zenodo.18753567.
- `paper-cpc.tar.gz`, this directory, which unpacks into a checkout of that commit.

## What paper-cpc.tar.gz holds

`scripts/pack_paper.py` writes it.
It holds every file of `paper/cpc` that git does not ignore, except the two PDFs that `scripts/build_tex.sh` writes into `src/`, and the records that the ignore rules would drop: the raw output and the log of the Cachegrind run in `bench/results/r0174/cachegrind/` and the eOn runs under `evidence/work/e1/`, which the restart figure plots.
It leaves out `bench/work/` (the timed files, which `bench/make_payloads.py`, `bench/h2h.py` and `bench/binary_formats.py` write, and the programs that `bench/build_chemfiles.sh`, `bench/cpp_reads.py` and `bench/binary_formats.py` build), `.pixi/` and the TeX build products under `src/`.
The members are sorted by name, owned by uid 0 and dated 2026-10-31 00:00 UTC, the `SOURCE_DATE_EPOCH` of `scripts/regen_paper.py`.

## Rebuild and rerun

`readme.org` and the listing in the section Reproduction of the supplement rebuild the paper in a checkout of the commit of `src/commit.tex`, in the environment of `environment/`.
That section names the script behind each record: the measurements of `scripts/regen_paper.py --measure`, the eOn band, the resume walls and the file sizes, the performance, head-to-head and binary-format records under `bench/results/r0174/`, and the conformance records under `data/`.

The eOn band of `evidence/e1_restart.py` runs the `eonclient` of the conda-forge package that `evidence/results/e1_restart.json` names under `eon_build.conda_package`, with its URL and SHA-256.
The script takes the client from `EONCLIENT`, then from `PATH`, then from `paper/cpc/.pixi/envs/eon/bin` of the checkout, the `eon` environment of `pixi.toml`.

## Release

`src/commit.tex` holds one value, `\readconcommit`, the measured commit. That commit is readcon-core 0.17.3 and is not a release tag.
`scripts/gen_release.py` writes `src/release.tex` from that commit's Cargo.toml. `\readconversion` and `\rcMeasuredVersion` are 0.17.3. The role is measured commit. The tag sentence says this commit is not a release tag.
`\rcMeasuredSpecBlob` is the `docs/orgmode/spec.org` of that commit.
Every record names the library it measured by that digest and the commit of the checkout that ran it.
One record also depends on the commit of `src/commit.tex`: `data/test_run.json`, the run of the example program in a clone of that commit, prints the commit in its commands, and `scripts/test_run.py --tables` stops when the record names another.
No other record changes with the tag, and neither do `data/trace/numbers.csv` and the files under `src/figures/generated/` but `test_run.tex`, the listing that `scripts/test_run.py` writes from that record.

When the tag names another commit, in a checkout of that commit with this directory unpacked into it, set `\readconcommit` in `src/commit.tex` to that commit and run

```
python3 scripts/gen_release.py
python3 scripts/test_run.py --checkout ../.. --toolchain 1.88.0
bash scripts/build_tex.sh
python3 packet/make_packet.py
python3 scripts/check_manuscript.py
python3 scripts/check_manuscript.py --rebuild
python3 scripts/make_arxiv_combined.py --out ../arxiv
python3 scripts/pack_paper.py ../paper-cpc.tar.gz
```

These rewrite `src/release.tex`, `data/test_run.json` with `src/figures/generated/test_run.tex`, the two PDFs, `packet/CPC-FORM.md`, the arXiv source `readcon-arxiv-v2.tar.gz` and `paper-cpc.tar.gz`.
The test run builds the example program in the checkout with rustup's toolchain 1.88.0, whose rustc and cargo `data/test_run.json` names.
The bundle is then written again from the repository. The measurement logs name the commit of `src/commit.tex` and tree `7df8390b6ee7cfd73f0b849b02313a365121d4a2`. The latest release tag is v0.23.2 at commit `8c2d9984c40aedfb2e0084fedefaa02e930957f2`.
The commands above run from this paper tree. test_run.py --checkout expects a separate checkout of the measured commit that src/commit.tex names, taken from the bundle as Listing S1 does, or from a clone: `git clone https://github.com/lode-org/readcon-core readcon-measured && git -C readcon-measured checkout "$(python3 scripts/gen_release.py --commit)"`. Tag v0.17.3 is the published release that precedes it; `git log v0.17.3..$(python3 scripts/gen_release.py --commit)` lists the commits between them, and `git log v0.17.3..origin/develop` lists later work.

## The clean room

The review package that carries the two archives also carries `check_package.py`.
Run as `python3 check_package.py --clean-room INSTALLER`, with a Miniforge installer, it makes an empty directory with an empty HOME and runs Listing S1 of the supplement there as printed, under `env -i`, from the bundle and this tarball.
It requires the two PDFs that Listing S1 typesets to be the submitted PDFs byte for byte, every member of this tarball to keep its bytes in the checkout, and the arXiv source that `scripts/make_arxiv_combined.py` writes, `readcon-arxiv-v2.tar.gz`, to be the submitted one.
It then reruns every record that depends neither on timing nor on another host and requires each to come back: byte for byte, or, for a JSON record, equal once each block that names a build is cut to the release, library digest and commit it names and the SHA-256 and directories of the programs and Python environments that the clean room builds are dropped.
The eOn runs of `evidence/e1_restart.py` come back with their run times dropped, and `src/figures/generated/version_map.tex`, which prints the builds the records name, is compared before the reruns.
`logs/clean-room.log` of the review package records the run and lists the records that no step reruns: the timed records and the records of other hosts.
