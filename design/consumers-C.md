# Consumers C: one crate and one C ABI

The shared layer is a new crate, `readcon-xfer`, with a C ABI in `include/readcon-xfer.h`. It is the only new library. rgmin, rgsaddle, and the eOn client link it. The eOn Python server, rgpot, chemparseplot, and rgpycrumbs call the same bytes through the `readcon` 0.17.1 wheel and `readcon-db`. For the plot stack that call sequence lives in `chemparseplot.parse.eon.con_io`, and rgpycrumbs calls that module. cpmdc and seams-core call the C ABI for ionic frames.

`readcon-xfer` does not parse CON and does not own a file format. A restart is the RoundTrip CON UTF-8 of one frame. A checkpoint is that file plus the same UTF-8 stored in a corpus. A trajectory is a concatenation of those frames on disk and one `traj_id` whose `frame_idx` values are read back by index. The 64-frame zstd group already implemented in readcon-db is how a trajectory is stored. The single-pass parse and the SoA accessors already on readcon-core `main` (0.17.1) are how a frame is read.

Shallow clones this design was written from:

| Repository | Commit |
| --- | --- |
| lode-org/readcon-core `main` | `96fd38f66cad` (tag `v0.17.1`) |
| lode-org/readcon-db `main` | `0725c94a36ba` |
| TheochemUI/eOn | `cc4f69982610` |
| OmniPotentRPC/rgmin | `2560f834b4fa` |
| OmniPotentRPC/rgsaddle | `ffe54d487ce2` |
| OmniPotentRPC/rgpot | `b901b09b92f0` |
| OmniPotentRPC/cpmdc | `c518e1e07bbd` |
| d-SEAMS/seams-core | `305fb3c67c39` |
| HaoZeke/chemparseplot | `4e4095bd70c9` |
| HaoZeke/rgpycrumbs | `73ddf2ebc8ca` |

## What each consumer does today

| Consumer | Restart | Checkpoint | Trajectory |
| --- | --- | --- | --- |
| eOn C++ client | `con2matter` / `convel2matter` via `readcon::read_first_frame`. Wrap pin `v0.16.0`. | `helpers::relaxMatter` writes `prefixCheckpoint + "_cp"` through `matter2con(..., append=false)`. `getRelevantFile` prefers that file. | `relaxMatter` and `MonteCarlo.cpp` append `movie.con`. `writeNebPath` writes a band. `ReadconDbMirror` dlopens `rkrdb_append_trajectory_str`. |
| eOn Python server | `eon.fileio.loadcon` → `readcon.read_first_frame`. Floor `readcon>=0.15`, `readcon-db>=0.1.6`. | `eon.concorpus.mirror_con_text` stores one blob under FNV-1a of path and text. | `savecon(..., w='a')` concatenates `write_con_string` and mirrors only the new frame, as its own one-frame trajectory. |
| rgsaddle | `frame_from_con` → `readcon_core::iterators::read_first_frame`. Cargo pin `readcon-core = "0.14"`. | None. | None. The `readcon-db` feature is declared and unused. |
| rgmin | None. `python/rgmin/ase.py` `Optimizer.read` and `Optimizer.dump` raise `NotImplementedError`. ASE `trajectory=` is ASE's own writer. | None. | None. No readcon dependency. |
| rgpot | `CppCore/rgpot/rpc/ase_helpers.py` `atoms_from_con` → `readcon.read_con_as_ase`. eonviz pin `readcon>=0.14.7`. | None. | None. `tests/eon_min_landscape.py` reads the last frame of `minimization.con` with `readcon.read_con`. |
| chemparseplot | `con_io.read_first_atoms` loads every frame with `read_con_as_ase` and keeps index 0. Floor `readcon>=0.14.5` (`pyproject.toml` extras `neb` and `test`, `pixi.toml`). No `readcon-db`. | `write_con_frames` / `write_atoms_as_con` rewrite a whole file with `write_con` and no precision argument. `stitch_neb_segments` writes `sp.con` that way. | `read_con_frames` / `load_movie_and_table` parse a whole movie. `stitch_neb_segments` writes `neb.con` and `neb_path_000.con`. `parse.trajectory.neb.load_trajectory` is ASE extxyz/`.traj`, not CON. |
| rgpycrumbs | Single-frame reads take `read_con(...)[0]` or `read_con_as_ase(...)[0]` (`uma/_io.py` `load_atoms`, `tls_pairs._atoms` and `_band_values`, `plt_kmc.collect_kmc_n2_timeline`, `plt_saddle`, `pimd_centroid._template`, `seed_dimers._match_eon_mode`). `xts/cuh2/datgen.py` `get_from_gitroot_con` and `xts/saddle/cuh2.py` `_cuh2_min` read `cuh2.con` with `ase.io.read`. Floors are `readcon>=0.14.5` in `pixi.toml` and `_aux._DEPENDENCY_MAP`, with PEP 723 floors from `0.13.1` (`plt_con`) through `0.16.0` (PIMD). No `readcon-db`. | `con_splitter._write_con_frame` / `_write_con_atoms` and `seed_dimers_from_peaks` (`pos.con`, `displacement.con`) call `write_con` on one frame. | `con_splitter._read_trajectory_frames` uses `read_con` for a whole band and writes one `ipath_{i:03d}.con` per image. `pimd_centroid.main` writes `centroid.con` with `write_con`. `modes_tensormap.read_modes` reads every `modes.con` frame. `plt_min` / `plt_saddle` / `plt_neb_stitch` open CON only by calling chemparseplot. `plt_con` expects `chemparseplot.api.load_trajectory`, which `chemparseplot/api.py` does not define at this commit. |
| cpmdc | `cpmdc_restart_read_path` / `cpmdc_restart_coordinates` / `cpmdc_restart_velocities` on a gfortran unformatted `RESTART.n`. | `cpmdc_restart_set_coordinates`, `cpmdc_restart_set_velocities`, `cpmdc_restart_write_path`. Other records stay byte-identical. | `cpmdc_last_md_trajectory_row` copies a Hartree energy row. It is not a geometry. |
| seams-core | `sinp::readCon` walks `readcon::ConFrameIterator::nth`. | None. | `sinp::ingestConCorpus` / `sinp::readConCorpus` via `rkrdb_append_trajectory` and `rkrdb_get_frame_text`. |
| readcon-db | Corpus of CON text. | Same. | `frame_codec::GROUP_LEN = 64`. Indexed `ConCorpus::get_frame`. |

Pin facts that the implementation has to start from:

- eOn `subprojects/readcon-core.wrap` is `revision = v0.16.0`. `client/meson.build` asks for `readcon-core` `>=0.16.0` because `ConFileIO.cpp` calls `set_spreads_from_flat`.
- seams-core `subprojects/readcon-core.wrap` is `91181ef2699ef4c46fd7827cee1127776a32aa55`, which is `v0.16.2~2`. `subprojects/readcon-db.wrap` is `0001a2c5a931bdde6bc8fe9b308f666dc28f4fe5` (readcon-db 0.1.8), and that commit's `Cargo.toml` has `readcon-core = "=0.16.1"`.
- readcon-db `main` has already moved to `readcon-core = "=0.17.0"` and ships the 64-frame codec. The remaining pin move on that crate is `0.17.0` to `0.17.1`.
- chemparseplot and rgpycrumbs do not depend on `readcon-db`. Their CON writes already omit `precision`, so on a 0.17.1 wheel they are RoundTrip. Their reads are `read_con` of the whole file, including when the caller keeps only frame 0.

