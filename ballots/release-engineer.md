# Ballot: release engineer

Rank: **A, B, C**

Confidence that A is the right top pick: **0.82**

Expected pick from the other ballots: **A**

I read `design/consumers-A.md` at `97d352e`, `design/consumers-B.md` at `06044cc`, `design/consumers-C.md` at `80cf36a`, and `design/consumers-critique.md` at `860571e`. The vote is on version pins, release order, CI cost, and the readcon-db 0.1.9 tag. A feature counts once a production caller uses it. Working behaviour is the baseline. The library the consumers move to is readcon-core 0.17.1 and a readcon-db tag that pins that core. No tag or release is cut by this ballot. Both publishes wait for Rohit's yes.

## What is actually published

| Artifact | Git tag | Registry |
| --- | --- | --- |
| readcon-core | `v0.17.0` (`f13f87c`, GitHub release 2026-10-11). There is no `v0.17.1` tag and no GitHub release of that name. | crates.io max `0.17.0`. PyPI `readcon` `0.17.0`. |
| readcon-db | `v0.1.8` (`0001a2c`). There is no `v0.1.9` tag. | crates.io max `0.1.8`. PyPI `readcon-db` `0.1.8`. |

`main` of readcon-core is `694e808`. `Cargo.toml` already says `0.17.1`. `96fd38f`, the commit the designs call the 0.17.1 tag, is an ancestor of that tip, and it is not a tag. `main` of readcon-db is `0725c94`. That commit's `Cargo.toml` still says `version = "0.1.8"` and `readcon-core = "=0.17.0"`. The 64-frame codec is under `Unreleased`. Tag `v0.1.8` pins `readcon-core = "=0.16.1"` and has no `src/frame_codec.rs`.

A wrap `revision = v0.17.1` does not resolve. A crates.io publish of readcon-db `0.1.9` with `readcon-core = "=0.17.1"` cannot land before readcon-core `0.17.1` is on the registry. Consumers stay on the pins they have until both tags exist.

## The eight critique claims

All eight held.

1. **readcon-ops at the eOn pin is not the adapter A describes.** eOn `pixi.toml` at `cc4f699` pins `4d7881a`. That tree is `src/readcon_ops/match.py` and `wulff.py`. `__all__` is `identical`, `internal_motion`, `rotate`, `rotational_match`, `spacegroup`, `wulff_vertices`. A frame is `r`, `box`, `names`, `copy`, and `__len__`. The package docstring says it does not read a file. `pyproject.toml` depends on numpy, spglib, and minimage. There is no `frames.py`, `_from_conframe`, `as_frame`, `_is_protocol`, `_is_conframe`, or `lengths_angles_to_cell`. `eon/atoms.py` passes `Structure` into `spacegroup` and `rotational_match`. Those names exist on ops `main` (`39787cc`) and on `fix/kabsch-and-frames`. `4d7881a` is not an ancestor of that main. The pin eOn runs does not contain them.

2. **seams does not exchange a db-owned handle.** At `305fb3c`, `sinp::readConCorpus` calls `rkrdb_get_frame_text`, closes the database, parses with seams' `read_con_string_iterator`, then `cloudFromHandle` and `free_rkr_frame` on that local handle. No call site uses `rkrdb_get_frame`. The `meson.build` comment is the constraint: the db crate vendors its own core, and seams does not free that handle with this build's `libreadcon_core`. The live bug is real: `cloudFromHandle` keeps the SoA only when `xyz[1] == frame->atoms[0].y` and `xyz[2] == frame->atoms[0].z`.

3. **The one-frame and path extend symbols are already shipped.** `rkrdb_extend_trajectory_frame` and `rkrdb_extend_trajectory` are in `include/readcon-db.h` on tag `v0.1.8` and on `0725c94`. Rust `ConCorpus::extend_trajectory_frames` is on main. `extend_trajectory_str` and `rkrdb_extend_trajectory_str` are absent on both. Python `ConCorpus.extend_trajectory` calls `extend_trajectory_path_units`. Python `append_trajectory_frames` imports the installed `readcon` wheel and calls `write_con_string`. That last part of A is right. A's "if 0.1.9 exports one" and "if `rkrdb_extend_trajectory` is missing" describe symbols the 0.1.8 header already has.

4. **B's Bohr factor is the reciprocal of the restart tool's constant.** `include/cpmdc_restart.h` defines `CPMDC_RESTART_ANGSTROM_PER_BOHR` as `0.529177210859`. The comment says OpenCPMD `cnst%fbohr` is `1/0.529177210859`. `print_triples` multiplies by the macro to print angstroms. `patch-positions` divides by the macro to store bohr. B's `export-con` converts with `1/0.529177210859`. `CPMDC_BOHR_TO_ANGSTROM` in `src/cpmdc_params.h` is `0.529177210903`, a different number. A and C name the restart macro and multiply by it.

