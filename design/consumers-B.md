# Consumers B: restart state, checkpoints, and campaign storage

This note starts from the production runs, then assigns readcon features to the holes those runs already have. It was written against the trees below and does not depend on any other `design/consumers-*` branch.

| Tree | Commit measured | What it pins today |
| --- | --- | --- |
| readcon-core `main` | `96fd38f` (v0.17.1, 2026-10-14) | This is the writer and parser the consumers should move to. |
| eOn `TheochemUI/eOn` | `cc4f699` | C++ Meson `>=0.16.0`, wrap revision `v0.16.0`. Python `readcon>=0.15.0`, `readcon-db>=0.1.6`. |
| rgsaddle | `ffe54d4` | Optional `readcon-core` `0.14`, read only. `readcon-db` `0.1` is a feature with no call site. |
| rgmin `0.4.0` | `2560f83` | No readcon dependency. |
| rgpot | `b901b09` | Pixi `readcon>=0.14.7`. `atoms_from_con` reads. |
| cpmdc | `c518e1e` | Fortran unformatted `RESTART` only. No readcon. |
| readcon-db `main` | `0725c94` | `readcon-core = "=0.17.0"`. Sixty-four-frame zstd is in the unreleased changelog, not in v0.1.8. |
| seams-core | `305fb3c` | Meson `readcon-core >=0.16.2`. Wrap revision `91181ef` (`v0.16.1-12`, an ancestor of tag `v0.16.2`). Reader and corpus selector only. |

v0.1.8 of readcon-db still documents the 0.16.1 writer. The 0.16.2 line is the floor seams still builds. Neither of those is a place to leave a new restart.

## What a production run actually saves

Three kinds of state show up. They do not belong in one file.

1. **Ionic restart.** Positions, cell, masses, atom ids, fixed flags, and, when the potential is already clean, energy and forces. Dynamics also needs velocities. A saddle checkpoint also needs the mode. A Hessian mode dump and an instanton centroid need displacements or spreads.
2. **Optimizer or wavefunction checkpoint.** L-BFGS pairs, FIRE velocity, Lanczos subspace, a finite-difference Hessian column, and CPMD plane-wave coefficients. These are not a structure.
3. **Campaign.** The ordered history of ionic frames a later job selects by trajectory and frame index, or by energy, formula, or forces. The `.con` file remains the copy a client can read without the corpus.

### eOn

The C++ client is the writer of record for a run directory.

| Run | Where it resumes | What is on disk |
| --- | --- | --- |
| Minimization, Monte Carlo | `MinimizationJob::run`, `MonteCarloJob::run` load `pos_cp.con` when `main.checkpoint` is set | `helpers::relaxMatter` calls `Matter::matter2con("{prefix}_cp")` every accepted step. Prefixes are `pos`, `react_neb`, `prod_neb`, `matter_cur`, `matter_hop`. |
| Saddle search | `SaddleSearchJob::run` loads `displacement_cp.con` and `mode_cp.dat` together | `MinModeSaddleSearch` writes both when checkpointing. `helpers::saveMode` writes the eigenvector as `%.17g` text. `ProcessSearchJob::run` writes `mode.dat` the same way at the end. |
| NEB | Endpoint relax uses the minimization checkpoint. `NudgedElasticBand::compute` keeps images in memory. `NEBMorseTest` restarts from copied `Matter` images. | `eonc::io::writeNebPath` writes the band. |
| Dynamics | `DynamicsJob::run` reads `pos.con` and writes `final.con`. There is no mid-run resume. | `Dynamics::run` appends `dynamics.con` through `matter2con`, which always passes `with_velocities=false`. |
| Hessian | `Hessian::calculateSerial` resumes with `loadColumnCheckpoint` | `saveColumnCheckpoint` writes `eon_hess_ckpt <size> <next_col>` plus a row-major matrix at `precision(17)`. `HessianJob` writes `modes.con` when `write_modes` is set: one frame per mode, Cartesian mode in the displacements section. |
| Instanton | The centroid file is a result, not a stepper resume | `InstantonJob` writes `instanton_centroid.con` with the spreads section. That call is why the client refuses readcon-core older than 0.16. |
| aKMC catalog | `eon/process_catalog.py` reloads a saddle with `load_frame_text` | Reactant, saddle, and product text go into `readcon.db`. The saddle displacements section holds the mode. `pack_frame_key` stores the 12-byte `(traj_id, frame_idx)` key on `amsel.KdbStore`. |
| CPMD potential | `examples/akmc-cpmd-slurm/potfiles/cpmd_extpot.py` | Ionic positions are the `.con` the client already has. The wavefunction is `RESTART.1`, checked with `cpmdc-restart info` when `CPMDC_RESTART` is set. |