eOn's C++ writer is the byte divergence that the shared layer removes. `client/ConFileIO.cpp` passes `kConPrecision = 17` and `kConvelPrecision = 6` into `ConFrameWriter`. Those are decimal-place writers. readcon-core 0.17.1's default, `writer::FloatFormat::RoundTrip` (`CON-num.6`), is what Python `write_con` uses when `precision` is omitted. A frame written by the client and a frame written by the server are not the same UTF-8.

## Substrate the crate is allowed to call

### readcon-core 0.17.1

Single pass over the frame being restarted:

- `iterators::read_first_frame` stops after the first frame. This is the restart read of a CON path.
- `iterators::read_nth_frame` / `ConFrameIterator::skip_frames` then `next` parses one selected frame. `forward_fast` skips the others without building atoms.
- `ConFrameIterator::next_with_raw_span` is the ingest pass: one parse, and the UTF-8 span that was parsed is the blob that is stored.
- `readcon_db::corpus::ConCorpus::get_frame` loads one indexed value and runs `ConFrameIterator::next` on that frame's UTF-8.

Accessors, which are the only numeric reads:

- Rust: `positions.as_f64_row`, `velocities.as_f64_row`, `forces.as_f64_row`.
- C: `rkr_frame_xyz_f64`, `rkr_frame_velocities_f64`, `rkr_frame_forces_f64` (and the `*_view` twins). `free_rkr_frame` releases the handle.
- C++: `readcon::ConFrame::xyz_f64`, and the velocity and force views on the same handle.
- Python, on a freshly parsed frame: `ConFrame.coords_array`, `velocities_array`, `forces_array`, `atom_ids_array`.

Write path: `ConFrameWriter::new` / `FloatFormat::RoundTrip` / `FloatFormat::default`. The crate has no precision argument and does not call `from_path_with_precision`.

### readcon-db

On-disk frame values, from `src/frame_codec.rs`:

- One frame: `0xFD 0x01` plus one zstd frame of the CON UTF-8, level 1, when that is shorter than the text.
- An aligned run of `GROUP_LEN` (64) frames: `0xFD 0x03` plus one zstd frame of length-prefixed UTF-8, when the group is shorter than the per-frame values. Other keys in the run are `0xFD 0x02` redirects.
- xxh3-128 is taken on each frame's UTF-8, not on the compressed bytes.

Indexed read is `ConCorpus::get_frame(FrameKey { traj_id, frame_idx })`, which calls `get_frame_text` → `decode_frame` → one `ConFrameIterator::next`. `rkrdb_get_frame` is the C form. `get_positions` / `rkrdb_get_positions` prefer cooked SoA and are not the restart path. Cooked SoA stays available for callers that already use it. A restart does not read it.

`append_trajectory_str` stores the raw span from `next_with_raw_span`. `extend_trajectory_frames` re-serializes. The crate stores the UTF-8 it wrote to disk, so the extend path has to grow one raw-span sibling. That is the only readcon-db API addition.

## The API

Rust (`readcon_xfer`) and C (`rkrx_*`) are one implementation. C reads return an `RKRConFrame *` owned by the caller and released with `free_rkr_frame`. Status values are `RKRX_OK = 0`, `RKRX_ERR = -1`, `RKRX_EXISTS = -2`, `RKRX_NOT_FOUND = -3`, `RKRX_NULL = -4`.

```rust
pub fn frame_text(frame: &ConFrame) -> Result<String>;
pub fn restart_write(path: &Path, frame: &ConFrame) -> Result<()>;
pub fn restart_read(path: &Path) -> Result<ConFrame>;
pub fn checkpoint_write(path: &Path, corpus: &Path, traj_id: u64, frame: &ConFrame) -> Result<()>;
pub fn checkpoint_read(corpus: &Path, traj_id: u64, frame_idx: u32) -> Result<ConFrame>;
pub fn trajectory_append(path: &Path, corpus: &Path, traj_id: u64, frames: &[ConFrame]) -> Result<u32>;
pub fn trajectory_frame(corpus: &Path, traj_id: u64, frame_idx: u32) -> Result<ConFrame>;
```

```c
int rkrx_frame_text(const struct RKRConFrame *frame, char **out_text, size_t *out_len);
int rkrx_restart_write(const char *path, const struct RKRConFrame *frame);
struct RKRConFrame *rkrx_restart_read(const char *path);
int rkrx_checkpoint_write(const char *path, const char *corpus, uint64_t traj_id,
                          const struct RKRConFrame *frame);
struct RKRConFrame *rkrx_checkpoint_read(const char *corpus, uint64_t traj_id,
                                         uint32_t frame_idx);
int rkrx_trajectory_append(const char *path, const char *corpus, uint64_t traj_id,
                           const struct RKRConFrame *const *frames, uint32_t n,
                           uint32_t *out_count);
struct RKRConFrame *rkrx_trajectory_frame(const char *corpus, uint64_t traj_id,
                                          uint32_t frame_idx);
void rkrx_free_string(char *s);
```

Call map:

| Function | readcon-core | readcon-db |
| --- | --- | --- |
| `frame_text` | `ConFrameWriter::new` into a buffer | |
| `restart_write` | `frame_text`, then truncate the path to that buffer | |
| `restart_read` | `read_first_frame` | |
| `checkpoint_write` | `restart_write` | `append_trajectory_str(traj_id, text, path)`. Identical stored text is success. A different text under the same id returns `RKRX_EXISTS`. |
| `checkpoint_read` | parse inside `get_frame` | `get_frame(FrameKey { traj_id, frame_idx })` |
| `trajectory_append` | `frame_text` per new frame. Concatenate onto an uncompressed path. Do not rewrite earlier bytes. | `append_trajectory_str` when the id is new, otherwise `extend_trajectory_str` of only the new text. `group_prepared` packs each aligned run of 64. |
| `trajectory_frame` | same parse as `checkpoint_read` | same `get_frame` |

`trajectory_append` rejects a gzip or zstd path. Those members cannot grow in place. Callers that still rewrite a compressed movie keep doing that above the crate, then pass the new frame's UTF-8 through `extend_trajectory_str`. The crate never re-serializes a frame the caller did not hand it.

Trajectory ids are the caller's. The crate does not hash paths. eOn keeps its FNV-1a for one-shot blobs so an unchanged checkpoint still hits the same corpus key.

Python has no new module. The same bytes, on `readcon` 0.17.1 and the readcon-db that pins it. `chemparseplot.parse.eon.con_io` is the one implementation of this table for chemparseplot and rgpycrumbs. The eOn server and rgpot call the same functions directly.

