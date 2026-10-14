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
| chemparseplot `HaoZeke/chemparseplot` | `4e4095b` | Extras `neb` and `test`, and pixi `feature.test`, pin `readcon>=0.14.5`. No readcon-db. |
| rgpycrumbs `HaoZeke/rgpycrumbs` | `73ddf2e` | Pixi and `ensure_import` pin `readcon>=0.14.5`. Script headers span `0.13.1` to `0.16.0`. No readcon-db. |
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

### chemparseplot

`HaoZeke/chemparseplot` at `4e4095b` is the parser the eOn plot CLIs call. It does not step a geometry. The restart it owes the suite is the CON it writes back, and a movie load that still has the forces eOn stored.

`pyproject.toml` extras `neb` and `test`, and `pixi.toml` `feature.test`, pin `readcon>=0.14.5`. The extra's comment says 0.14.5 is the first wheel that accepts eOn `con_spec_version=3`; 0.13 raises `UnsupportedSpecVersion`. There is no `readcon-db` dependency.

`chemparseplot/parse/eon/con_io.py` is the only CON boundary.

- `read_con_frames` calls `readcon.read_con`. `read_con_as_ase` calls `readcon.read_con_as_ase`. `read_first_atoms` takes the first frame of that full parse, so a one-frame `pos.con` still walks the file.
- `frame_with_energy` builds a new `ConFrame` from `cell`, `angles`, `atoms`, both header pairs, and a metadata dict, then calls `set_energy` or `set_scalar_metadata`. The atoms are the original `Atom` objects, so forces, velocities, displacements, and spreads that live on those atoms stay. The parsed SoA behind the source frame does not travel with the clone.
- `write_con_frames` calls `readcon.write_con` with precision omitted and `canonical` left false.
- `write_atoms_as_con` calls `ConFrame.from_ase`, then `frame_with_energy`. `from_ase` copies positions, the cell, masses, a non-zero velocity array, and forces when `get_forces` succeeds. Displacements and spreads come back empty. Metadata starts empty.
- `_readcon`'s import error still says `readcon>=0.7.0`. `tests/parse/test_readcon_boundary.py` asserts that substring.

`_trajectory_common.load_movie_and_table` reads the movie with `read_con_frames`, converts every frame with `to_ase`, and builds the metric table with `frame_rows_to_table`. `metadata_value` uses `frame.frame_index`, `frame.energy`, and otherwise `frame.metadata.get`. A sidecar TSV is the fallback when that table is empty. `resolve_movie_file` accepts `minimization` or `minimization.con`. `read_first_structure` and `read_optional_first` go through `read_first_atoms`.

`load_min_trajectory` and `parse_min_con` load the minimization movie. `MIN_METADATA_COLUMNS` is `frame_index`, `step_size`, `convergence`, `energy`. The final structure is `{prefix}.con`, then `min.con`, then the last movie frame. `load_dimer_trajectory` loads the climb movie. `DIMER_METADATA_COLUMNS` adds `eigenvalue`, `torque`, `angle`, and `rotations`. The reactant is `reactant.con` or `pos.con`. The saddle is `saddle.con`. `_load_mode_dat` reads `mode.dat` with `np.loadtxt`. `frame_series.atoms_list_from_frames` calls `to_ase` and copies energy onto `atoms.info`. The plot packet is the `ConFrame` sequence. ASE is the adapter.

`stitch_neb_segments` is the writer a later job opens. It reads each segment with `read_con_frames`, shifts energies onto one reactant zero, drops the duplicate junction frame, and stores the kept frames through `_frame_with_energy`. It writes `neb.con` and `neb_path_000.con` with `write_con_frames`, writes `neb_000.dat` with `f_para` set to 0, and writes `sp.con`. A saddle override takes `read_con_frames(sad_path)[0].to_ase()` and `write_atoms_as_con`. The fallback writes the peak frame with `write_con_frames`. Those three CON files are the next inputs for eOn and for rgpycrumbs `plt_neb`.

`parse/surrogate/gpr_optim.py` `_read_saddle` and `read_atom_types` call `ase.io.read(..., format="eon")` on `cell/band/band.con` and `cell/saddle/pos.con`. ASE's eon plugin rejects a forces section, so a 0.17 checkpoint becomes `None` or a `ValueError`. `_band_from_h5` reads ChemGP HDF5 (`positions`, `energy`, training rows). That store stays HDF5. `parse/trajectory/neb.py` `load_trajectory` is an ASE trajectory. `parse/sella/saddle_search.py` reads and writes `.traj`. `plot/rings.py` reads XYZ and SDF in `read_structure` and `read_xyz_frames`. `contracts/load_outcome.py` refuses a payload that contains positions; the record is job type and status, and the comment on that refusal is that trajectories stay readcon frames.