5. **Canonical key order is not the client/server byte split.** `client/ConFileIO.cpp` constructs `ConFrameWriter(path, compression, precision)` with `kConPrecision = 17` and `kConvelPrecision = 6`. That constructor calls `create_writer_from_path_with_precision_c`, which is `FloatFormat::DecimalPlaces`. `eon/fileio.py` `savecon` calls `write_con_string([frame])` with precision omitted. `FloatFormat::default` is `RoundTrip`. `create_writer_from_path_c` passes `precision = None`, which constructs `ConFrameWriter::new`. Python `canonical` defaults to false. `header.metadata` is a `BTreeMap`. `refresh_metadata_cache` inserts sections in a fixed order and metadata keys in map order. `self.canonical` only disables the metadata cache. It is not read while the bytes are emitted. On this writer, `canonical=True` does not produce a second spelling. The production Python call that still passes a precision is `eon/process_catalog.py`: `readcon.write_con_string([frame], 17)`. A and C do not name that call. B names it, and then turns canonical on.

6. **A one-frame extend does not fill a 64-frame group.** `group_prepared` returns immediately when `prepared.len() < 2`. `pack_aligned` emits `0xFD 0x03` only for a run with more than one frame inside that call, and only when the group is shorter than the per-frame values. `rkrdb_extend_trajectory_frame` passes a one-element slice to `extend_trajectory_frames`. A movie appended one frame per step stays `0xFD 0x01` or raw UTF-8. A path passed to `rkrdb_extend_trajectory` groups when that path contains an aligned run of more than one frame. A's 64-frame batch matches the codec. B's per-step `rkrdb_extend_trajectory_frame` does not. C's `trajectory_append` groups only when the caller hands the run in one call, and eOn's `matter2con(..., append=true)` hands one frame.

7. **The numeric read of a parsed Python frame is not `coords_array`.** `coords_array`, `velocities_array`, and `forces_array` copy `Atom` fields. The getters `xyz`, `vel`, and `frc` copy `positions.f64_slice()` (and the velocity and force columns) when `inner` is set. `disp` and `spread` walk atoms. `ase_from_pyconframe` copies `atom.x/y/z`. It does not call `coords_array`. `atom_ids_array`'s docstring says "atomic numbers"; the values are `atom_id`. C puts `coords_array` in the restart contract.

8. **An identical re-append is `TrajExists`.** `append_trajectory_str` calls `commit_prepared` with `replace_meta = false`. That returns `TrajExists` as soon as `traj_meta` has the id. The bytes are not compared. `workflow_dedup_identical_ingest` stores one file under two trajectory ids and dedups in `unique_frame_keys`. The C++ mirror calls `rkrdb_append_trajectory_str` and ignores the status, so a second insert of the same id fails quietly. Identical-text success would be new code in front of that call. C specifies that success.

## Why this order

A is the only design that names the tag the release has to cut, pins it exactly, and refuses a new package.

The first db release is **0.1.9**, and only after readcon-core **0.17.1** is a real tag and a registry crate. The 0.1.9 crate pins `readcon-core = "=0.17.1"`. Its Python `append_trajectory_frames` calls `append_trajectory_frames_with_float_format(..., FloatFormat::RoundTrip)` inside the crate, so the stored UTF-8 does not follow whichever `readcon` wheel happens to be installed. `get_frame_text` is tested for a `0xFD 0x03` group, a `0xFD 0x02` redirect, a single `0xFD 0x01`, and a raw untagged value from a 0.1.8 fixture. `GROUP_LEN`, the tags, and `decode_frame` stay. Consumers do not move until that tag exists. Wraps pin the tag. They do not pin `0001a2c`, and they do not pin `91181ef`.

`rkrdb_extend_trajectory` of a file that contains only the new batch already groups. That symbol is in the 0.1.8 header. 0.1.9 does not add `extend_trajectory_str` and does not add a second in-memory batch symbol. A production caller that has no path can ask for the binding later. It is not in this tag.

eOn's C++ wrap and the Python floors move in one change, after 0.1.9 exists. `savecon` is RoundTrip once the wheel is 0.17.1. The client is precision 17 and 6 until that change. `process_catalog.py`'s explicit `17` moves in the same change. A gap between them is a mixed deploy, which is the part of A's order I will not ship. `readcon-ops` stays at `4d7881a`. That pin matches the package production calls. A commit whose purpose is to vendor `frames.py` has no caller in this cutover.