| Operation | Calls |
| --- | --- |
| Restart write | `readcon.write_con(path, [frame])` with `precision` omitted |
| Restart read | `readcon.read_first_frame(path)`, then `coords_array` / `velocities_array` / `forces_array` |
| Checkpoint write | `text = readcon.write_con_string([frame])`, write that text to the path, `ConCorpus.append_trajectory_str(traj_id, text, source=path)` |
| Checkpoint or trajectory read | `ConCorpus.get_frame(traj_id, frame_idx)`, then the same three arrays. `get_positions` is not this path. |
| Trajectory append | `write_con_string` of the new frames only, concatenate, `ConCorpus.extend_trajectory_str(traj_id, text, source=path)` |

Bit-exact means three equalities, including signed zero and the subnormals the 0.17.1 writer round-trips:

1. The CON UTF-8 from `rkrx_frame_text`, from `readcon.write_con_string`, and from the bytes `get_frame_text` returns after a zstd group decode.
2. xxh3-128 of that UTF-8, which is the hash `rkrdb_frame_hash` already stores.
3. The `f64` bits from `rkr_frame_xyz_f64` (and the velocity and force accessors) and from the Python arrays, on a frame just parsed from that UTF-8.

A C restart written by eOn must satisfy those three equalities when rgsaddle reads it, when the eOn server reads it, and when rgpot reads it. The Bohr conversion in cpmdc is outside this equality. The CON file is the bit-exact object. Patching a binary `RESTART.n` converts Ångström to Bohr with `CPMDC_RESTART_ANGSTROM_PER_BOHR` and rewrites only the coordinate and velocity records.

Domain types stay in the consumers. `Matter`, `MolecularFrame`, ASE `Atoms`, a point cloud, and a `cpmdc_restart` are built on either side of the crate. The crate sees a `ConFrame` or an `RKRConFrame *`.

## Per-consumer changes

### readcon-db, before any consumer

File `Cargo.toml`: `readcon-core = "=0.17.1"`.

File `src/corpus.rs`: add `ConCorpus::extend_trajectory_str`. It is `prepare_trajectory_str` with `frame_idx` starting at `traj_meta.n_frames`, then `group_prepared` when compression is on, then the same write transaction `extend_trajectory_frames` already uses. Stored blobs are the raw spans.

File `src/python.rs`: `ConCorpus.extend_trajectory_str(traj_id, text, source)`.

File `src/ffi.rs` and `include/readcon-db.h`: `rkrdb_extend_trajectory_str`, next to `rkrdb_append_trajectory_str`.

No change to `GROUP_LEN`, the tags, or `get_frame`.

### readcon-xfer

New repository `lode-org/readcon-xfer`. Dependencies: `readcon-core = "=0.17.1"`, `readcon-db` at the release that pins that core. Crate types `lib`, `cdylib`, `staticlib`. Header `include/readcon-xfer.h` installed as written, the same way readcon-db ships `include/readcon-db.h`.

The Rust functions and the C functions above are the whole public surface. Tests live in the crate: a buffer of ordinary values, signed zero, `f64::MIN_POSITIVE`, and `f64::from_bits(1)`, written from Rust and from C, read back from the file and from `trajectory_frame` after 65 appends so a frame lands in the second 64-group. A Python test in the same crate's CI imports the `readcon` and `readcon_db` wheels and checks the three equalities.

### eOn C++ client

`subprojects/readcon-core.wrap`: `revision = v0.17.1`.

`client/meson.build`: the `readcon-core` dependency floor becomes `>=0.17.1`, and the comment above it that cites 0.16 for `set_spreads_from_flat` is updated to the 0.17.1 floor. Add a `readcon-xfer` dependency the same way (pkg-config, then a wrap). Link it into `eoncbase` beside readcon-core. `ConFileIO.cpp` and `ReadconDbMirror.cpp` are already in the `eoncbase` source list.

`client/ConFileIO.cpp`:

- `frame_from_matter`, `seed_builder`, `apply_geometry`, `apply_frame_metadata`, `collect_ids_headers`, `cell_to_lengths_angles` stay. They are the `Matter` to `ConFrame` mapping.
- `matter2con`: build the frame as it does now. `append == false` calls `rkrx_checkpoint_write` when a corpus directory is resolved, otherwise `rkrx_restart_write`. `append == true` on an uncompressed path calls `rkrx_trajectory_append` with the movie's stable id (FNV-1a of the absolute path, not the text). Drop `kConPrecision` on this path.
- `con2matter(Matter &, string)` calls `rkrx_restart_read` instead of `readcon::read_first_frame`.
- `con2matter(Matter &, const readcon::ConFrame &, ...)` copies coordinates, velocities, and forces through `xyz_f64` and the velocity and force views. The species-order loop and `matter_order` stay. Fixed masks, ids, and masses stay on the atom record.
- `matter2convel` and `convel2matter` call the same restart functions. Drop `kConvelPrecision`. A velocity restart is a RoundTrip frame.
- `writeConFrames` and `writeNebPath` call `rkrx_trajectory_append`. `buildNebPathFrames` and `ConFrameBuilder::clone` stay.
- `append_frames` and `write_frames` remain only if `matter2xyz` and `writeTibble` still need local helpers. They stop taking a precision for CON.

`client/ReadconDbMirror.cpp`: `mirror_con_corpus` becomes `rkrx_checkpoint_write` of the file's first frame under the existing FNV-1a id (`fnv1a` in this file, same constants as `eon/concorpus.py` `traj_id`). Delete the `dlopen` of `libreadcon_db.so`. `client/ReadconDbMirror.h` keeps `mirror_con_corpus` so current call sites compile.

`client/HelperFunctions.cpp`: `relaxMatter` keeps calling `matter.matter2con`. The movie branch is the trajectory. The `prefixCheckpoint << "_cp"` branch is the checkpoint. `getRelevantFile` stays.

`client/MonteCarlo.cpp` and `client/BasinHoppingJob.cpp` keep calling `matter2con("movie.con")` and therefore pick up the trajectory append.

`include/eon/ConFileIO.h`: the declarations of `matter2con`, `con2matter`, `writeNebPath`, and `writeConFrames` stay. Callers do not learn a new type.

### eOn Python server

`pyproject.toml` and `pixi.toml`: `readcon>=0.17.1` and `readcon-db` at the release that pins `readcon-core = "=0.17.1"` (the `>=0.1.6` floor is not enough, because 0.1.6 does not have the 64-frame codec or the 0.17.1 writer).

`eon/fileio.py`:

- `savecon`: keep building the frame with `_atoms_to_frame` → `Structure.to_conframe`. Write with `write_con` / `write_con_string` and omit `precision`. Uncompressed append still concatenates that string (`_file_ends_with_newline` stays). Call `eon.concorpus.trajectory_append` for `w == 'a'` and `eon.concorpus.checkpoint_store` otherwise. Delete the direct `_mirror_con_text` / `_mirror_con_path` split.
- `loadcon`: `read_first_frame`, then `Structure.from_conframe`.
- `loadcons`: `read_con` for the in-memory list, then one `append_trajectory_str` of the file's own text under a path id so the corpus copy is the file bytes.

`eon/structure.py`:

- `from_conframe` keeps `coords_array` and `atom_ids_array`. Also copy `velocities_array` and `forces_array` when they are present, so a client checkpoint that carries forces restores them. The per-atom `except` fallback is removed once the floor is 0.17.1, so a missing accessor fails the test instead of silently reading `atom.x`.
- `to_conframe` stays the builder.

`eon/concorpus.py`:

- `checkpoint_store` calls `append_trajectory_str` with `traj_id(path, text)` as today.
- `trajectory_append` calls `extend_trajectory_str` with an id that is FNV-1a of the path alone, so successive movie frames share a `traj_id` and fall into 64-frame groups.
- `load_frame_text` and `frame_texts_for_paths` stay on `get_frame_text` / `get_frame_texts`.
- `mirror_con_text` and `mirror_con_path` delegate to `checkpoint_store` so existing tests that call them keep working.

`eon/fileio.py` `Dynamics` is unchanged. It reads reactant frames through `concorpus`, which is already indexed.

### chemparseplot

Python only. It does not link `readcon-xfer`. `chemparseplot/parse/eon/con_io.py` is already the module the package tells every eOn parser to use (`tests/parse/test_readcon_boundary.py` locks that). The six operations are added there. Callers keep their function names.

`pyproject.toml` extras `neb` and `test`, and `pixi.toml`: `readcon>=0.17.1`, plus `readcon-db` at the release that pins `readcon-core = "=0.17.1"`. The error string in `_readcon` and the docstring that say `readcon>=0.7` become `readcon>=0.17.1`, because `test_con_io_is_single_readcon_entry_point` asserts that string.

`chemparseplot/parse/eon/con_io.py`:

- `read_con_frames` stays `readcon.read_con` for a plot that needs every frame in memory. After the read, `checkpoint_store` is not called. A movie ingest is `append_trajectory_str` of the file bytes under a path id, once, so later indexed reads do not rescan the file.
- `read_first_atoms` calls `readcon.read_first_frame` and `frame.to_ase()`. It stops calling `read_con_as_ase(path)[0]`, which parses every frame to return the first.
- `read_con_as_ase` stays the all-frames ASE adapter. Positions on a fresh frame come from `coords_array` inside `to_ase` as 0.17.1 implements it. The bit-exact check compares `coords_array` with the file, not `get_positions` on a corpus.
- `frame_with_energy` stays. `set_energy` exists on 0.17.1, so the string-metadata fallback is dead on the new floor and the tests that still construct an old frame keep calling `set_energy`.
- `write_con_frames` keeps `write_con` with `precision` omitted. One frame is a restart write. More than one frame is a trajectory: the file is the RoundTrip text, and `extend_trajectory_str` / `append_trajectory_str` stores that same text under a caller-supplied `traj_id` (default FNV-1a of the absolute path). `write_atoms_as_con` goes through `write_con_frames`, so it picks up the corpus copy.
- Add `read_trajectory_frame(corpus, traj_id, frame_idx)` as `ConCorpus.get_frame` then the three arrays. Add `write_checkpoint(path, frames, corpus, traj_id)` as the one-frame form of `write_con_frames` plus `append_trajectory_str`.

`chemparseplot/parse/eon/_trajectory_common.py`:

- `read_first_structure` stays a call to `con_io.read_first_atoms`, so reactant and saddle restarts become one-frame parses.
- `load_movie_and_table` stays on `con_io.read_con_frames` because `table_from_min_metadata` and `table_from_dimer_metadata` need every frame's metadata. It calls the new ingest so the movie text is one corpus trajectory. `metadata_value` stays on `frame.energy`, `frame.frame_index`, and `frame.metadata`.

`chemparseplot/parse/eon/min_trajectory.py`: `parse_min_con`, `table_from_min_metadata`, and `load_min_trajectory` stay. `final_atoms` still prefers `{prefix}.con` then `min.con` via `read_optional_first`, which now reads one frame. The movie itself remains the trajectory.

`chemparseplot/parse/eon/dimer_trajectory.py`: `parse_climb_con` and `load_dimer_trajectory` stay. `saddle.con` / `reactant.con` / `pos.con` go through `read_first_structure`. `_load_mode_dat` stays an Nx3 text file. It is not a CON restart.

`chemparseplot/parse/eon/stitch.py` `stitch_neb_segments`: `read_con_frames` stays for the segments. `write_con_frames` of `neb.con` and `neb_path_000.con` is the trajectory write. `write_con_frames` of `sp.con`, and `write_atoms_as_con` of the saddle override, are the checkpoint of the highest image. The saddle geometry read `read_con_frames(sad_path)[0]` becomes `read_first_atoms`.

`chemparseplot/parse/eon/frame_series.py` does not touch the filesystem. `atoms_list_from_frames` keeps `to_ase`.

These stay off the CON path. They are not structure restarts:

- `chemparseplot/parse/trajectory/neb.py` `load_trajectory` reads extxyz and `.traj` with `ase.io.read`.
- `chemparseplot/parse/sella/saddle_search.py` reads and writes ASE trajectories with `ase.io.read` / `ase.io.write`.
- `chemparseplot/parse/eon/gprd.py` uses `ase.io.trajectory.Trajectory` and HDF5.
- `chemparseplot/plot/neb.py` `_render_xyzrender` writes a temporary `.xyz` for xyzrender.

`chemparseplot/parse/eon/__init__.py` keeps exporting `con_io`. `readcon` and `readcon_db` stay imported inside `con_io` functions. A module-level import would fail `test_eon_modules_do_not_import_readcon_at_module_level_except_typed_files`.

### rgpycrumbs

Python only. It does not grow a second CON writer. The functions that read or write a `.con` call `chemparseplot.parse.eon.con_io` after that module has the operations above. `rgpycrumbs/_aux.py` `_DEPENDENCY_MAP["readcon"]` becomes `readcon>=0.17.1`. `pixi.toml` gets the same floor and the matching `readcon-db`. PEP 723 headers move in the same commit, because `ci_test.yml` runs `pytest --pep723-check` over `rgpycrumbs/`.

`rgpycrumbs/eon/con_splitter.py`:

- `_read_trajectory_frames` calls `con_io.read_con_frames` for `.con` / `.convel` and still returns `(atoms_list, con_frames)`. Non-CON inputs stay `ase.io.read`. The `ase.io` import of `read` stays. `test_con_splitter_source_has_no_asewrite` still forbids `ase.io.write`.
- `_apply_frame_energy`, `_write_con_atoms`, and `_write_con_frame` delegate to `con_io.frame_with_energy` and `con_io.write_checkpoint`. An image that was not moved is still the original `ConFrame`, written with `precision` omitted. A centered or aligned image is `ConFrame.from_ase` plus the saved energy, which is what `_write_con_frame` does today.
- The loop that writes `ipath_*.con` keeps that layout. Each file is one checkpoint. The band the splitter read is ingested as one trajectory by `read_con_frames`.

`rgpycrumbs/eon/seed_dimers.py` `seed_dimers_from_peaks` (the function that takes `neb_con` and `out_dir`):