`eonc::io::matter2con` and `matter2convel` build a frame in `frame_from_matter`, then write it at `kConPrecision = 17` or `kConvelPrecision = 6` through `write_frames` / `append_frames`. Those helpers construct `readcon::ConFrameWriter` with a decimal precision, which is `FloatFormat::DecimalPlaces`, not the binary64 round-trip writer. `con2matter` then walks `frame.atoms()` one coordinate at a time into Eigen matrices. A clean energy plus a forces section calls `Matter::restoreFileForces` so the next step skips the potential. Geometry-only files set `recomputePotential`.

`mirror_con_corpus` runs only after a full rewrite. Streaming appends return first. The mirror `dlopen`s `libreadcon_db` and calls `rkrdb_open` plus `rkrdb_append_trajectory_str`. The trajectory id is FNV-1a of the absolute path, a NUL, and the entire file text (`ReadconDbMirror.cpp`, and the same function `traj_id` in `eon/concorpus.py`). Each overwrite is a new one-frame trajectory. A movie that grew by append is absent from the corpus. Windows builds compile the mirror out.

Python `eon/fileio.py` `savecon` calls `readcon.write_con_string` with no precision. On 0.17 that default is already round-trip, so a Python save and a C++ checkpoint of the same `Matter` disagree as soon as the wheels move and the client wrap does not. `process_catalog.py` is explicit: `readcon.write_con_string([frame], 17)`.

`helpers::relaxMatter` does not store the optimizer. A resumed minimization reloads coordinates and, only when forces were written, the cached forces. L-BFGS pairs and FIRE velocity start empty. That is the resume eOn has in production today.

### rgsaddle

`frame_from_con` in `src/io.rs` calls `readcon_core::iterators::read_first_frame` and copies positions with `as_f64_row` and masses with `get_f64`. The cell comes from `header.lattice_vectors()` or from lengths and angles. There is no writer, no second frame, and no corpus call. `tests/io_cells.rs` covers two cells.

`BandSession::restart` and `rgsaddle_band_restart` drop FIRE velocity, L-BFGS pairs, and the climbing baseline. They keep endpoint energies and the last evaluation. eOn's `XtsciBand` calls that after `rgsaddle_band_set_positions`. The positions the host can persist are the array behind `rgsaddle_band_positions`. The solver history is not in that array.

A band checkpoint in production is therefore the host's multi-frame `.con` (`writeNebPath`, or the images eOn already holds). rgsaddle 0.14 cannot read that file as a band and cannot write one.

### rgmin

rgmin is the stepper under rgsaddle and under eOn's Xtsci optimizer. `Lbfgs` keeps curvature pairs in `memory`. `FireState` keeps its velocity. `python/rgmin/ase.py` raises `NotImplementedError` when ASE passes `restart=`. The library has no structure type and no campaign.

A preempted minimization resumes from the geometry the host wrote. Rebuilding L-BFGS pairs from a CON unknown-section would couple the stepper to a file format it does not parse, and ASE's `restart=` path is already refused on purpose.

### rgpot

`CppCore/rgpot/rpc/ase_helpers.py` `atoms_from_con` calls `readcon.read_con_as_ase` and optionally attaches a calculator. `tests/con_relax_demo.py` relaxes that atoms object. `tests/eon_min_landscape.py` reads the last frame of `minimization.con` with `readcon.read_con`. Nothing writes a `.con`.

`tests/cpmd_params.py` sets the CPMD input keyword `restart`. That is a deck flag, not a `RESTART.1` reader.

On 0.17.1, `ConFrame.to_ase` attaches stored energy and forces through `SinglePointCalculator`. A 0.14.7 wheel does not. A force-bearing checkpoint loaded by rgpot therefore recomputes, or errors, depending on the ASE version the environment resolved. The pixi floor `>=0.14.7` allows either wheel.

### cpmdc