chemparseplot moves the `neb` extra, the `test` extra, pixi, the `>=0.7` hint, and the assertion that locks the hint, in one change. rgpycrumbs moves `pixi.toml`, `_aux.py`, and every PEP 723 header in one commit, after `con_io` and `load_trajectory`, `plot_con_overview`, and `plot_con_overlay` exist. `tests/test_uma_cli.py` compares against the literal `readcon>=0.14.5`. A floor check at `(0, 7)` or `(0, 13)` stays green if one script is left behind, and `uv run` will install that script's wheel.

rgpot's readcon floor lives in the `eonviz` feature, beside exact pins of chemparseplot and rgpycrumbs. `pyproject.toml` does not depend on readcon, and the C++ package stays that way. `scripts/check_eonviz_pins.sh` does not parse readcon. Raising the eonviz floor to `>=0.17.1` passes the script. If the resolver must not float, the script learns a minimum it actually parses. Adding readcon to the core package dependencies pulls a CON library into every rgpot install.

rgsaddle's optional `readcon-db = "0.1"` can resolve to tag `v0.1.8` and pull `readcon-core = "=0.16.1"` beside a direct 0.17.1 pin. The feature has no call site. Pin both to 0.1.9 and `=0.17.1`, or leave the feature out of CI until a host calls it. The `capi` job stays free of readcon. rgmin's `default`, `capi`, and `highs` rows stay free of readcon. An optional feature row is a separate job. A new default dependency is not.

seams moves both wraps in one commit, after the golden exists, so a build cannot see a 0.17.1 core beside a db whose crate pins `=0.16.1`. The core wrap `91181ef` is `v0.16.1-12-g91181ef` and `v0.16.2~2`. The meson floor `>=0.16.2` accepts a tag that wrap does not build. The db floor `>=0.1.8` is satisfied by `0001a2c`. cpmdc's readcon link stays optional and off in the CPMD-only job. A default link of the Rust staticlib pulls `libstdc++` into a C tool whose existing test stays bit-stable without readcon.

C adds a repository, a cdylib, a staticlib, a header, and a link into eOn, rgsaddle, rgmin, cpmdc, and seams before any of those trees has a RoundTrip writer. eOn already documents `STATUS_ENTRYPOINT_NOT_FOUND` when a second `libreadcon_core` is on `PATH`. Deleting `dlopen` makes the corpus a load dependency of `eoncbase`. The Windows mirror is compiled out today, and a missing library does not change `IoStatus`. That is the baseline. The writer the client needs is the `ConFrameWriter` constructor that takes no precision, in the core the client already links. I will not publish `readcon-xfer`.

## Order

Each step is green before the next repository moves a pin. A red build belongs to one repository.

1. Rohit tags and publishes readcon-core `0.17.1`. The code is on `main`. The tag is not.
2. Rohit tags and publishes readcon-db `0.1.9` with `readcon-core = "=0.17.1"` and the in-crate RoundTrip Python writer. Consumers stay on their current pins.
3. eOn client and Python server, one change. Wrap `v0.17.1`, floors `readcon>=0.17.1` and `readcon-db>=0.1.9`, delete `kConPrecision` and `kConvelPrecision`, and drop the `17` in `process_catalog.py`. Path-only trajectory id, shared by the C++ and Python FNV. Buffer up to 64 serialized frames and `rkrdb_extend_trajectory` of a file that contains that batch. `dlopen` stays. A missing library does not fail the AKMC step. `ApproveConFileIO` is regenerated once in this commit. Dynamics resume is a later change. The ops pin does not move.
4. chemparseplot. Pin, hint, assertion, `read_first_frame`, `frame_with_positions`, deletion of `format="eon"` reads of `.con`, and the three `api` names. No readcon-db dependency. Canonical stays at the default.
5. rgpycrumbs. One floor commit, then the splitter writer deleted in favour of `con_io`. No corpus client.
6. rgpot `eonviz` floor and deletion of `_read_eon_con`. No core `pyproject.toml` dependency.
7. rgsaddle read pin to `=0.17.1`. The db feature is pinned to 0.1.9 or left out of CI. `store_band` is not a release gate. Nothing calls it.
8. cpmdc optional bridge, default off. Multiply by `CPMDC_RESTART_ANGSTROM_PER_BOHR`. `cpmdc_restart_set_cell` is in the import path. The coefficient records stay byte-identical. The stub and CPMD-only jobs do not link readcon.
9. seams, both wraps, last. Delete the `xyz[1] == atom.y` heuristic. Keep `rkrdb_get_frame_text` and seams' own parser. No new writer.

rgmin's optional `=0.17.1` writer can land any time after the golden. It is not on this path. `Solver::step` does not open files. The ASE adapter keeps raising. `test_todict_and_restart_refusal` keeps its `.json`.