- `read_con` of the band stays a full read. Energies still come from `ConFrame.energy`.
- `pos.con` is `con_io.write_checkpoint` of `frames[idx]`, so the peak image is a RoundTrip restart.
- `displacement.con` is `con_io.write_atoms_as_con` of the displaced ASE atoms. `direction.dat` stays `numpy.savetxt`.
- `_match_eon_mode` reads each `peak*_pos.con` with `read_con(...)[0].to_ase()`. That becomes `con_io.read_first_atoms`. The paired `peak*_mode.dat` stays `numpy.loadtxt`.

`rgpycrumbs/eon/pimd_centroid.py`:

- `_template` reads the reference with `con_io.read_first_atoms` and takes symbol, mass, fixed flags, cell, and angles from that one frame. Spreads stay on the atoms (`sx`, `sy`, `sz`), which 0.17.1 still writes. The PEP 723 floor rises from `readcon>=0.16.0` to `readcon>=0.17.1`.
- `build_frames` stays the `ConFrame` constructor.
- `main` replaces `readcon.write_con` with `con_io.write_con_frames`, so `centroid.con` is a trajectory ingest as well as a file.

`rgpycrumbs/eon/modes_tensormap.py` `read_modes`: `con_io.read_con_frames`, then `frame.disp` and the metadata keys `mode_eigenvalue`, `hbar_omega`, `wavenumber`. The PEP 723 floor rises from `readcon>=0.15.0`. This is a trajectory read of every mode frame. It does not write CON.

Single-frame readers, each switched to `con_io.read_first_atoms`:

- `rgpycrumbs/uma/_io.py` `load_atoms` for `.con` / `.convel`. Other suffixes stay `ase.io.read`.
- `rgpycrumbs/eon/tls_pairs.py` `_atoms`. `_band_values` reads only the first frame's metadata (`read_con(...)[0].metadata`, key `tunnel_splitting`) and uses the same one-frame read, not `read_con_frames`.
- `rgpycrumbs/eon/plt_kmc.py` `collect_kmc_n2_timeline`, which today does `read_con(str(con))[0]` on `states/<id>/reactant.con`.
- `rgpycrumbs/eon/plt_saddle.py`, which today does `readcon.read_con_as_ase(str(ref_product))[0]`.

Full-band readers stay on `con_io.read_con_frames`:

- `rgpycrumbs/eon/helpers.py` `load_profile_rows`. The metadata keys `reaction_coordinate`, `relative_energy`, `parallel_force`, and optional `reaction_coordinate_mw` stay. A missing key is still `ValueError`.

`rgpycrumbs/eon/plt_con.py` loads through `con_io.read_con_frames`. At `4e4095bd70c9`, `chemparseplot.api` does not define `load_trajectory`, `plot_con_overview`, or `plot_con_overlay`, which this file imports. The plot helpers are not added by this design. The structure load is `con_io`. When those plot names exist, `load_trajectory` for a `.con` path calls `read_con_frames` and does not call `ase.io.read`.

These open no CON file themselves. They call chemparseplot, which is already on `con_io`:

- `rgpycrumbs/eon/plt_min.py` calls `chemparseplot.parse.eon.min_trajectory.load_min_trajectory`.
- `rgpycrumbs/eon/plt_saddle.py` calls `load_dimer_trajectory` in addition to the `ref_product` read above.
- `rgpycrumbs/eon/plt_neb_stitch.py` calls `stitch_neb_segments`.
- `rgpycrumbs/eon/plt_neb.py` imports `load_trajectory` from `chemparseplot.parse.trajectory.neb` (extxyz / `.traj`). Profile rows are `helpers.load_profile_rows`.

`rgpycrumbs/xts/cuh2/datgen.py` `get_from_gitroot_con` and `rgpycrumbs/xts/saddle/cuh2.py` `_cuh2_min` read `cuh2.con` with `ase.io.read`. That is a one-frame geometry for a contour, and it moves to `con_io.read_first_atoms`. Neither function writes CON. `rgpycrumbs/eon/gen_dimer.py` declares a `readcon` floor and does not read or write a structure. Its PEP 723 header still moves to `>=0.17.1` with the others. `tests/test_uma_cli.py` `test_prepare_aoti_declares_the_export_stack` asserts the string `readcon>=0.14.5` in `uma/prepare_aoti.py` and is updated in that commit.

`tests/test_cli_plotting.py` `_write_con_file` writes fixtures with `ase.io.write`. That helper is a test fixture writer, not the library path. It stays, and it is not the bit-exact witness. The witness writes with `con_io.write_con_frames`.

### rgsaddle

`Cargo.toml`: replace the optional `readcon-core = "0.14"` dependency with `readcon-xfer` at the published version, feature `readcon = ["dep:readcon-xfer"]`. Drop the direct `readcon-db` dependency. The `readcon-db` and `chemfiles` feature flags stay as aliases that enable `readcon`, so a downstream crate that already passes `--features readcon-db` still builds. Chemfiles import stays a readcon-core feature of the xfer crate if a later change needs it. This design does not add a chemfiles call.

`src/io.rs`:

- `frame_from_con` calls `readcon_xfer::restart_read` instead of `read_first_frame`. The `MolecularFrame` construction (positions flattened from `as_f64_row`, masses, `cell_from_header`) stays.
- Add `frame_to_con(path, frame: &MolecularFrame, symbols: &[String]) -> Result<(), SaddleError>`. It builds a `ConFrame` with `ConFrameBuilder` and calls `restart_write`.
- Add `checkpoint_con` and `append_band` as `checkpoint_write` and `trajectory_append`. `append_band` takes the positions `rgsaddle_band_positions` already exposes (`src/capi.rs`) plus the symbols and cell from the `MolecularFrame` the host loaded.

`src/lib.rs`: keep `pub use io::{MolecularFrame, frame_from_con}` and export the three new functions under the same `readcon` feature.

`src/capi.rs`: no change to `rgsaddle_band_step`, `rgsaddle_band_restart`, or the surface request. A C host that wants a band on disk links `readcon-xfer` and passes the pointer from `rgsaddle_band_positions`. rgsaddle does not grow a second writer.

`tests/io_cells.rs`: the existing `frame_from_con` cell cases stay. Add one write/read of a frame whose coordinates include a subnormal, and one 65-frame `append_band` that reads frame 64 back through `trajectory_frame`.

The optimizer `restart` on `BandSession` (`src/band.rs`, `rgsaddle_band_restart`) stays a wipe of stepper history. It is not a geometry restart.

### rgmin

`Cargo.toml`: optional `readcon-xfer`. Feature `xfer = ["dep:readcon-xfer"]`. Default features stay `["simd"]`. The C optimizer ABI in `include/rgmin.h` does not grow.

New file `src/geom.rs`, compiled only with `xfer`:

- `restart_write(path, symbols, masses, cell_lengths, cell_angles, positions)` builds one `ConFrame` and calls `readcon_xfer::restart_write`.
- `restart_positions(path) -> Array1<f64>` calls `restart_read` and flattens `as_f64_row`.
- `checkpoint_write` and `trajectory_append` take the same coordinate buffer plus optional velocities, forces, and energy.
- `trajectory_positions(corpus, traj_id, frame_idx)` calls `trajectory_frame`.