`cpmdc_restart_read_path` / `cpmdc_restart_read_mem` parse a gfortran sequential unformatted stream. Section 1 is the `STUTTGART VERSION 3.0` header. Coordinates and velocities are Bohr, species-major, in `cpmdc_restart_coordinates` and `cpmdc_restart_velocities`. `cpmdc_restart_set_coordinates` and `cpmdc_restart_set_velocities` rewrite those 24-byte records. `cpmdc_restart_write_mem` / `cpmdc_restart_write_path` leave every other record, including plane-wave coefficients, byte for byte. `tests/test_cpmd_restart.c` checks that rewrite.

`tools/cpmdc_restart.c` exposes `info`, `positions`, `velocities`, `patch-positions`, and `patch-velocities`. Positions print as text. eOn's `cpmd_extpot.py` uses `info` to accept a pooled `RESTART.1`, then copies the binary into the work directory and writes `LATEST`.

The ionic geometry the next eOn or rgpot step needs is inside that binary. The wavefunction the next CPMD call needs is the rest of the same file. A CON file can carry the ions. It cannot carry the coefficients.

### seams-core, as a reader the others must not break

`sinp::readCon` in `src/seams_input.cpp` walks `readcon::ConFrameIterator` and copies coordinates with `rkr_frame_xyz_f64`. `campaignEnvs` opens a sharded `readcon.db` and selects frames through the same reader. seams does not write a restart. A campaign eOn stores has to come back out of `get_frame_text` as CON text this iterator accepts.

## Which feature fills which need

| Need | Feature | Why this one |
| --- | --- | --- |
| A checkpoint written by the C++ client reloads in the Python server, in rgpot, and in rgsaddle with the same f64 bits | Conformant round-trip CON. `create_writer_from_path_round_trip_c`, the default `ConFrameWriter::new`, Python `write_con` / `write_con_string` with `precision=None` and `canonical=True` | Decimal precision 17 and convel precision 6 are the writers in the tree today. They are not bit-exact, and the two eOn languages will diverge on 0.17 defaults. Canonical metadata order is what makes the bytes comparable. |
| Resume a large frame without walking `Atom` objects | Accessors on the parsed frame: `rkr_frame_xyz_f64`, `velocities_f64`, `forces_f64`, `displacements_f64`, `spreads_f64`, and `rkr_frame_copy_*`. C++ `ConFrame::xyz_f64` and the matching methods | `con2matter` and `frame_from_con` copy through per-atom fields. The pointers stay valid until `free_rkr_frame`. Copy into Eigen or `Array1` immediately; do not hold them across `add_atom`. |
| Build that frame without a per-atom setter loop | Builder accessors: `ConFrameBuilder::positions_data`, `velocities_data`, `forces_data`, `displacements_data`, `spreads_data` (`rkr_frame_builder_*_data`) | eOn already prefers `set_*_from_flat` because an `add_atom` reallocates the pointer. The flat setters stay the safe write path. The raw pointers are for a builder whose atom count is already final, which `seed_builder` is. |
| Movie and corpus reads of line-2 JSON | Single-pass `parse_frame_header` | One walk collects `sections`, `validate`, and the remaining metadata. Consumers get it by linking 0.17.1. `metadata_from_frame` should keep using the typed getters (`energy_opt`, `neb_bead_opt`, and the rest) so a resume does not serialize the JSON a second time. |
| Dynamics movie, NEB band, and aKMC history that a later rank fetches by index | readcon-db indexed access: `rkrdb_extend_trajectory_frame`, `rkrdb_get_frame`, `rkrdb_get_frame_text`, `rkrdb_select_campaign` / `rkrdb_select_meta`. Python `ConCorpus.get_frame_text` and `get_frame_texts` | The file stays the client copy. The corpus is how `process_catalog.load_frame_text` and `frame_texts_for_paths` already work. |
| Those histories are long | 64-frame zstd in `frame_codec.rs` (`GROUP_LEN = 64`, tags `0xFD 0x01` / `0x02` / `0x03`, level 1). xxh3-128 stays on the UTF-8 | A group is an internal value. Callers keep using frame index. A one-frame overwrite (`pos_cp.con`) never fills a group; a dynamics or band trajectory does. |
| CPMD wavefunction, Hessian columns, L-BFGS pairs, FIRE velocity, `mode_cp.dat` | Leave them on their current writers | `cpmdc_restart_write_path` already preserves untouched records. `eon_hess_ckpt` is a matrix. `saveMode` is three columns of text the saddle search loads with `loadMode`. Putting any of these into a CON section would make a restart depend on a parser change in every reader, including seams. |