`chemparseplot.api` exports ORCA and XYZ helpers. It does not define `load_trajectory`, `plot_con_overview`, or `plot_con_overlay`. `rgpycrumbs/eon/plt_con.py` imports those three names. `tests/test_plt_con.py` supplies them with a mock module. A real `plt-con` invocation against this commit fails at import.

On 0.17.1, `ConFrame.to_ase` attaches stored energy and forces with `SinglePointCalculator`. The 0.14.5 wheel does not. `load_movie_and_table` and `atoms_list_from_frames` call `to_ase` on every frame of a force-bearing movie. Under ASE 3.29 the old wheel errors. The floor `>=0.14.5` allows either wheel.

### rgpycrumbs

`HaoZeke/rgpycrumbs` at `73ddf2e` is the CLI over those parsers, plus three writers that emit eOn job inputs. Pixi and `rgpycrumbs/_aux.py` `ensure_import` pin `readcon>=0.14.5`. There is no `readcon-db` dependency. The PEP 723 floors disagree with that pin and with each other: `plt_con.py` says `>=0.13.1`, `tls_pairs.py` `>=0.14.9`, `modes_tensormap.py` `>=0.15.0`, `pimd_centroid.py` `>=0.16.0`, and `con_splitter.py`, `gen_dimer.py`, `plt_kmc.py`, `plt_min.py`, `plt_neb.py`, `plt_neb_stitch.py`, and `plt_saddle.py` say `>=0.14.5`. `uv run` of one script can resolve a different wheel than the pixi environment.

| Call | What it reads | What it writes | What the next eOn job opens |
| --- | --- | --- | --- |
| `con_splitter` | `_read_trajectory_frames` uses `read_con`, `to_ase`, and copies `frame.energy` onto `atoms.info`. A non-CON path uses `ase.io.read(index=":")`. | Unchanged geometry: `_write_con_frame` writes the original `ConFrame`, calling `set_energy` when the atoms carry an energy. Center or align: `ConFrame.from_ase` of the moved atoms. A non-CON input uses `_write_con_atoms`. `write_con` omits precision and leaves `canonical` false. `ipath.dat` lists the paths. | `ipath_NNN.con`. A sliced band that was not moved can be the original frame. A centered or aligned image loses displacements and spreads. Forces survive only when `to_ase` left a calculator `from_ase` can read. |
| `seed_dimers_from_peaks`, via `gen_dimer.py` | `read_con` of `neb.con`. Energy is `ConFrame.energy`, else a sibling `neb.dat` or the latest `neb_NNN.dat`. | `pos.con` is `write_con` of the original peak frame. `displacement.con` is `ConFrame.from_ase` of the peak positions plus `_DISPLACE_MAGNITUDE * mode` (`0.01`). `direction.dat` is `np.savetxt` with `fmt="%18.12f"`. `config.ini` goes through `write_eon_config`. | `SaddleSearchJob` reads `pos.con`. The mode stays in `direction.dat`, the same role as `mode_cp.dat`. `displacement.con` is a finite-difference geometry. On 0.17.1, `to_ase` puts the peak forces on a `SinglePointCalculator`, `Atoms.copy` keeps that calculator, and `from_ase` writes those forces onto the moved positions. |
| `pimd_centroid.main` | `_template` reads the reference `.con` for symbol, mass, fixed flags, cell, and angles. Bead files are CPMD `TRAJECTORY` text or xyz. Velocities in the CPMD file are ignored. | `build_frames` sets `sx`, `sy`, and `sz` on each `Atom`. `write_con` writes `centroid.con`, the default `--out`. | eOn reads the spreads section. The script already requires readcon 0.16 for that section. The writer is still the non-canonical default. |
| `modes_tensormap.read_modes` | `read_con`, `frame.disp`, and metadata `mode_eigenvalue`, `hbar_omega`, `wavenumber`. | `modes.mts` through `metatensor.save`. | No CON write. |

Readers that leave the run directory as they found it:

- `load_profile_rows` parses every frame of a `.con` band for `reaction_coordinate`, `relative_energy`, `parallel_force`, and `reaction_coordinate_mw` when `mass_weighted` is set. `neb_bead` and `lowest_eigenvalue` come from metadata. A legacy `neb_*.dat` uses `np.loadtxt`.
- `tls_pairs._atoms` is `read_con(path)[0].to_ase()` on `procdata/reactant_N.con`, `saddle_N.con`, and `product_N.con`. `_band_values` parses the whole `neb.con` and keeps the first frame's metadata when `tunnel_splitting` is present. The aKMC state stays the directory tree: `states/N/processtable` and `procdata`.
- `collect_kmc_n2_timeline` reads `states/{id}/reactant.con` with `read_con`, takes frame 0, calls `to_ase`, and counts ejected N2. A missing file reuses the previous count. `dynamics.txt` is the timeline.
- `uma/_io.load_atoms` sends `.con` and `.convel` through `read_con` and `frames[0].to_ase()`. The UMA weights stay a torch checkpoint.
- `plt_min` calls `load_min_trajectory`. `plt_neb` and `plt_saddle` call `load_dimer_trajectory`. `plt_saddle` also calls `readcon.read_con_as_ase` for a reference product. `plt_neb_stitch` calls `stitch_neb_segments`. `plt_con` is the import of the three missing `chemparseplot.api` names.
- `xts/saddle/cuh2.py` `_cuh2_min` and `xts/cuh2/datgen.py` `get_from_gitroot_con` call `ase.io.read` on `cuh2.con`. The format comes from the extension, which selects ASE's eon plugin.

No call site opens `readcon.db`. A minimization movie, a band, and an aKMC state tree are read by parsing each file from the first byte.

### seams-core, as a reader the others must not break

`sinp::readCon` in `src/seams_input.cpp` walks `readcon::ConFrameIterator` and copies coordinates with `rkr_frame_xyz_f64`. `campaignEnvs` opens a sharded `readcon.db` and selects frames through the same reader. seams does not write a restart. A campaign eOn stores has to come back out of `get_frame_text` as CON text this iterator accepts.

## Which feature fills which need

| Need | Feature | Why this one |
| --- | --- | --- |
| A checkpoint written by the C++ client reloads in the Python server, in rgpot, in rgsaddle, in chemparseplot, and in rgpycrumbs, and a CON those last two write reloads in the C++ client, with the same f64 bits | Conformant round-trip CON. `create_writer_from_path_round_trip_c`, the default `ConFrameWriter::new`, Python `write_con` / `write_con_string` with `precision=None` and `canonical=True` | Decimal precision 17 and convel precision 6 are the eOn writers today. chemparseplot `write_con_frames` and rgpycrumbs `write_con` omit precision and leave `canonical` false, so a stitched band and a seed `pos.con` disagree with the client on key order. Canonical metadata order is what makes the bytes comparable. |
| Resume a large frame without walking `Atom` objects | Accessors on the parsed frame: `rkr_frame_xyz_f64`, `velocities_f64`, `forces_f64`, `displacements_f64`, `spreads_f64`, and `rkr_frame_copy_*`. C++ `ConFrame::xyz_f64` and the matching methods | `con2matter` and `frame_from_con` copy through per-atom fields. The pointers stay valid until `free_rkr_frame`. Copy into Eigen or `Array1` immediately; do not hold them across `add_atom`. |
| Build that frame without a per-atom setter loop | Builder accessors: `ConFrameBuilder::positions_data`, `velocities_data`, `forces_data`, `displacements_data`, `spreads_data` (`rkr_frame_builder_*_data`) | eOn already prefers `set_*_from_flat` because an `add_atom` reallocates the pointer. The flat setters stay the safe write path. The raw pointers are for a builder whose atom count is already final, which `seed_builder` is. |
| Movie and corpus reads of line-2 JSON | Single-pass `parse_frame_header` | One walk collects `sections`, `validate`, and the remaining metadata. Consumers get it by linking 0.17.1. `metadata_from_frame` should keep using the typed getters (`energy_opt`, `neb_bead_opt`, and the rest) so a resume does not serialize the JSON a second time. |
| Dynamics movie, NEB band, and aKMC history that a later rank fetches by index | readcon-db indexed access: `rkrdb_extend_trajectory_frame`, `rkrdb_get_frame`, `rkrdb_get_frame_text`, `rkrdb_select_campaign` / `rkrdb_select_meta`. Python `ConCorpus.get_frame_text` and `get_frame_texts`. A one-frame read uses `read_nth_frame` / `read_first_frame` | The file stays the client copy. The corpus is how `process_catalog.load_frame_text` and `frame_texts_for_paths` already work. chemparseplot `load_movie_and_table` and rgpycrumbs `load_profile_rows`, `collect_kmc_n2_timeline`, and `_band_values` select the same histories. They read the `.con` when the corpus is absent. |
| Those histories are long | 64-frame zstd in `frame_codec.rs` (`GROUP_LEN = 64`, tags `0xFD 0x01` / `0x02` / `0x03`, level 1). xxh3-128 stays on the UTF-8 | A group is an internal value. Callers keep using frame index. A one-frame overwrite (`pos_cp.con`) never fills a group; a dynamics or band trajectory does. |
| CPMD wavefunction, Hessian columns, L-BFGS pairs, FIRE velocity, `mode_cp.dat`, `direction.dat`, `mode.dat`, `neb_*.dat`, `dynamics.txt`, ChemGP HDF5, UMA torch weights | Leave them on their current writers | `cpmdc_restart_write_path` already preserves untouched records. `eon_hess_ckpt` is a matrix. `saveMode` is three columns of text the saddle search loads with `loadMode`. rgpycrumbs `direction.dat` and chemparseplot `mode.dat` are that same sidecar. ChemGP training rows stay HDF5. The UMA checkpoint stays a torch file. Putting any of these into a CON section would make a restart depend on a parser change in every reader, including seams. |