`src/lib.rs` exports `geom` behind the feature. `src/ffi.rs` and `rgmin_minimize` are untouched. A C program that already links rgmin and wants I/O links `libreadcon_xfer` and calls `rkrx_*` itself.

`python/rgmin/ase.py`:

- `Optimizer.__init__`: when `restart` is a path, call `readcon.read_first_frame` and `atoms.set_positions` from `coords_array`. Stepper memory stays empty. This replaces the `NotImplementedError` for a geometry path. A JSON file still raises, which keeps `test_todict_and_restart_refusal` meaningful if its fixture stays a `.json`.
- `Optimizer.dump`: write the current positions with `readcon.write_con` (precision omitted) to the path in `data` if the caller passed one. Method state is not in the file.
- When `trajectory` is a path ending in `.con`, append one RoundTrip frame per `step` via `write_con_string` concatenation and `extend_trajectory_str`, instead of letting ASE open a `.traj`. A `.traj` path keeps today's ASE writer so existing ASE tests stay valid.

`tests/python/test_ase.py`: `test_todict_and_restart_refusal` keeps the JSON refusal. Add `test_con_restart_restores_positions` and `test_con_trajectory_appends`. `test_trajectory_round_trip` still uses a `.traj` path.

### rgpot

`pixi.toml` feature `eonviz`: `readcon>=0.17.1`, and `readcon-db` at the matching release. `scripts/check_eonviz_pins.sh` learns that floor.

`CppCore/rgpot/rpc/ase_helpers.py`:

- `atoms_from_con` stays on `read_con_as_ase`. After the pin, the last-frame index still selects one frame of a multi-frame file.
- Add `atoms_to_con(atoms, path)`: `ConFrame.from_ase` when that constructor is present on 0.17.1 (`ConFrame.from_ase` in `src/python.rs`), else build a `ConFrame` from positions and symbols, then `write_con` with precision omitted.
- Add `checkpoint_atoms(atoms, path, corpus, traj_id)` and `append_atoms` as the Python call sequence in the table above.

`tests/eon_min_landscape.py`: the `readcon.read_con(...)[-1]` read of `minimization.con` stays. It is a trajectory read of the last frame. Add an assertion that the last frame's positions match `get_frame` of the corpus written beside the job, once the eOn client that produced the file is on this layer. Until that client ships, the test only checks `read_con` against `read_first_frame` of a one-frame fixture so the pin bump itself has a witness.

No C++ change under `CppCore/`. Potentials do not write geometries.

### cpmdc

The binary reader stays the wavefunction store. Geometry crosses the shared layer.

`src/cpmdc_restart.c` and `include/cpmdc_restart.h`: no change to record layout, `cpmdc_restart_read_mem`, `cpmdc_restart_write_mem`, or the rule that `cpmdc_restart_set_coordinates` rewrites 24-byte records and leaves every other record alone.

New file `src/cpmdc_con.c`, header `include/cpmdc_con.h`:

- `cpmdc_restart_write_con(file, path, symbols)` reads `cpmdc_restart_coordinates` and `cpmdc_restart_velocities`, converts Bohr to Ångström with `CPMDC_RESTART_ANGSTROM_PER_BOHR`, builds a frame through the readcon-core C builder (`rkr_frame_builder_*`), and calls `rkrx_restart_write`.
- `cpmdc_restart_apply_con(file, path)` calls `rkrx_restart_read`, reads `rkr_frame_xyz_f64` and `rkr_frame_velocities_f64`, converts Ångström to Bohr, and calls `cpmdc_restart_set_coordinates` / `cpmdc_restart_set_velocities`.
- `cpmdc_restart_checkpoint_con` and `cpmdc_restart_append_con` are `rkrx_checkpoint_write` and `rkrx_trajectory_append` around the same conversion.

`src/cpmdc.c`: `cpmdc_last_md_trajectory_row` and `cpmdc_session_last_md_trajectory_row` stay the Hartree row. A geometry trajectory frame may store that row's energy in the CON metadata when the caller passes it. The row itself is not parsed as atoms.

`tools/cpmdc_restart.c`: add `export-con` and `import-con` subcommands that call the two functions above. `info`, `positions`, `velocities`, `patch-positions`, and `patch-velocities` stay.

`meson.build` (or the equivalent that builds `cpmdc_restart.c`): link `readcon-xfer` into the library that exports `cpmdc_restart_write_con`. The stub build that has no CPMD runtime still compiles the bridge. It does not need a CPMD binary.

### seams-core

`subprojects/readcon-core.wrap`: `revision = v0.17.1`.

`subprojects/readcon-db.wrap`: the commit of readcon-db that pins `readcon-core = "=0.17.1"`.

Add `subprojects/readcon-xfer.wrap` and a dependency next to the existing readcon-core dependency.

`src/seams_input.cpp`:

- `sinp::readCon` may keep `ConFrameIterator::nth` for a CON path. That is already one atom-parse of the requested frame. After the wrap bump, the frame it yields is a 0.17.1 frame.
- `sinp::readConCorpus` keeps `rkrdb_select_campaign` and the hit sort. Replace the `rkrdb_get_frame_text` plus local re-parse with `rkrx_trajectory_frame` (or `rkrdb_get_frame` if the xfer crate is not linked into that translation unit). The point cloud is filled from `rkr_frame_xyz_f64`.
- Add `sinp::writeCon`, `sinp::checkpointCon`, and `sinp::appendCon` in `src/include/internal/seams_input.hpp`. Each builds one frame from the point cloud with the C builder and calls the matching `rkrx_*` function. `sinp::ingestConCorpus` stays `rkrdb_append_trajectory` for a path the caller already wrote.

`tests/test_readcon.cpp`: the existing `readCon` and `readConCorpus` cases stay. Add one case that `writeCon` then `readCon` returns the same coordinates, and one that `appendCon` of 65 frames reads frame 65 back through `readConCorpus`.

## Order of work

Each step is merged and green before the next one starts. A failure then belongs to one repository.

1. **readcon-db pin and `extend_trajectory_str`.** Publish the crate. Consumers stay on their current pins, so this publish cannot break them until they opt in.
2. **readcon-xfer, with the Rust, C, and Python wheel witness.** No consumer depends on it yet.
3. **rgsaddle.** Smallest reader. `frame_from_con` changes implementation and keeps its return type. The new write functions are additive.
4. **rgmin.** Feature-gated. Default and `capi` builds do not compile the crate.
5. **eOn client, then the Python server, in one eOn change.** The client is the writer everyone else restarts from. Landing it together with the server floor keeps `tests/test_fileio_readcon.py` and `tests/test_concorpus.py` on one pair of versions.
6. **chemparseplot `con_io`.** The plot stack's only CON boundary. It waits on steps 1 and 2 for `extend_trajectory_str` and the 0.17.1 wheel. It does not wait on the eOn client. A movie written by the client is the integration check, and it runs after step 5 with the same witness.
7. **rgpycrumbs.** It calls `con_io` and does not land before step 6. PEP 723 floors and `_DEPENDENCY_MAP` move in that same change.
8. **rgpot eonviz pin and `atoms_to_con`.** It only consumes files. It waits until a 0.17.1 wheel exists, which it does from step 2, and until the helpers match the eOn server sequence from step 5.
9. **cpmdc bridge.** Independent of eOn. It waits on step 2 because it links the C ABI.
10. **seams-core wraps and the three write functions.** Last, because the wrap move from `v0.16.2~2` / readcon-db `=0.16.1` to 0.17.1 is the largest pin jump and the read path must keep `tests/test_readcon.cpp` green on the new core before the write functions land.