rgmin does not take a readcon dependency. The host writes the geometry rgmin last accepted.

## Per-consumer changes

### readcon-db first, because every corpus reader links it

`Cargo.toml` pins `readcon-core = "=0.17.0"`. Move that to `=0.17.1` so the corpus decoder matches the client writer (empty first header line, `units.time` spelling, `to_ase` forces). Keep `frame_codec::GROUP_LEN` and `corpus::extend_trajectory_frames` as they are. `get_frame_text` must return the UTF-8 that was stored, including when the value is a `0xFD 0x03` group or a `0xFD 0x02` redirect. That is the contract eOn and seams already call.

`src/python.rs` binds `extend_trajectory` to `extend_trajectory_path_units`, which appends every frame of a file. Calling that on a growing movie duplicates frames. Bind `ConCorpus.extend_trajectory_frames` to `corpus::extend_trajectory_frames` so Python can append the one new frame. The C ABI already has `rkrdb_extend_trajectory_frame`.

Ship that as a readcon-db release before eOn bumps `readcon-db>=0.1.6`.

### eOn

Pins:

- `client/meson.build`: `dependency('readcon-core', version: '>=0.17.1')` and the same floor on the subproject.
- `subprojects/readcon-core.wrap`: `revision = v0.17.1`.
- `pyproject.toml` and `pixi.toml`: `readcon>=0.17.1`, and `readcon-db` at the release from the previous step.

Writer, `client/ConFileIO.cpp`:

- Delete `kConPrecision` and `kConvelPrecision` as the production path. `write_frames` and `append_frames` take a round-trip writer: `create_writer_from_path_round_trip_c` or `ConFrameWriter(path)` with no precision argument, then `set_canonical(true)`.
- `matter2con`, `writeNebPath`, and `writeConFrames` use that writer.
- `matter2convel` uses it too. Precision 6 is why `ConFileIOTest` allows `1e-3` on velocities.
- `frame_from_matter` grows a `with_velocities` argument that `Dynamics::run` turns on for `dynamics.con` and for `final.con`. `apply_geometry` already has the velocity loop; it should fill `velocities_data()` after `seed_builder` returns, in one copy from `Matter::getVelocities`.
- `apply_geometry` keeps `set_positions_from_flat`, `set_forces_from_flat`, `set_displacements_from_flat`, and `set_spreads_from_flat`. Those are the bulk setters 0.16 added. They match the accessor layout without holding a pointer across `add_atom`.

Reader, same file, `con2matter(Matter&, const ConFrame&, …)`:

- Copy positions, forces, velocities, displacements, and spreads with `frame.xyz_f64`, `forces_f64`, `velocities_f64`, `displacements_f64`, and `spreads_f64` into the Eigen matrices, then apply `matter_order`. The per-atom `atom.x` loop stays only for symbol, mass, id, and the fixed mask, which are not in those SoA views.
- Keep `restoreFileForces` gated on energy plus a forces section. A geometry-only checkpoint still recomputes.
- `metadata_from_frame` keeps the typed getters. `raw_json` is only for keys those getters do not name.

Checkpoint call sites stay. They already name the files a resume opens:

- `helpers::relaxMatter` writes `{prefix}_cp.con`.
- `MinimizationJob::run` and `MonteCarloJob::run` read `pos_cp.con`.
- `MinModeSaddleSearch` writes `displacement_cp.con`. `SaddleSearchJob::run` reads it only together with `mode_cp.dat`.
- `helpers::saveMode` / `loadMode` stay the mode sidecar.
- `Hessian::saveColumnCheckpoint` / `loadColumnCheckpoint` stay `eon_hess_ckpt`.
- `writeNormalModes` stays the displacements section of `modes.con`.
- `InstantonJob` stays the spreads section of `instanton_centroid.con`.

`Dynamics::run` is the run that does not resume. Add a checkpoint read of the last `dynamics.con` frame (positions and velocities) next to the movie append, gated by `main.checkpoint`, and have `DynamicsJob::run` start from that frame when the file exists. The movie append path is the one that must call the corpus extend below. `final.con` remains the client copy.

Corpus, `client/ReadconDbMirror.cpp` and `eon/concorpus.py`:

- Trajectory id for a path is FNV-1a of the absolute path only. The content hash stays the xxh3-128 readcon-db already stores on the UTF-8, and it stays the dedup key inside one trajectory.
- On a streaming append, call `rkrdb_extend_trajectory_frame` with the `ConFrame` just built. Do not reread the file and do not call `rkrdb_append_trajectory_str` with a new id.
- On a single-frame overwrite (`pos_cp.con`, `final.con`, `displacement_cp.con`), store that blob as frame 0 of the path's trajectory, replacing the previous frame 0. Resume keeps reading the file. The corpus holds the latest checkpoint for `load_frame_text`.
- `mirror_con_text` / `store_frame_text` learn the same split. `process_catalog.py` stops passing `17` to `write_con_string`. The saddle text is `write_con_string([frame], canonical=True)`. `pack_frame_key` is unchanged, so `amsel.KdbStore` rows written after the cutover still unpack with `unpack_frame_key`.
- A missing `libreadcon_db` still leaves the `.con` as the only copy. Resume must not require the corpus. The Windows stub stays a no-op until the dlopen path exists there; the file checkpoint is the resume.

`eon/structure.py` `to_conframe` is the Python builder `savecon` already uses. It does not grow a private writer.

Approval fixtures in `client/unit_tests/data/systems/neb_morse/approval_tests/ApproveConFileIO.*` are regenerated once from the round-trip writer and then frozen. `ConFileIOTest` "convel round-trip" compares velocities with `memcmp` on the f64 payload, not `isApprox(..., 1e-3)`.

### rgsaddle

`Cargo.toml`: `readcon-core = "0.17.1"` on the `readcon` feature. Keep `readcon-db` optional and set it to the release that pins 0.17.1. The feature stays off by default.

`src/io.rs`:

- `frame_from_con` stays the first-frame helper. Point it at 0.17.1 `read_first_frame`. Keep `as_f64_row` / `get_f64`. That is the Rust accessor equivalent of `rkr_frame_xyz_f64`.
- Add `frames_from_con` for a band file: every frame, same cell check, positions stacked in file order. `neb_bead` on the header is the image index when present; otherwise file order is the band order.
- Add `write_band_con`. It writes one canonical round-trip frame per image, with `neb_bead` set, and with forces when `BandSession::evaluation` has a gradient for that image. It does not write solver pairs.

`BandSession::restart` stays the in-memory drop of solver state. A file resume is `frames_from_con`, then `rgsaddle_band_set_positions`, then `rgsaddle_band_restart`. `src/capi.rs` does not grow a disk format. eOn's `XtsciBand` can keep calling those three C functions; the new CON helpers are for hosts that do not already own `writeNebPath`.

The optional `readcon-db` feature, once the release exists, appends the frames from `write_band_con` with `extend_trajectory_frames` under a caller-supplied corpus path. A band shorter than 64 images shares a group with the next stored band of that trajectory. Indexed read is `get_frame_text` by `neb_bead`, then `frames_from_con` on that text.

`tests/io_cells.rs` keeps the two cell cases and adds a two-image write/read whose reloaded positions match the written `Array1` bit for bit.

### rgmin

No `Cargo.toml` change and no new module. `python/rgmin/ase.py` keeps raising when `restart` is set. `Lbfgs` and `FireState` stay in memory.

The host contract, stated in the crate docs next to `Lbfgs::with_capacity`: the process that owns the positions writes them with its own CON writer when it needs a checkpoint. rgmin returns the accepted point through the stepper API the host already has. A test in `tests/python/test_ase.py` (`test_todict_and_restart_refusal`) remains the proof that a restart file is refused.

### rgpot

`pixi.toml`: `readcon>=0.17.1`. There is no `pyproject.toml` dependency today; add the same floor there so a non-pixi install cannot resolve 0.14.7.

`atoms_from_con` stays `read_con_as_ase`. On 0.17.1 a frame that carries forces arrives with a `SinglePointCalculator`, which is the warm start `restoreFileForces` gives the C++ client. Do not strip that calculator unless the caller passed `calc=`.

Add `atoms_to_con` beside it. Build the frame with `ConFrame.from_ase` and write it with `write_con(..., canonical=True)` and no precision argument. Positions must be the binary64 values already on the atoms, not a second formatting pass through ASE's `.con` writer. `tests/con_relax_demo.py` writes the relaxed atoms and reloads them through `atoms_from_con`; the coordinates compare equal with `array_equal`.