rgmin does not take a readcon dependency. The host writes the geometry rgmin last accepted. chemparseplot and rgpycrumbs take the 0.17.1 wheel. They read eOn's corpus with `get_frame_text` when that database is already beside the job. They do not create a second one. The `.con` file remains the copy a plot can open without the database.

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

### chemparseplot

Pins, in one change:

- `pyproject.toml` extras `neb` and `test`: `readcon>=0.17.1`.
- `pixi.toml` `[feature.test.pypi-dependencies]`: the same floor.
- `con_io._readcon` and `tests/parse/test_readcon_boundary.py` `test_con_io_is_single_readcon_entry_point`: the install hint names `0.17.1`. The assertion moves with the string.

`chemparseplot/parse/eon/con_io.py`:

- `write_con_frames` calls `readcon.write_con(path, frames, canonical=True)` and omits `precision`. That is the round-trip writer.
- An energy-only edit stays on `frame_with_energy`. That clone keeps the source `Atom` objects, which is how a stitched image keeps its forces, velocities, displacements, and spreads.
- `write_atoms_as_con` stays `from_ase` for a geometry that was born as ASE atoms and never had those sections.
- Add `read_nth_con_frame`, bound to `readcon.read_nth_frame`. `read_first_atoms` uses index 0. A full movie stays `read_con`, or `iter_con` inside `load_movie_and_table`, with one frame resident at a time.
- `metadata_value` keeps `frame.energy` and `frame.frame_index`. Other keys stay `frame.metadata.get`. The line-2 JSON is not walked a second time.

`stitch.py`:

- `neb.con` and `neb_path_000.con` stay `write_con_frames`, which now passes `canonical=True`.
- A saddle override writes `sp.con` with `write_con_frames` of `frame_with_energy(saddle_frame, referenced_energy)`. The override file's atoms stay the atoms. `to_ase` stays on the band, where `_cumulative_rmsd` needs positions.
- `neb_000.dat` stays the sidecar. Its `f_para` column stays 0. That column is not copied into the CON.

`gpr_optim.py`:

- `_read_saddle` and `read_atom_types` call `con_io.read_first_atoms` for a `.con`. Positions and atomic numbers come from that atoms object. A forces section is then the 0.17.1 parser's job, which already accepts it.
- `_band_from_h5` stays HDF5.

`chemparseplot/api.py` gains the three names `plt_con` already imports:

- `load_trajectory(path)` reads a native CON through `con_io.read_con_frames` and returns an object with `energies`, `n_frames`, `source`, and `table`. `source` is `con`. `table` carries `fmax` from `forces_array` when the frame has forces. That is the column `plt_con._has_forces` checks.
- `plot_con_overview` and `plot_con_overlay` take that object and draw from the frame sequence. `parse/trajectory/neb.py` `load_trajectory` stays the ASE-trajectory helper. The api name is the CON reader `plt_con` calls.

`load_min_trajectory`, `load_dimer_trajectory`, and `frame_series` keep calling `to_ase`. On 0.17.1 a force-bearing frame arrives with `SinglePointCalculator`. That calculator is what the force panel reads. Leave it attached.

Optional corpus, only when `readcon.db` already sits beside the job and the path is the trajectory eOn stored: `load_movie_and_table` may take `ConCorpus.get_frame_text` by index. A missing database, or a file the mirror never stored, reads the `.con`. This package does not create a corpus.

`mode.dat`, ChemGP HDF5, Sella `.traj`, and the rings XYZ and SDF readers stay on their current parsers.

Tests compare file bytes and use `array_equal`. The existing energy checks stay green:

- `tests/parse/test_con_io.py`: `write_con_frames` of a force-bearing frame matches the conformance fixture bytes for the same numbers. The reloaded `forces_array` matches with `array_equal`.
- `tests/parse/test_neb_stitch.py`: an unshifted one-segment `neb.con` matches the input frame bytes aside from the energy metadata the stitch rewrites. A saddle-override `sp.con` still has a forces section when the saddle file had one.
- `tests/parse/test_min_trajectory.py`, `test_dimer_trajectory.py`, and `test_frame_series.py`: `to_ase` on a force-bearing frame exposes energy and forces on the calculator.
- `tests/parse/test_surrogate_gpr_optim.py`: `read_atom_types` on a `.con` that contains a forces section returns the atomic numbers.
- `tests/parse/test_readcon_boundary.py` stays the guard that eOn parse modules do not call `ase.io.write`.
- A test next to `test_con_io.py` builds the object `load_trajectory` returns for a two-frame file and checks `n_frames == 2` and a finite `fmax` when forces are present.

### rgpycrumbs

Pins, in one change, so a PEP 723 script and the library resolve the same wheel:

- `pixi.toml`: `readcon>=0.17.1`.
- `rgpycrumbs/_aux.py` `_DEPENDENCY_MAP["readcon"]`: `readcon>=0.17.1`.
- The PEP 723 headers on `con_splitter.py`, `gen_dimer.py`, `modes_tensormap.py`, `pimd_centroid.py`, `plt_con.py`, `plt_kmc.py`, `plt_min.py`, `plt_neb.py`, `plt_neb_stitch.py`, `plt_saddle.py`, and `tls_pairs.py`, and the dependency comment in `uma/prepare_aoti.py`. `plt_con.py` moves off `0.13.1`. `pimd_centroid.py` moves off `0.16.0`, because spreads are already in 0.17.1. `modes_tensormap.py` moves off `0.15.0`.
- `ensure_import("chemparseplot")` and the `plt_*.py` headers `chemparseplot[neb,plot]>=1.9.17,<2` move to the chemparseplot release that contains `api.load_trajectory` and the 0.17.1 pin.

`eon/con_splitter.py`:

- `_write_con_frame` and `_write_con_atoms` call `write_con(..., canonical=True)` and omit precision.
- Unchanged geometry keeps writing the original frame. That is the bit-exact `ipath_NNN.con` when the splitter only slices.
- Center is a rigid translation. After `from_ase`, copy `fx`/`fy`/`fz`, `dx`/`dy`/`dz`, and `sx`/`sy`/`sz` from the source frame's atoms onto the new atoms, then `set_energy`. A pure shift leaves Cartesian forces, displacements, and spreads unchanged, so those arrays match the source with `array_equal`. The file bytes differ because the coordinates moved.
- Align can rotate and reorder. That path writes the new positions and leaves forces, displacements, and spreads unset, so the next eOn step recomputes.
- `_apply_frame_energy` calls `set_energy` on the existing frame. The constructor fallback stays for a wheel that has no setter. On 0.17.1 the setter exists, so that is the path the splitter takes.

`eon/seed_dimers.py`:

- `pos.con` stays `write_con([peak_frame], canonical=True)`. The bytes match that source image. `SaddleSearchJob` reads this file.
- `displacement.con` is a new geometry. Clear the calculator on the displaced atoms before `from_ase`, then `write_con(..., canonical=True)`. The peak forces stay off that file, and eOn recomputes at the moved point. Reloaded positions equal the peak plus `0.01 * mode`, compared with `array_equal`.
- `direction.dat` stays `np.savetxt` with `fmt="%18.12f"`. It is the mode sidecar.
- `config.ini` stays `write_eon_config`.

`eon/pimd_centroid.py`:

- `build_frames` stays the `Atom(..., sx=, sy=, sz=)` constructor. That is the spreads section.
- `main` calls `write_con(..., canonical=True)`.
- `_template` uses `read_first_frame`. It copies symbol, mass, fixed flags, cell, and angles from that frame.

`eon/modes_tensormap.py`:

- `read_modes` stays `frame.disp` and the three metadata keys. There is no CON writer. The pin is what lets it read a 0.17.1 `modes.con`. The TensorMap stays `modes.mts`.

`eon/helpers.py` `load_profile_rows`:

- The metadata keys stay. The read goes through `iter_con`, so a long band builds one frame at a time.
- When the corpus from the eOn cutover contains that path, `get_frame_text` by index replaces the file walk. The `.con` is the fallback.

`eon/tls_pairs.py`:

- `_atoms` uses `read_first_frame`, then `to_ase`. These process files are single-frame.
- `_band_values` uses `read_first_frame` and reads `tunnel_splitting` from that frame's metadata.