## CI proof, with the existing suites left in place

The existing job is the regression gate. The new test is the bit-exact witness. Approval masters that capture CON bytes are regenerated in the same commit that switches the writer, and the following run of that job must match the new masters with no further edit.

| Repository | Existing job that must stay green | Witness added beside it |
| --- | --- | --- |
| readcon-db | The corpus test binary, including `zstd_round_trip_is_byte_exact_and_does_not_cook` and `grouped_frames_round_trip_and_migrate_does_not_wrap_again` in `src/frame_codec.rs` / `src/corpus.rs`. | `extend_trajectory_str` of 65 RoundTrip frames, `get_frame_text` equals the input span, `get_frame` then `as_f64_row` equals the parsed `f64` bits. |
| readcon-xfer | `cargo test` and a C driver that links the cdylib. | The shared fixture: Rust `frame_text`, C `rkrx_frame_text`, Python `write_con_string`, and `get_frame_text` after a 65-frame append are the same bytes. Accessors agree, including `f64::from_bits(1)` and signed zero. |
| rgsaddle | `.github/workflows/ci.yml` job `test`: `cargo test --features capi`, clippy, rustfmt. Job `ase-parity`. Neither gains a readcon dependency. | A new step `cargo test --features readcon,capi` runs `tests/io_cells.rs` plus the subnormal round trip. |
| rgmin | `.github/workflows/ci.yml` matrix rows `default`, `capi`, and `highs` (`cargo test --locked` with those args). | A new matrix row `xfer` (`--features xfer`). `python/rgmin` tests: JSON `read` still raises; a `.con` restart restores positions; a `.traj` path still round-trips. `--all-features` will compile `xfer`. That row is the witness, and the three existing rows must not mention readcon in their link line. |
| eOn | `.github/workflows/ci_build_akmc.yml` job `build_eon` (client tests, including `ConFileIOTest.cpp` and `ApproveConFileIO.cpp`) on ubuntu, macOS, and Windows. `.github/workflows/ci_serve.yml`. The Python tests `tests/test_fileio_readcon.py`, `tests/test_structure_readcon.py`, `tests/test_concorpus.py`, `tests/test_movie_corpus.py`. | One new client test writes a frame with `matter2con`, reads it with `rkrx_restart_read`, and checks `rkr_frame_xyz_f64` against the `Matter` positions bit for bit. One new Python test writes with `savecon`, reads with `read_first_frame` and `coords_array`, and checks `get_frame_text` against the file bytes. `ApproveConFileIO` masters are updated once in that commit. |
| chemparseplot | `.github/workflows/build_test.yml` job `build`: `uv run pytest --cov=chemparseplot tests` on Python 3.10, 3.11, and 3.12. `tests/parse/test_con_io.py`, `tests/parse/test_readcon_boundary.py`, `tests/parse/test_min_trajectory.py`, `tests/parse/test_dimer_trajectory.py`, and `tests/parse/test_neb_stitch.py` stay. | `read_first_atoms` on a two-frame file matches `read_first_frame` and does not require the second frame's atoms. `write_con_frames` of 65 frames, then `get_frame` of index 64, matches `coords_array` bit for bit, including a subnormal. `test_con_io_is_single_readcon_entry_point` is updated in that commit to look for `readcon>=0.17.1`. |
| rgpycrumbs | `.github/workflows/ci_test.yml` jobs `test-uv` (`uv run pytest`, including `--pep723-check` over `rgpycrumbs/`) and `test-pixi` (`pixi r -e fragments` and `pixi r -e surfaces`). `tests/test_con_splitter_readcon.py`, `tests/test_modes_tensormap.py`, `tests/test_pimd_centroid.py`, and `tests/test_seed_dimers.py` stay. | `con_splitter` of a RoundTrip band writes `ipath_000.con` whose bytes match `write_con_string` of that frame with `precision` omitted. `load_atoms` of a two-frame file equals `read_first_frame`. `tests/test_con_splitter_readcon.py` `test_con_splitter_source_has_no_asewrite` still requires a `readcon>=` floor and still forbids `ase.io.write`. The floor check is already `>= (0, 7)`, so 0.17.1 passes it. `tests/test_uma_cli.py` `test_prepare_aoti_declares_the_export_stack` is updated in that commit from the literal `readcon>=0.14.5`. |
| rgpot | `pixi run rust-test` and the Python CI that already covers `tests/`. `scripts/check_eonviz_pins.sh`. | `atoms_to_con` then `atoms_from_con` on a subnormal coordinate. The eonviz pin check fails if `readcon` is below 0.17.1. |
| cpmdc | `.github/workflows/ci.yml` jobs `stub-and-e2e` (`pixi run test-stub`, `test-e2e`, `test-cmocka`) and `sanitize` (`pixi run test-stub-sanitize`). | Extend `tests/test_cpmd_restart.c`: `cpmdc_restart_write_con` then `cpmdc_restart_apply_con` leaves every record other than coordinates and velocities byte-identical to the fixture `tests/restart_geo1.bin`, and the CON UTF-8 matches `rkrx_frame_text`. |
| seams-core | `.github/workflows/ci_test.yml` job `build-test` (`pixi run test`), including `tests/test_readcon.cpp`. | The new `writeCon` / `appendCon` case in that file. The old `readCon` and `readConCorpus` cases are not rewritten. |

A consumer PR that only bumps a pin is not done when the old tests pass. The witness for that repository has to pass in the same CI run. A consumer PR that changes a numeric spelling updates the one approval file that stores that spelling and touches no other golden.

## Risks

**0.17.0 read rejections.** Readers on 0.17.1 reject NaN and Inf (`NonFiniteValue`), reject a non-integer column 4 (`InvalidFixedFlag`), and require `units.time` on a minor-1 frame that carries velocities. eOn fixtures and seams fixtures that parsed on 0.16.0 can fail the existing `ConFileIOTest` and `test_readcon` jobs after the wrap bump. Those failures are the gate. Fix the fixture or the writer that produced it before adding witness tests. The 0.17.1 empty-header fix is the reason the pin is 0.17.1 and not 0.17.0: a multi-frame file with a blank line after coordinates must still read.

**Approval masters and decimal output.** `kConPrecision = 17` and `kConvelPrecision = 6` are the bytes `ApproveConFileIO.cpp` locks. Moving those writes to RoundTrip changes the masters once. External readers that assumed six decimal places in a `.convel` will see more digits. The digits round-trip. The velocity values a dynamics restart reloads are the values that were stored.