`tests/eon_min_landscape.py` keeps reading `minimization.con`. After eOn's writer cutover, that file is round-trip text; this test is one of the cross-repo checks below.

The CPMD `restart` keyword in `cpmd_params.py` stays a deck flag.

An optional corpus helper can call `ConCorpus.extend_trajectory_frames` on the frames `atoms_to_con` just wrote. It is not required for a relaxation. Training-set selection uses `rkrdb_select_meta` (energy window, forces present) and then `get_frame_text`.

### cpmdc

The binary parser does not link readcon. `cpmdc_restart_read_mem`, `cpmdc_restart_set_coordinates`, `cpmdc_restart_set_velocities`, `cpmdc_restart_set_cell`, and `cpmdc_restart_write_path` stay the wavefunction-preserving path. `tests/test_cpmd_restart.c` stays the byte check on records the patch did not touch.

Add an optional tool subcommand in `tools/cpmdc_restart.c`, behind a build that finds `readcon-core` 0.17.1:

- `export-con RESTART.1 OUT.con` reads coordinates and velocities, converts Bohr to angstrom with the factor already documented on `cpmdc_restart.h` (`1/0.529177210859`), and writes one canonical round-trip frame with velocities. Species counts from `cpmdc_restart_species` become the CON type blocks. The cell comes from `cpmdc_restart_cell`.
- `import-con RESTART.1 IN.con OUT` reads the CON with `read_first_frame`, converts angstrom to Bohr, calls `cpmdc_restart_set_coordinates`, `cpmdc_restart_set_velocities`, and `cpmdc_restart_set_cell`, then `cpmdc_restart_write_path`.

`export-con` followed by `import-con` onto a copy of the same `RESTART.1` changes the ionic records and leaves the coefficient records identical to the input. A second `export-con` of that copy matches the first CON byte for byte.

eOn's `cpmd_extpot.py` keeps seeding from `CPMD_RESTART_POOL`. After a client step moves the ions, `import-con` patches the pooled binary from the client `.con` before the next CPMD launch. `restart_matches` stays `cpmdc-restart info`. The pool still stores `RESTART.1`, not a CON. A long ionic history is the client's `dynamics.con` or minimization movie in `readcon.db`, not a copy of the wavefunction.

### seams-core, after the writers

`subprojects/readcon-core.wrap` moves from `91181ef` to `v0.17.1`. The Meson floor `>=0.16.2` already accepts that tag; the wrap revision is what CI builds. `sinp::readCon` and `campaignEnvs` stay. The only change is the pin, plus a test that a round-trip fixture from this design's golden loads through `rkr_frame_xyz_f64` with the same bits. seams does not gain a writer.

## Order of work

1. **Freeze the restart bytes on readcon-core 0.17.1.** Add one multi-section fixture under `resources/conformance/` (cell, two species, forces, velocities, one displacement row, one spread row, line-2 energy). Write it with `create_writer_from_path_round_trip_c` and with Python `write_con_string(..., canonical=True)`. The files are identical. This fixture is the currency for every later step. Single-pass `parse_frame_header` and the accessors are already on this tag; this step only publishes the bytes.
2. **readcon-db pin `=0.17.1` and release.** `get_frame_text` of a 64-frame group, a redirect, and a single `0xFD 0x01` value each return those exact bytes. Bind `extend_trajectory_frames` on the Python module. Ingest and migrate still do not cook.
3. **eOn client and Python in one change.** Wrap, Meson floor, writer, reader accessors, dynamics velocities, corpus id and extend. Regenerate `ApproveConFileIO` once. Old 0.16 fixtures in the client tests must still load: 0.17 reads them. New files are the round-trip spelling.
4. **cpmdc `export-con` / `import-con`.** Depends on the fixture's writer, not on eOn. Then point `cpmd_extpot.py` at `import-con` for the ionic patch.
5. **rgpot `>=0.17.1` and `atoms_to_con`.** Reads the eOn spelling, writes a spelling eOn `con2matter` reloads.
6. **rgsaddle `0.17.1`, `frames_from_con`, `write_band_con`.** Optional corpus append only after step 2 is released. The 0.14 read-only path goes away with the pin; `tests/io_cells.rs` is the regression for cells.
7. **rgmin docs and the existing ASE refusal test.** No waiting on the pin. Can land any time.
8. **seams-core wrap to `v0.17.1`.** Last, so the reader canary sees the golden rather than a mid-migration writer.