`eon/plt_kmc.py` `collect_kmc_n2_timeline`:

- `read_first_frame` of `reactant.con`, then `to_ase`. A missing file still reuses the previous count.
- When eOn's corpus has that path, `get_frame_text` of frame 0 is the read. The directory of `.con` files still works when the corpus is absent. `dynamics.txt` stays the timeline.

`uma/_io.py` `load_atoms`:

- `.con` and `.convel` use `read_first_frame`, then `to_ase`. The torch checkpoint stays a torch file.

`xts/saddle/cuh2.py` `_cuh2_min` and `xts/cuh2/datgen.py` `get_from_gitroot_con`:

- Read `cuh2.con` with `read_first_frame` and `to_ase`.

`plt_min`, `plt_neb`, `plt_saddle`, and `plt_neb_stitch` keep calling chemparseplot. `plt_con` keeps importing `chemparseplot.api`. It runs once that API exists. Its own `readcon` floor still moves, because a script-level `0.13.1` beside chemparseplot's `0.17.1` writes a seed in the old spelling.

This package does not create a `ConCorpus`. The optional reads use the corpus eOn already mirrors.

Tests:

- `tests/test_con_splitter_readcon.py`: an unmoved split of a force-bearing frame matches `write_con([frame], canonical=True)` of that frame. A centered split keeps `forces_array` equal to the source.
- `tests/test_seed_dimers.py`: `pos.con` bytes equal `write_con([peak_frame], canonical=True)`. `displacement.con` reloads positions equal to the peak plus `0.01 * mode`, and `has_forces` is false. `direction.dat` stays the text file.
- `tests/test_pimd_centroid.py`: reloaded spreads match the arrays passed to `build_frames` with `array_equal`.
- `tests/test_modes_tensormap.py`: `frame.disp` still fills the TensorMap.
- `tests/test_neb_profile_rows.py`, `tests/test_tls_pairs.py`, and `tests/test_plt_kmc.py`: the first-frame helpers return the same metadata and the same ejected-N2 count.
- `tests/test_plt_con.py` stays the mock of `chemparseplot.api` until that module exports the three names. The real two-frame `fmax` check lives in chemparseplot, next to `load_trajectory`.

### seams-core, after the writers

`subprojects/readcon-core.wrap` moves from `91181ef` to `v0.17.1`. The Meson floor `>=0.16.2` already accepts that tag; the wrap revision is what CI builds. `sinp::readCon` and `campaignEnvs` stay. The only change is the pin, plus a test that a round-trip fixture from this design's golden loads through `rkr_frame_xyz_f64` with the same bits. seams does not gain a writer.

## Order of work

1. **Freeze the restart bytes on readcon-core 0.17.1.** Add one multi-section fixture under `resources/conformance/` (cell, two species, forces, velocities, one displacement row, one spread row, line-2 energy). Write it with `create_writer_from_path_round_trip_c` and with Python `write_con_string(..., canonical=True)`. The files are identical. This fixture is the currency for every later step. Single-pass `parse_frame_header` and the accessors are already on this tag; this step only publishes the bytes.
2. **readcon-db pin `=0.17.1` and release.** `get_frame_text` of a 64-frame group, a redirect, and a single `0xFD 0x01` value each return those exact bytes. Bind `extend_trajectory_frames` on the Python module. Ingest and migrate still do not cook.
3. **eOn client and Python in one change.** Wrap, Meson floor, writer, reader accessors, dynamics velocities, corpus id and extend. Regenerate `ApproveConFileIO` once. Old 0.16 fixtures in the client tests must still load: 0.17 reads them. New files are the round-trip spelling.
4. **cpmdc `export-con` / `import-con`.** Depends on the fixture's writer, not on eOn. Then point `cpmd_extpot.py` at `import-con` for the ionic patch.
5. **rgpot `>=0.17.1` and `atoms_to_con`.** Reads the eOn spelling, writes a spelling eOn `con2matter` reloads.
6. **chemparseplot `>=0.17.1`.** `con_io` writes canonical round-trip text, `api.load_trajectory` is the movie `plt_con` already imports, stitch keeps force and displacement sections on `neb.con` and `sp.con`, and `gpr_optim` reads `.con` through `con_io`. Depends on the fixture from step 1 and on the eOn spelling from step 3. Can land beside step 5.
7. **rgpycrumbs `>=0.17.1`.** Script floors, the splitter, seed `pos.con`, PIMD spreads, and the first-frame readers. Depends on step 6, because `plt_con` and `plt_neb_stitch` call chemparseplot. An unmoved `ipath_*.con` and a seed `pos.con` must be text step 3's `con2matter` accepts bit for bit.
8. **rgsaddle `0.17.1`, `frames_from_con`, `write_band_con`.** Optional corpus append only after step 2 is released. The 0.14 read-only path goes away with the pin; `tests/io_cells.rs` is the regression for cells.
9. **rgmin docs and the existing ASE refusal test.** No waiting on the pin. Can land any time.
10. **seams-core wrap to `v0.17.1`.** Last, so the reader canary sees the golden rather than a mid-migration writer.