**Corpus identity for movies.** Today's eOn mirror uses FNV-1a of path plus text, so each appended movie frame is a separate one-frame trajectory. `trajectory_append` uses a path-only id so 64-frame grouping has a `frame_idx` sequence. Old movie corpora stay readable under their old ids. A new run does not see those old frames as indexes 0, 1, 2 of the movie trajectory. `checkpoint_store` keeps the path-plus-text id, so an unchanged reactant blob still hits.

**`RKRX_EXISTS`.** readcon-db has no replace-frame call. A second checkpoint with the same `traj_id` and different text returns `RKRX_EXISTS` and leaves the corpus as it was. eOn's FNV id changes when the text changes, so `relaxMatter`'s per-step `_cp` file still inserts. A caller that reuses one id for a changing checkpoint has to switch that series to `trajectory_append` and treat the last index as current. The CON path from `restart_write` is still the latest frame either way.

**Python accessors.** `ConFrame.coords_array` in `src/python.rs` copies the Python atom list. On a freshly parsed frame that list is the parser's `f64` values, and the witness compares it to `rkr_frame_xyz_f64`. If those bits differ, the only readcon-core change in this design is to make `coords_array`, `velocities_array`, and `forces_array` read the SoA columns. That change lands before step 5. No consumer papered over it.

**Cooked SoA.** `get_positions` skips the CON parse when a cooked blob is present, and the corpus comment says that blob is not equivalent to the CON text. Any consumer that restarts through `get_positions` or `rkrdb_get_positions` can observe a different `f64` than the file. The crate does not call those functions. A later campaign that cooks a frame must keep using `get_frame` for a restart.

**cpmdc units.** `CPMDC_RESTART_ANGSTROM_PER_BOHR` (`0.529177210859`) is not a bit-exact inverse of its reciprocal. Two trips through the binary `RESTART.n` can move a coordinate by an ulp. The CON file written in between is bit-exact across languages. The test that matters for the binary file is the one cpmdc already has: non-coordinate records are unchanged. Do not claim the Bohr records are bit-exact across a CON round trip.

**rgmin stepper state.** A `.con` restart restores positions and starts FIRE or LBFGS with empty history. `Optimizer.read` used to refuse every restart. Tests that pass a `.json` still see `NotImplementedError`. Tests that start passing a `.con` and expect a refusal need to expect restored positions instead. The `default` CI row does not link readcon, so a release built without `--features xfer` has the same Rust behavior it has today. The Python ASE adapter does import `readcon` on the restart path. That import is lazy and inside the `restart is not None` branch, so a process that never restarts does not require the wheel. Document the wheel as required only when `restart=` or a `.con` trajectory is used.

**rgsaddle 0.14 to 0.17.1.** `frame_from_con` uses `frame.positions`, `frame.masses`, and `header.lattice_vectors` / `header.boxl` / `header.angles`. Those fields exist on 0.17.1. The 0.17.0 parser is stricter. `tests/io_cells.rs` is the check that the cell conversion still accepts the fixtures under the new parser. The `readcon` feature is off in the default CI job, so a broken feature does not hide inside `cargo test --features capi`.

**Two readcon-core copies in one process.** eOn already links `libreadcon_core` for `ConFrameBuilder` and would link it again through `libreadcon_xfer`. Both must be the same 0.17.1 build. `client/meson.build` already has a comment about a second `readcon_core.dll` on `PATH` causing `STATUS_ENTRYPOINT_NOT_FOUND` on Windows. The xfer crate links readcon-core statically, or the install puts one shared `libreadcon_core` on the path and the xfer cdylib uses it. Mixing 0.16.0 in the eOn wrap with 0.17.1 inside xfer is a broken process. The wrap bump and the xfer dependency land in the same eOn commit.

**seams pin distance.** The seams readcon-core wrap is two commits before `v0.16.2`, and the vendored readcon-db commit requires `=0.16.1`. Moving both wraps in one commit is what `pixi run test` has to survive. `readCon` returning an empty cloud on a missing frame is existing behavior and stays.

**Append of a file this process did not write.** `matter2con` today parses an uncompressed target whose size or mtime changed before it concatenates, and returns `AppendError` with the bytes untouched when that parse fails. `trajectory_append` must keep that check: run `read_first_frame` (or `count_frames`) on a foreign tail, and on failure write nothing. A tail that parses is concatenated. Earlier frames are not rewritten, so their bytes survive.

**chemparseplot reads the whole file to keep frame 0.** `read_first_atoms` and every rgpycrumbs `read_con(...)[0]` site parse every frame on 0.14.5. Switching those sites to `read_first_frame` changes the work, not the frame that is returned. `load_movie_and_table`, `load_profile_rows`, `read_modes`, and `stitch_neb_segments` still need every frame, and they stay on `read_con`. A test that counted `read_con` calls on a one-frame helper has to expect `read_first_frame` instead.

**Re-serializing a band that was not RoundTrip.** `con_splitter._write_con_frame` and `seed_dimers` `write_con([peak_frame])` parse a frame and write it again. On 0.17.1 that write is RoundTrip, so a band written at 17 decimal places changes spelling on the way out. `tests/test_con_splitter_readcon.py` compares energies with `pytest.approx`, so those tests stay green while the bytes change. The new witness covers a frame that was already RoundTrip. An unchanged image from a decimal file is not required to keep its old spelling.

**Two copies of the energy setter.** `con_io.frame_with_energy` and `con_splitter._apply_frame_energy` both clone a `ConFrame` and call `set_energy`, with the same string-metadata fallback. rgpycrumbs deletes its copy and calls `con_io`. Leaving both in place means a later metadata change has to be made twice, and the bit-exact tests can pass in one package and fail in the other.

**`plt_con` imports names this chemparseplot commit does not export.** `rgpycrumbs/eon/plt_con.py` imports `load_trajectory`, `plot_con_overview`, and `plot_con_overlay` from `chemparseplot.api`. `chemparseplot/api.py` at `4e4095bd70c9` exports the ORCA and XYZ helpers and does not define those three names. This design does not add the plot functions. It only requires that a `.con` load, wherever it is called, go through `con_io.read_con_frames`. ASE `load_trajectory` in `parse/trajectory/neb.py` stays the extxyz/`.traj` reader.

**PEP 723 floors disagree with each other today.** `plt_con.py` says `readcon>=0.13.1`, most eOn scripts and `uma/prepare_aoti.py` say `>=0.14.5`, `tls_pairs.py` says `>=0.14.9`, `modes_tensormap.py` says `>=0.15.0`, and `pimd_centroid.py` says `>=0.16.0`. `pytest --pep723-check` records the header it sees. Raising one script and leaving another on 0.14.5 lets `uv run` of that script write with an older wheel than `con_io`. Every header listed above moves to `>=0.17.1` in the rgpycrumbs commit, including `gen_dimer.py`, which declares the floor and does not touch a structure. `test_optional_peers_pinned_for_uv_and_readcon` only requires `>= (0, 13)`, so the higher floor still passes. `test_prepare_aoti_declares_the_export_stack` compares the header to the literal `readcon>=0.14.5` and has to change in that same commit.