A campaign written in step 3 is readable by seams only after step 8. Until then, the `.con` file is the copy seams and a 0.16.2 checkout can be given by hand. Do not point a 0.16.2 seams build at a corpus whose stored text uses 0.17 minor or unit spellings it rejects.

## CI proof

Bit-exact means `cmp` on the file bytes, then `memcmp` on the f64 buffers from `rkr_frame_xyz_f64` / `velocities_f64` / `forces_f64`. A tolerance check does not count. Each job runs the suite it already has, plus the new comparison. A failure of an existing test is a regression even when the new comparison passes.

| Job | Proves | Existing suite that must stay green |
| --- | --- | --- |
| readcon-core | Rust, C (`create_writer_from_path_round_trip_c`), and Python (`write_con_string` with `canonical=True`, precision omitted) emit one byte string for the conformance fixture. Reloading with `parse_frame_header` yields the same f64 buffers. A writer built with `create_writer_from_path_with_precision_c(..., 17)` is asserted to differ, so precision 17 cannot return by accident. | Conformance manifest, current parser tests. |
| readcon-db | Ingest the fixture as 64 copies plus one extra frame. `get_frame_text` for index 0, index 63, and index 64 equals the fixture. The stored value at the group head is one `0xFD 0x03` zstd frame. `zstd_round_trip_is_byte_exact_and_does_not_cook` still passes. A 0.1.8 untagged UTF-8 value still reads. | Crate tests, including `corpus::zstd_round_trip_is_byte_exact_and_does_not_cook`. |
| eOn C++ | `matter2con` of a force-bearing `Matter` matches the fixture bytes for the same numbers. `con2matter` then `memcmp` on positions and forces. `matter2convel` round-trips velocities by `memcmp`. `MinimizationJob` with `checkpoint` writes `pos_cp.con` and a second process loads it. `SaddleSearchJob` resumes only when both `displacement_cp.con` and `mode_cp.dat` exist. `HessianTest` column resume still matches a full finite difference. `dynamics.con` last frame carries velocities and matches `final.con` positions. Append of 65 movie frames, then `rkrdb_get_frame_text`, matches the appended frame bytes. | `ConFileIOTest`, `ApproveConFileIO`, `HessianTest`, `NEBMorseTest`, `DynamicsTest`, `JobIntegrationTest`. |
| eOn Python | `savecon` bytes equal `matter2con` bytes for one shared structure. `process_catalog` stored text equals `write_con_string(..., canonical=True)`. `load_frame_text` returns that text. `from_conframe` / `to_conframe` keep atom ids. | `tests/test_fileio_readcon.py`, `tests/test_structure_readcon.py`, `tests/test_concorpus.py`, `tests/test_process_catalog.py`. |
| rgpot | `atoms_to_con` bytes equal the eOn bytes for the same coordinates. `atoms_from_con` on a force-bearing frame exposes the stored energy and forces on the ASE calculator. `eon_min_landscape.py` reads a 0.17.1 `minimization.con`. | `tests/con_relax_demo.py`, `tests/eon_min_landscape.py`. |
| rgsaddle | `write_band_con` / `frames_from_con` round-trip two images bit-exact, including a non-orthogonal cell. `BandSession::restart` still drops solver state and keeps endpoint energies (`tests/double_well.rs`). | `tests/io_cells.rs`, `tests/double_well.rs`, `tests/cxx_abi.rs`. |
| cpmdc | `export-con` of a fixture `RESTART.1` matches a CON written from the same ions by the round-trip writer. `import-con` back leaves coefficient records identical to the original file (`memcmp` on those slices) and a second export matches the first CON. | `tests/test_cpmd_restart.c`. |
| seams-core | `sinp::readCon` on the conformance fixture returns the same coordinates `rkr_frame_xyz_f64` does. A sharded corpus of that fixture selects the frame. | Existing `.con` reader tests. |
| rgmin | `test_todict_and_restart_refusal` still raises. No CON job. | `tests/python/test_ase.py`. |

Cross-repo order in CI: the conformance fixture is an artifact of step 1. Downstream jobs download those bytes rather than re-encoding expected text in each repo. A consumer job that vendors a private copy of the fixture fails when the bytes drift.