A campaign written in step 3 is readable by seams only after step 10. Until then, the `.con` file is the copy seams and a 0.16.2 checkout can be given by hand. Do not point a 0.16.2 seams build at a corpus whose stored text uses 0.17 minor or unit spellings it rejects.

## CI proof

Bit-exact means `cmp` on the file bytes, then `memcmp` on the f64 buffers from `rkr_frame_xyz_f64` / `velocities_f64` / `forces_f64`. A tolerance check does not count. Each job runs the suite it already has, plus the new comparison. A failure of an existing test is a regression even when the new comparison passes.

| Job | Proves | Existing suite that must stay green |
| --- | --- | --- |
| readcon-core | Rust, C (`create_writer_from_path_round_trip_c`), and Python (`write_con_string` with `canonical=True`, precision omitted) emit one byte string for the conformance fixture. Reloading with `parse_frame_header` yields the same f64 buffers. A writer built with `create_writer_from_path_with_precision_c(..., 17)` is asserted to differ, so precision 17 cannot return by accident. | Conformance manifest, current parser tests. |
| readcon-db | Ingest the fixture as 64 copies plus one extra frame. `get_frame_text` for index 0, index 63, and index 64 equals the fixture. The stored value at the group head is one `0xFD 0x03` zstd frame. `zstd_round_trip_is_byte_exact_and_does_not_cook` still passes. A 0.1.8 untagged UTF-8 value still reads. | Crate tests, including `corpus::zstd_round_trip_is_byte_exact_and_does_not_cook`. |
| eOn C++ | `matter2con` of a force-bearing `Matter` matches the fixture bytes for the same numbers. `con2matter` then `memcmp` on positions and forces. `matter2convel` round-trips velocities by `memcmp`. `MinimizationJob` with `checkpoint` writes `pos_cp.con` and a second process loads it. `SaddleSearchJob` resumes only when both `displacement_cp.con` and `mode_cp.dat` exist. `HessianTest` column resume still matches a full finite difference. `dynamics.con` last frame carries velocities and matches `final.con` positions. Append of 65 movie frames, then `rkrdb_get_frame_text`, matches the appended frame bytes. | `ConFileIOTest`, `ApproveConFileIO`, `HessianTest`, `NEBMorseTest`, `DynamicsTest`, `JobIntegrationTest`. |
| eOn Python | `savecon` bytes equal `matter2con` bytes for one shared structure. `process_catalog` stored text equals `write_con_string(..., canonical=True)`. `load_frame_text` returns that text. `from_conframe` / `to_conframe` keep atom ids. | `tests/test_fileio_readcon.py`, `tests/test_structure_readcon.py`, `tests/test_concorpus.py`, `tests/test_process_catalog.py`. |
| rgpot | `atoms_to_con` bytes equal the eOn bytes for the same coordinates. `atoms_from_con` on a force-bearing frame exposes the stored energy and forces on the ASE calculator. `eon_min_landscape.py` reads a 0.17.1 `minimization.con`. | `tests/con_relax_demo.py`, `tests/eon_min_landscape.py`. |
| chemparseplot | `write_con_frames(..., canonical=True)` of a force-bearing frame matches the conformance fixture bytes. A stitched `neb.con` keeps `forces_array` equal to the source segment aside from the rewritten energy. A saddle-override `sp.con` still has forces when the saddle file had them. `load_trajectory` on a two-frame file reports `n_frames == 2` and a finite `fmax`. `read_atom_types` reads a `.con` that contains a forces section. `to_ase` exposes stored energy and forces on the calculator. | `tests/parse/test_con_io.py`, `test_neb_stitch.py`, `test_min_trajectory.py`, `test_dimer_trajectory.py`, `test_frame_series.py`, `test_surrogate_gpr_optim.py`, `test_readcon_boundary.py`. |
| rgpycrumbs | An unmoved `ipath_*.con` matches `write_con([frame], canonical=True)` of the source frame. A centered split keeps the source forces. Seed `pos.con` matches the peak frame bytes. `displacement.con` reloads the displaced positions and has no forces section. `centroid.con` reloads the spreads passed to `build_frames`. `read_modes` still fills the TensorMap from `frame.disp`. | `tests/test_con_splitter_readcon.py`, `tests/test_seed_dimers.py`, `tests/test_pimd_centroid.py`, `tests/test_modes_tensormap.py`, `tests/test_neb_profile_rows.py`, `tests/test_tls_pairs.py`, `tests/test_plt_kmc.py`. |
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
- **seams at `91181ef` / floor 0.16.2.** It will not parse every 0.17 spelling. Shipping eOn's writer before seams' wrap means a shared campaign can contain text the older seams build rejects. The `.con` file written for the client is still the interchange; seams moves in step 10.
- **readcon-db `=0.17.0` against a 0.17.1 writer.** The empty-header and `units.time` fixes are in 0.17.1. A corpus built on 0.17.0 can disagree with the client on those files. The pin moves before ingest.
- **cpmdc endianness and record markers.** `import-con` may change only the coordinate, velocity, and cell records, through the existing setters. A CON bridge that rewrites the file from scratch will drop the wavefunction. The coefficient `memcmp` in CI is what catches that.
- **Bohr conversion.** The factor on `cpmdc_restart.h` is the OpenCPMD constant, not a rounded 0.529177. Export and import use that constant so the binary records round-trip. The CON holds angstroms, matching eOn. The bits that must match across bindings are the CON bits, not a claim that Bohr and angstrom are the same f64.
- **rgsaddle 0.14 API.** `frame_from_con` uses `positions.as_f64_row`, `masses.get_f64`, and `header.lattice_vectors()`. Confirm those names still compile on 0.17.1 in the same change as the pin. The cell tests are the regression.
- **rgpot's unpinned floor.** `>=0.14.7` resolves forward. CI for steps 5 and 3 should pin the version under test to 0.17.1 so a resolver rollback is visible.
- **chemparseplot and rgpycrumbs floors resolve forward, and the script floors disagree.** Package pins are `>=0.14.5`. `plt_con.py` still says `>=0.13.1`, which rejects eOn `con_spec_version=3`. `pimd_centroid.py` says `>=0.16.0` and `modes_tensormap.py` says `>=0.15.0`. A `uv run` of one script beside a pixi env on another wheel rewrites `pos.con` or `centroid.con` in a spelling eOn's client does not byte-match. Move the pixi pin, `_aux.py`, and every PEP 723 header in the same change, and pin CI at 0.17.1.
- **`from_ase` drops displacements and spreads, and on 0.17.1 it can stamp stale forces.** `to_ase` attaches a `SinglePointCalculator` when the frame has forces. `Atoms.copy` keeps that calculator. `seed_dimers` then moves the positions and `from_ase` writes the peak forces onto the displaced geometry, which `restoreFileForces` would trust. Clear the calculator before that write. `frame_with_energy` is the energy-shift path, because it keeps the source atoms. A stitch or a split that rebuilds the frame with `from_ase` while only the energy changed loses the sections eOn needs to warm-start.
- **ASE `format="eon"` is a second parser.** `gpr_optim._read_saddle`, `read_atom_types`, and the CuH2 example's `ase.io.read` of `cuh2.con` go through ASE's eon plugin. That plugin rejects a forces section. After eOn's writer cutover those calls fail, or they return `None` where `_read_saddle` swallows the exception. They move to `con_io` / `read_first_frame` in the same pin bump.
- **`chemparseplot.api` does not yet export the names `plt_con` imports.** `load_trajectory`, `plot_con_overview`, and `plot_con_overlay` are absent at `4e4095b`. rgpycrumbs tests mock the module. Landing the rgpycrumbs pin before the chemparseplot API leaves `plt-con` failing at import, and leaves `plt_neb_stitch` writing `neb.con` with the old non-canonical `write_con`. chemparseplot is step 6. rgpycrumbs is step 7.
- **`test_con_io_is_single_readcon_entry_point` locks the `readcon>=0.7` hint.** Updating the install string without the assertion, or the assertion without the string, fails that test. They move together. The 0.7 fallback inside `frame_with_energy` and `_apply_frame_energy` stays source-compatible. Production on 0.17.1 takes `set_energy`.
- **Canonical JSON versus a hand-built line 2.** Byte equality fails if one binding sorts metadata keys and another does not. Both writers set canonical mode. A test that compares only coordinates will pass while the campaign hash differs; the `cmp` is on the whole frame. chemparseplot `write_con_frames` and rgpycrumbs `write_con` pass `canonical=True` explicitly, because the Python default is false.