## CI cost

The jobs that already exist are the regression gate. A pin bump whose old assertions stay green is not done. The witness for that repository runs in the same job. Approval masters that store CON bytes change in the writer commit and then freeze.

- readcon-core: one fixture, Rust, C, and Python, `cmp` against `ConFrameWriter::new`, and a precision-17 writer asserted different. The conformance manifest stays. Downstream jobs download those bytes. A consumer that re-encodes the expected text will go green while the writer drifts.
- readcon-db: 64 frames plus one, `get_frame_text` equals the fixture, the group head is `0xFD 0x03`, a raw untagged value still reads, and `zstd_round_trip_is_byte_exact_and_does_not_cook` stays green. This job does not skip.
- eOn: `ci_build_akmc.yml` already runs `meson test --suite eon`. The corpus witness runs where `libreadcon_db.so` from 0.1.9 is on the path. Windows compiles the mirror out, so that witness is not a Windows failure. Resume tests load `pos_cp.con` and the saddle pair without the database. One existing minimization keeps the energy tolerance it already uses.
- chemparseplot and rgpycrumbs: `build_test.yml` and `ci_test.yml` with `--pep723-check`. Byte tests skip only when that job has no wheel. The job that claims the pin installs 0.17.1.
- rgsaddle and rgmin: one extra feature invocation each, and only when that feature is in the change. The default invocations do not link readcon.
- cpmdc: `tests/test_cpmd_restart.c` on the default build, with no readcon. The optional job does the CON round trip and the coefficient `memcmp`.
- seams: `tests/test_readcon.cpp` plus a bit check on the golden coordinates. One ASan run of ingest and decode. LAMMPS dump tests stay out of it.

A 65-frame corpus witness in every consumer, a new crate's CI, and a readcon link on rgmin's `default` / `capi` / `highs` rows are cost I will not add.

## What the final plan takes from B and C

A is the base. These pieces of the other two are part of the release, because leaving them out ships the wrong pin, the wrong bytes, or a regression.

From B:

- The eOn client and the Python server move together, and `process_catalog.py` stops passing `17` in that same change.
- `displacement.con` is a new geometry. Peak forces do not ride along. The reloaded file has no forces section. `direction.dat` stays `%18.12f`.
- The golden is one byte string produced by `ConFrameWriter::new` on the tagged 0.17.1 writer. Downstream CI downloads it. readcon-core asserts that a precision-17 writer differs on a value RoundTrip preserves.
- The cpmdc bridge, when it is built, calls `cpmdc_restart_set_cell` as well as the coordinate and velocity setters. The factor is `CPMDC_RESTART_ANGSTROM_PER_BOHR`, the macro the restart tool already multiplies by.
- rgmin does not gain a readcon dependency on the rows CI already runs, and the ASE adapter keeps refusing `restart=`. A's optional module is allowed after the golden. It is not required for the tag.
- A dynamics resume from the last `dynamics.con` frame, with velocities, is a later change. `Dynamics::run` today appends through `matter2con` with `with_velocities=false`, and there is no mid-run resume. The writer commit does not add that job behaviour. `ApproveConFileIO` moves once.

From C:

- An uncompressed append whose tail this process did not write is parsed first. Parse failure returns `AppendError` and leaves the file bytes untouched. A gzip or zstd movie is rewritten as a whole file. A concatenated gzip member is invisible on read.
- The restart witness is `get_frame_text` / `get_frame` and `rkr_frame_xyz_f64`, and on Python the `xyz` getter. `rkrdb_get_positions` is the cooked cache. The corpus comment says that blob is not the file. seams keeps its text reparse through the wrap bump.
- A second `append_trajectory_str` of an existing trajectory id returns `TrajExists` whether or not the text matches. The 0.1.9 tag does not redefine that as success. A replace-frame-0 call is a later API, with a caller, and it is not this release.
- `matter2con` keeps the scratch file. RoundTrip does not need a new buffer ABI. The C writer still takes a path.

The final plan leaves these on the table. C's `readcon-xfer` crate, the deletion of `dlopen`, the identical-text success, the split trajectory id (path-plus-text for checkpoints, path-only for movies), `coords_array` as the bit witness, readcon-db inside chemparseplot and rgpycrumbs, a `.con` path that moves atoms in rgmin's ASE `restart=`, a readcon link in the cpmdc stub build, and new seams writers. B's `canonical=True`, the per-step `rkrdb_extend_trajectory_frame` as the way a movie fills a group, the Bohr reciprocal, the readcon dependency in rgpot's core `pyproject.toml`, the dynamics resume inside the writer commit, and a seams bump that moves only the core wrap.