## Risks

- **0.17.0 is a breaking reader.** NaN and Inf are `NonFiniteValue`. Column 4 must be an integer token. A v3 frame needs a valid `units` object. A minor-1 frame with velocities and no `units.time` is `InvalidUnits`. eOn movies and fixtures that used a float fixed flag, a blank numeric, or `time: fs` on a minor-1 velocity frame will fail at resume. Run the 0.16 client fixtures through the 0.17.1 reader before the wrap bump, and fix or quarantine the files that the new parser rejects. That is a data migration, not a tolerance in the reader.
- **The writer spelling changes on purpose.** `ApproveConFileIO` golden files and any hash of a `.con` will move once. After that they are frozen. A campaign stored under the old FNV-of-content trajectory id will not be found by the path-only id. Keep reading old corpora by the stored key; write new frames under the path id. Do not rewrite a live campaign in place during a run.
- **Python and C++ must switch in the same eOn change.** `savecon` omits precision. On a 0.17 wheel that is already round-trip. The C++ client still passes 17 until this change. A mixed deploy writes checkpoints the other language does not byte-match.
- **Velocity cutover.** `kConvelPrecision = 6` and `matter2con`'s `with_velocities=false` mean a dynamics movie from today's client has no velocities. A resume implemented against the new writer cannot continue an old `dynamics.con`. Start new dynamics campaigns on the new writer. Leave an old movie as a geometry history.
- **Accessors dangle if the frame is freed or the builder grows.** `con2matter` copies into Eigen before the `ConFrame` dies. `seed_builder` finishes `add_atom` before any `*_data()` call. The comment in `apply_geometry` about ASAN lifetime is the rule to keep.
- **64-frame groups are not one LMDB value per frame.** Code that reads the `frames` database itself and expects UTF-8 will see `0xFD`. eOn's mirror and `get_frame_text` go through the library, which is the supported path. A random read decodes up to 64 frames. Checkpoint resume of `pos_cp.con` stays on the file, so that decode is not on the stepper's hot path. Movie scrubbing is.
- **`extend_trajectory(path)` on a growing file duplicates frames.** The Python binding that takes a path is the wrong call for an append. Use `rkrdb_extend_trajectory_frame` / `extend_trajectory_frames` with the new frame only.
- **Corpus failure is not a failed step.** `mirror_con_corpus` swallows a missing library. Keep that. A resume that required `readcon.db` would make a client without the library unable to continue a checkpoint it had already written.
- **Windows.** The C++ mirror is compiled out. File checkpoints still work. Do not document the corpus as the resume source.
- **seams at `91181ef` / floor 0.16.2.** It will not parse every 0.17 spelling. Shipping eOn's writer before seams' wrap means a shared campaign can contain text the older seams build rejects. The `.con` file written for the client is still the interchange; seams moves in step 8.
- **readcon-db `=0.17.0` against a 0.17.1 writer.** The empty-header and `units.time` fixes are in 0.17.1. A corpus built on 0.17.0 can disagree with the client on those files. The pin moves before ingest.
- **cpmdc endianness and record markers.** `import-con` may change only the coordinate, velocity, and cell records, through the existing setters. A CON bridge that rewrites the file from scratch will drop the wavefunction. The coefficient `memcmp` in CI is what catches that.
- **Bohr conversion.** The factor on `cpmdc_restart.h` is the OpenCPMD constant, not a rounded 0.529177. Export and import use that constant so the binary records round-trip. The CON holds angstroms, matching eOn. The bits that must match across bindings are the CON bits, not a claim that Bohr and angstrom are the same f64.
- **rgsaddle 0.14 API.** `frame_from_con` uses `positions.as_f64_row`, `masses.get_f64`, and `header.lattice_vectors()`. Confirm those names still compile on 0.17.1 in the same change as the pin. The cell tests are the regression.
- **rgpot's unpinned floor.** `>=0.14.7` resolves forward. CI for steps 5 and 3 should pin the version under test to 0.17.1 so a resolver rollback is visible.
- **Canonical JSON versus a hand-built line 2.** Byte equality fails if one binding sorts metadata keys and another does not. Both writers set canonical mode. A test that compares only coordinates will pass while the campaign hash differs; the `cmp` is on the whole frame.
