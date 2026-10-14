# Consumers A: put readcon 0.17.1 into production

This is an adoption plan for the codes that already sit next to CON. The library work is on `readcon-core` `main` at **0.17.1**. The corpus work is on `readcon-db` `main` at `0725c94` (merge of `feat/zstd-frames`). The gap is that the consumers still pin older cores, still spell floats with a fixed decimal count, and still treat a campaign as a pile of one-frame blobs.

Pins below are what those repositories actually resolve to on 2026-10-14, not the version bounds written in a README.

| Consumer | What it resolves today | What production should resolve |
| --- | --- | --- |
| eOn C++ client (`TheochemUI/eOn` `cc4f699`) | `subprojects/readcon-core.wrap` `revision = v0.16.0` | readcon-core **v0.17.1**, readcon-db at or after `0725c94` with core **=0.17.1** |
| eOn Python server | `pyproject.toml` / `pixi.toml`: `readcon>=0.15.0`, `readcon-db>=0.1.6`; `readcon-ops` git `4d7881a` | `readcon>=0.17.1`, readcon-db **0.1.9** (cut below), ops commit that reads `xyz` |
| chemparseplot (`HaoZeke/chemparseplot` `4e4095b`) | optional extra `neb` and the `test` extra: `readcon>=0.14.5`; `pixi.toml` the same. Core install is numpy and pint only | `readcon>=0.17.1` on `neb`, `test`, and pixi. `chemparseplot/parse/eon/con_io.py` stays the only CON read/write facade |
| rgpycrumbs (`HaoZeke/rgpycrumbs` `73ddf2e`) | `pixi.toml` and `_aux.py` `readcon>=0.14.5`. PEP 723 floors differ by script (`0.13.1` through `0.16.0`). Plotting imports chemparseplot | every floor `readcon>=0.17.1`. CON writes go through chemparseplot `con_io`. No corpus client |
| rgsaddle (`ffe54d4`) | optional `readcon-core = "0.14"`; `readcon-db = "0.1"` declared and unused | `readcon-core = "0.17.1"`, `readcon-db` 0.1.9, both still optional |
| rgmin (`2560f83`) | no readcon dependency; `Report.coords` is the only result | optional `readcon` feature on 0.17.1 |
| rgpot (`b901b09`) | `pixi.toml` `readcon >=0.14.7`; `scripts/export_uma_aoti.py` parses CON by hand | `readcon>=0.17.1`; delete the hand parser |
| cpmdc (`c518e1e`) | `cpmdc_restart_*` binary RESTART only | binary RESTART stays; optional CON sidecar through the C ABI |
| seams-core (`305fb3c`) | `meson.build` `readcon-core >=0.16.2`; wrap `91181ef` (2026-10-09); readcon-db wrap `0001a2c` which pins `readcon-core = "=0.16.1"` and has no `frame_codec.rs` | both wraps move to v0.17.1 and readcon-db 0.1.9 |
| readcon-db | tag `0001a2c` (the 0.1.8 release commit) pins `readcon-core = "=0.16.1"`. `main` `0725c94` pins `=0.17.0` and implements the 64-frame codec | `readcon-core = "=0.17.1"`, version **0.1.9** |

`readcon-ops` `4d7881a` does not parse files. It is in this plan because `eon/atoms.py` compares structures through it, and `_from_conframe` still walks `atom.x/y/z` unless `xyz` is present.

## The surface the consumers are adopting

### Single-pass parse

`parse_single_frame` (`src/parser.rs`) reads the header, the coordinate rows, and the position SoA in one walk. The flat `pos_flat` buffer is wrapped once. `ConFrameIterator::next` (`src/iterators.rs`) stays on that same `MemchrLines` cursor and calls `parse_declared_sections`. `ConFrame::sync_arrays_from_atom_data` runs only when a section was present, and it does not rewrite positions when `positions.nrows()` is already `N`.

`ConFrameBuilder::build_with_permutation` (`src/types.rs`) is the matching single pass on the way out. It buckets atoms by symbol in encounter order and returns `perm` where `perm[i]` is the grouped index of insertion `i`. `build` discards that map. Callers that keep a parallel array (Matter order, a mode vector, a band image) use the map. They do not sort `atom_id` afterwards to rediscover it.

Skipping is not a second parse. `forward_fast`, `skip_frames`, and `read_nth_frame` advance by counts. `read_all_frames_indexed` uses the `.rcidx` sidecar. Corpus ingest uses `ConFrameIterator::next_with_raw_span` so the stored blob is the file substring. `readcon-db` `prepare_trajectory_str` already does this. Consumers that read the file, build a `ConFrame`, and write it back are throwing that span away.

### Accessor API

Hot loops borrow the builder or the frame. They do not call `get_atom_*` / `set_atom_*` per row and they do not allocate a `std::vector<double>` to hand to `set_*_from_flat` when the source is already row-major `Nx3`.

| Binding | Write into the builder | Read a frame |
| --- | --- | --- |
| Rust | `ConFrameBuilder::positions`, `positions_mut`, `positions_view`, `velocities_mut`, `forces_mut`, `displacements_mut`, `spreads_mut`, `atom_energies_mut`, `masses`, `atom_ids` | `ConFrame.positions` / `forces` / `velocities` (`FloatArray2::as_f64_row` or the f64 slice) |
| C++ | `ConFrameBuilder::positions_data`, `velocities_data`, `forces_data`, `displacements_data`, `spreads_data`, `atom_energies_data`, `masses_data`, `atom_ids_data` | `ConFrame::xyz_f64` → `rkr_frame_xyz_f64` |
| C | `rkr_frame_builder_positions_data` and the siblings in `include/readcon-core.h` | `rkr_frame_xyz_f64` |
| Python | `ConFrame` is still built from `Atom` objects; `to_con_frame` in `src/python.rs` then `add_atom`s. A bulk constructor is not in 0.17.1 | parsed frames: getter `xyz` (and `vel`, `frc`), which copies `positions.f64_slice()` once. `coords_array` / `atom_ids_array` walk the Python atom list |

`positions_dlpack` / `rkr_frame_builder_positions_dlpack` stays the path for a consumer that already speaks DLPack (rgmin already depends on `dlpk`). A DLPack export is not a reason to copy into a fresh `Array1` first.

Pointer rule, from the builder comments: the data pointer is stable until `add_atom` grows the buffer. Fill identity (`add_atom` of symbols, masks, masses, ids), then borrow `positions_data()` for the geometry, then `build_with_permutation`. Do not hold the pointer across `add_atom`.

`velocities_data()` returns null until the section exists. Call `velocities_mut()` on the Rust side, or one `set_atom_velocity` / the C++ equivalent that allocates, before borrowing the pointer for the rest of the rows. eOn's `apply_geometry` currently loops `set_atom_velocity` for every atom (`client/ConFileIO.cpp`). That loop goes away once the section is allocated and the pointer is borrowed.

### 64-frame zstd, indexed

`readcon-db/src/frame_codec.rs` on `0725c94`:

- `GROUP_LEN = 64`
- one frame: `0xFD 0x01` plus one zstd frame, or the raw UTF-8 when compression does not shrink
- redirect: `0xFD 0x02`, head frame index, slot
- group: `0xFD 0x03`, count, one zstd frame of length-prefixed UTF-8
- level 1, no dictionary
- xxh3-128 is over each frame's UTF-8, not over the compressed bytes

`ConCorpus::compress_frames` defaults to true (`src/corpus.rs`, both `open` paths). `append_trajectory_str` parses with `next_with_raw_span`, `build_index_puts` stores per-frame values, then `group_prepared` → `pack_aligned` replaces a run whose `frame_idx / 64` matches when the group plus redirects is shorter. `get_frame_text` → `decode_frame` follows a redirect back to the head.

`pack_aligned` does not group a one-frame call. `extend_trajectory_frames` groups only the frames in that call. A client that appends one frame per AKMC step never produces a `0xFD 0x03` value. Production movies buffer an aligned run (indices `64k .. 64k+63`) and extend once.

Indexes are the `FrameIndexProjection` written in `build_index_puts` (finite energy, formula, section mask). Reads are `ConCorpus::get_frame` / `get_frame_text` / `select`, and on the C ABI `rkrdb_get_positions`, `rkrdb_get_forces`, `rkrdb_get_velocities`, `rkrdb_select_campaign`, `rkrdb_result_key`. A consumer that needs frame `k` uses the key. It does not scan the `.con`.

`src/python.rs` `ConCorpus.append_trajectory_frames` does not use that writer. It imports the installed `readcon` wheel and calls `write_con_string`. The bytes in the corpus then depend on whichever wheel is installed, and a second parse throws away the span. 0.1.9 changes this method to `append_trajectory_frames_with_float_format(..., FloatFormat::RoundTrip)` inside the crate. `set_compress_frames` stays default-on. It is Rust-only today; the C and Python bindings do not need a setter for adoption.

The 0.1.8 **tag** (`0001a2c`) is not this codec. It pins `readcon-core = "=0.16.1"` and has no `frame_codec.rs`. Version `0.1.8` on `main` is ahead of that tag and already pins `=0.17.0`. Cut **0.1.9** with `readcon-core = "=0.17.1"` so a version bound can mean "64-frame groups and the 0.17.1 writer". Until that tag exists, wraps pin the 0.1.9 commit, not `0001a2c`.

### Bit-exact restarts

A restart is bit-exact when these four produce the same UTF-8 for the same `ConFrame`, with canonical mode left off:

- Rust `ConFrameWriter::new` / `FloatFormat::RoundTrip` (`src/writer.rs`; default since 0.17.0)
- Python `write_con` / `write_con_string` with `precision` omitted (`src/python.rs`)
- C `create_writer_from_path_c` and `create_writer_from_path_round_trip_c`
- C++ `ConFrameWriter(path)` or `ConFrameWriter(path, Compression::None)` with no precision argument (`include/readcon-core.hpp`)

`FloatFormat::DecimalPlaces` is a different spelling. eOn's `kConPrecision = 17` and `kConvelPrecision = 6` (`client/ConFileIO.cpp`) take that path via `create_writer_from_path_with_precision_c`. Those constants are deleted. `%.17g` in `save_mode` (`eon/fileio.py`) is a mode file, not a CON restart, and stays.

Proof is `cmp` of the files, then a read through `read_first_frame` and `f64::to_bits` on positions, velocities, forces, and the frame energy. A tolerance on energy is the regression check for a dynamics step. It is not the restart check.

0.17.1 also changes what a conforming frame contains, and every writer above has to emit it:

- `ConFrameBuilder::build` stamps `con_spec_minor` 1 when the caller did not set it, and inserts `default_v3_units_json()` (length, energy, mass; no `time: fs`).
- A minor-1 frame with velocities and no `units.time` fails read and write (`InvalidUnits`). The time label for eOn and ASE natural units is `(amu*angstrom^2/eV)^0.5`.
- `set_lattice_vectors` keeps header lines 3 and 4 consistent with the cell matrix. Writers that only set lengths and angles, then also carry a lattice, must go through this or through `cell_vectors` / `lengths_and_angles`.
- Two atoms of one symbol whose masses differ by more than `ConFrameBuilder::TYPE_MASS_ABS_TOL` fail `build` with `MassMismatch`. CON line 9 has one mass per type. Callers collapse to the first mass of the symbol before `build`, and a test owns the error.

Canonical JSON (`writer.set_canonical(true)`, Python `canonical=True`) sorts keys. It is not part of the restart equality. All four bindings leave it off.

## Order across repositories

1. **readcon-db 0.1.9.** Pin `=0.17.1`. Point Python `append_trajectory_frames` at `append_trajectory_frames_with_float_format` + `FloatFormat::RoundTrip`. No on-disk tag change: `0xFD 0x03` is already the group. A corpus written by 0.1.9 still reads a raw UTF-8 value from an older db.
2. **eOn C++ client**, then **eOn Python server**, against that 0.1.9. These two write the files other codes consume (`reactant.con`, `saddle_*.con`, `product_*.con`, movies). They have to agree with each other before anyone else adopts the spelling.
3. **chemparseplot**, then **rgpycrumbs**. `con_io.py` is the CON facade both already intend to share. Stitch, seed-dimer, and centroid writes produce `neb.con`, `pos.con`, and `centroid.con` that eOn reads back, so they adopt RoundTrip immediately after eOn's writer. Neither package opens LMDB.
4. **readcon-ops**, then bump the eOn git pin. Ops does not write restarts. It has to stop reconstructing coordinates from `atom.x` so a comparison of a 0.17.1 frame uses the same numbers the accessor returned.
5. **rgsaddle**, then **rgmin**. Saddle already reads CON and owns band images. The minimizer grows an optional writer and does not gain a required parser.
6. **rgpot** deletes its private parser once eOn's writer is the spelling `read_con` accepts.
7. **cpmdc** CON sidecar, optional at build time. The binary `RESTART` remains the CPMD checkpoint.
8. **seams-core** wrap bump last among the readers. It already reads. It must not link a db built on 0.16.1 beside a core built on 0.17.1.

Each step lands with its byte test green before the next repository moves its pin. A consumer does not vendor a private copy of `parse_single_frame`.

## Shared restart fixture

One frame, checked into each consumer that writes CON, generated by readcon-core 0.17.1 and stored as bytes:

- Cu, H, Cu, H in that insertion order, so grouping is not a no-op
- one Cu mass shared, one H mass shared
- one axis fixed on the first atom
- a non-orthogonal cell (angles not all 90)
- a coordinate of signed zero, one subnormal-scale value (`f64` from a known bit pattern, not a decimal literal that is already short), a finite energy, a force row, and for the velocity variant a velocity row
- `units` length `angstrom`, energy `eV`, mass `amu`, and for the velocity variant time `(amu*angstrom^2/eV)^0.5`
- line 1 `Generated by eOn` so the eOn header normalizer is in the comparison

Call it `restart_exact.con` and `restart_exact_vel.con`. The golden is the output of `ConFrameWriter::new`, not of precision 17. Tests `cmp` their writer against the golden. They do not re-implement the float format.

---

## readcon-db

### What changes

`Cargo.toml` `readcon-core = "=0.17.0"` becomes `=0.17.1`. Crate version 0.1.8 becomes 0.1.9. `GROUP_LEN`, the three tags, and `decode_frame` stay.

`src/python.rs` `ConCorpus::append_trajectory_frames` stops calling `readcon.write_con_string`. It converts the Python frames with the same `py_frames` path the wheel already uses, or accepts frames the caller already serialized with omitted `precision`, and then calls `append_trajectory_frames_with_float_format` with `FloatFormat::RoundTrip`. The stored UTF-8 is the crate's writer. A second copy of the spelling cannot appear because an older wheel was installed beside a new db.

`src/bin/readcon-db.rs` keeps the explicit `set_compress_frames(false)` switches it already has. Default ingest stays compressed. Document in the crate README that a one-frame `append` / `extend` stores `0xFD 0x01` or raw UTF-8, and that a 64-index-aligned batch is what produces `0xFD 0x03`.

No new key layout. `FrameKey` is still `(traj_id, frame_idx)`.

### API the crate must keep stable for the consumers

- Rust: `append_trajectory_str`, `append_trajectory_frames_with_float_format`, `extend_trajectory_frames`, `get_frame`, `get_frame_text`, `get_frame_texts`, `select`, `set_compress_frames`
- C: `rkrdb_open`, `rkrdb_append_trajectory_str`, `rkrdb_extend_trajectory`, `rkrdb_get_frame_text`, `rkrdb_get_positions`, `rkrdb_get_forces`, `rkrdb_get_velocities`, `rkrdb_select_campaign`, `rkrdb_result_key`, `rkrdb_abi_stamp`
- Python: `ConCorpus.append_trajectory_str`, `append_trajectory_frames`, `extend_trajectory`, `get_frame`, `get_frame_text`, `select`

`rkrdb_append_trajectory_str`'s signature stays. eOn `dlsym`s it (`client/ReadconDbMirror.cpp`). A missing symbol is a soft skip today; a signature change would corrupt the mirror.

### Order

1. Pin and the Python writer fix, with a unit test that a 64-frame aligned `append_trajectory_frames_with_float_format` stores one `0xFD 0x03` head and 63 redirects (`is_group` / `is_redirect` in `frame_codec.rs`).
2. Tag 0.1.9.
3. Consumers move.

### CI

- Existing corpus tests stay. Add: round-trip `get_frame_text` of a grouped frame equals the RoundTrip UTF-8; `f64::to_bits` of `get_frame` positions equals the input frame; a raw untagged value from a fixture written without compression still decodes.
- Byte test: the UTF-8 inside a one-frame value (after `load_frame`) equals `restart_exact.con`.
- Regression: `select` on energy / formula returns the same keys for an uncompressed fixture and for the same fixture after grouping. Grouping changes the value encoding, not the index keys. xxh3-128 is over the UTF-8, so the hash index matches too.

### Risks

- 0.1.9 and a wheel of readcon 0.15 in one process: Python `append_trajectory_frames` used to hide that. After the fix the crate writes 0.17.1 bytes even if the wheel is old, and a caller who then `read_con`s those bytes with a 0.15 wheel can fail on minor-1 units. The eOn pin moves in the same change set as the 0.1.9 dependency.
- Repacking an open group on every single-frame extend is deliberately not the design. A crash mid-buffer loses at most 63 unflushed frames from the **corpus**. The `.con` file remains the authority, which is what `eon/concorpus.py` already says.
- `set_trajectory_units` rewrites stored numbers. Do not run it on a restart corpus to "fix" units. Writers emit the right units object the first time.

---

## eOn C++ client

Repository `TheochemUI/eOn`. Files: `client/ConFileIO.cpp`, `client/ReadconDbMirror.cpp`, `client/ReadconDbMirror.h`, `include/eon/ConFileIO.h`, `subprojects/readcon-core.wrap`.

### What changes

`subprojects/readcon-core.wrap` `revision = v0.16.0` becomes `v0.17.1`. Add a `readcon-db.wrap` only if the client starts linking the db. It should not. The mirror keeps `dlopen` of `libreadcon_db.so` so a client binary runs where the db is absent (`ReadconDbMirror.h`: failure to load does not change `IoStatus`).

`write_frames` and `append_frames` drop the `uint8_t precision` argument and the `kConPrecision` / `kConvelPrecision` constants. They construct `readcon::ConFrameWriter` without a precision. That is `create_writer_from_path_c`, which is RoundTrip. Gzip and zstd targets use the compression constructor that also has no precision (`ConFrameWriter(path, compression)`), not `create_writer_*_with_precision_c`.

`frame_from_matter` keeps `seed_builder` for identity rows (`add_atom` of symbol, fixed mask, id, mass). After the atoms exist:

- Collapse masses to the first mass of each symbol before `add_atom`, so `MassMismatch` does not fire on a configuration the old line-9 writer already flattened. Log when a collapse changes a mass.
- `Eigen::Map<AtomMatrix>` onto `builder.positions_data()` instead of `flat_row_major` + `set_positions_from_flat`. `AtomMatrix` is already row-major (`flat_row_major` asserts that). The copy through `std::vector<double>` is the duplicate.
- Same map for forces onto `forces_data()` when `should_write_forces` is true. The opt-in stays (`g_write_con_forces`, `Matter::getWriteConForces`, `ConFrameMetadata::write_con_forces`). ASE-class readers still see no force section unless that flag is set.
- Velocities: allocate the section once, then map `velocities_data()`. `matter2convel` calls `builder.set_units` with length, energy, mass, and time `(amu*angstrom^2/eV)^0.5` before `build`.
- `build_with_permutation` replaces the hope that `matter_order` on the way back is the inverse. `matter2con` does not need the permutation for the file. `con2matter` does. On read, prefer the permutation the builder would have produced only when the file was just written in-process. For a file from disk, use `readcon` `pre_grouping_indices` (`src/types.rs`) on the id column from `atom_ids_data` / the frame ids, and delete the local sort in `matter_order` if the ids are unique. Duplicate ids keep file order, which `matter_order` already does.
- `cell_to_lengths_angles` and the triclinic reconstruction inside `con2matter` (the block that special-cases 90/90/90 and otherwise builds `Matrix3d` from sin/cos) are the same math as `lengths_and_angles` and `cell_vectors`. Call those. `set_lattice_vectors` on the way out when the Matter cell is not diagonal, so lines 3 and 4 cannot drift from the matrix.
- `con2matter` copies `atom.x/y/z` in a loop. Take `frame.xyz_f64()` and scatter with the id permutation into `AtomMatrix`. Forces and velocities the same, from the frame SoA, not from `atom.force()` / `atom.velocity()` optional copies.
- `apply_frame_metadata` stays. It is metadata, not a second geometry path. `canonical_generator_header` stays so line 1 is never empty (`Generated by eOn`).

`mirror_con_corpus` today reads the whole file back into a string and calls `rkrdb_append_trajectory_str` with `fnv1a(path + NUL + text)`. That has three production failures:

- `matter2con` skips the mirror when `concatenate` is true, so an AKMC movie never reaches the corpus after the first frame.
- The id includes the text, so every rewrite is a new trajectory and `extend` cannot attach.
- One call with one frame never hits `GROUP_LEN`.

Change: traj id is FNV-1a of the canonical path only, shared with `eon/concorpus.py` `traj_id` (same offset, prime, and NUL-free payload). On a full rewrite, `rkrdb_append_trajectory_str` of the file just written (one call, so a multi-frame file groups). On a streaming append, buffer up to 64 serialized frames in the existing append lock and `rkrdb_extend_trajectory` of that batch, or extend the in-memory frames through a new dlsym of a batch append if 0.1.9 exports one. If `rkrdb_extend_trajectory` is missing, keep today's soft skip. Do not fail the AKMC step.

`append_frames` keeps its scratch file. 0.17.1 still has no C writer over a caller-owned buffer (`create_writer_from_path_*` takes a path; `rkr_writer_flush` flushes a path writer). The comment in `append_frames` is right about the missing stream. It is wrong that this blocks RoundTrip: the scratch writer is simply constructed without precision. Deleting the scratch is a later FFI, not this adoption.

`matter2xyz` and `writeTibble` stay. They are not CON. `loadposcar` on the Python side stays; POSCAR is the non-CON format.

### API it needs

From readcon-core 0.17.1 C++: `ConFrameBuilder` (`add_atom`, `positions_data`, `forces_data`, `velocities_data`, `set_units`, `set_energy`, `set_displacements_from_flat`, `set_spreads_from_flat`, `build_with_permutation`), `ConFrame` (`xyz_f64`, `read_first_frame`, `read_all_frames`), `ConFrameWriter` without precision, `cell_vectors`, `lengths_and_angles`, `pre_grouping_indices`, `z_to_symbol`.

From readcon-db, by `dlsym` only: `rkrdb_open`, `rkrdb_append_trajectory_str`, `rkrdb_extend_trajectory`, `rkrdb_abi_stamp`. No link line on the client.

### Order inside eOn

1. Wrap bump to v0.17.1. Build the client. Fix `MassMismatch` and missing `units.time` on convel until `matter2con` / `matter2convel` succeed on `client/unit_tests` fixtures.
2. Switch writers off precision. Regenerate approvals that store bytes.
3. Switch `apply_geometry` / `con2matter` to the accessors and `cell_vectors`. Delete `matter_order`'s sort body once `pre_grouping_indices` covers it.
4. Mirror: path-only id, mirror streaming appends in groups of 64, soft-skip when the symbol is absent.

### CI

Workflow `.github/workflows/ci_build_akmc.yml` already runs `meson test -C bbdir --suite eon`. Add `client/unit_tests/ConRestartExact.cpp` to that suite:

- Build a `Matter` matching `restart_exact.con`, `matter2con` to a temp file, `cmp` against the golden.
- Same for `matter2convel` and `restart_exact_vel.con`.
- `con2matter` the golden, `matter2con` again, `cmp` again (read-then-write is the identity on this fixture).
- Positions after `con2matter` match the golden's f64 bits, including signed zero. Compare with `memcmp` on the mapped doubles, not `Approx`.
- A 64-frame synthetic movie (the same frame repeated is fine) flushed through the mirror, then `rkrdb_get_positions` of frame 0 and frame 63, matches. Skip the assertion when `dlopen` fails, and fail it when the library loaded but the group did not decode. Run that job in an environment where `libreadcon_db.so` from 0.1.9 is on the path so the skip is not the steady state.
- Existing `ApproveConFileIO.cpp` and the Catch2 suite stay. Update byte approvals. Geometry, fixed masks, atom ids, and "energy plus forces marks the potential clean" (`con2matter`) stay as they are.
- One existing short minimization (the suite already loads `reactant.con` in `SaddleSearchTest.cpp` / `BondBoostTest.cpp`) still accepts the same final energy within the tolerance that test already uses. Do not freeze the new movie bytes as the dynamics oracle.

Python cross-check lives in the server section and runs in the server CI, not in the Catch2 job. It `cmp`s a file this client wrote with `write_con_string` of the same frame.

### Risks

- Precision 17 and convel precision 6 are load-bearing for anyone diffing `minimization.con` or restarting MD from a truncated velocity. Old files still parse. New files will not match old goldens. Dynamics restarted from an old 6-digit convel are not bit-identical to a run restarted from a RoundTrip convel; that is the point of the change, and the regression net is the Catch2 energy check plus the old-file read, not a replay of the truncated file.
- Isotope masses. Collapsing to the first mass changes forces for a potential that reads mass from the file. The log line and a unit test with two Cu masses are the guard. Do not silently keep per-atom masses in memory and a different mass on disk.
- `build` now returns `Result` and throws out of the C++ wrapper on format errors. `frame_from_matter` already catches and returns `IoStatus::InvalidArgument`. Keep that. A new `InvalidUnits` must not become an abort.
- Streaming mirror holds 64 frames of text under `append_mutex`. That lock already covers the append. Do not evaluate the potential under it (`matter2con` already documents that). The buffer is text, not a `Matter`.
- Changing the FNV payload orphans old `readcon.db` directories: the keys do not match the new id. Leave old databases readable. New runs use a new `readcon.db` or accept that `get_frame` of the old id misses. Do not write a migration that rehashes every blob in the client.

---

## eOn Python server

Files: `pyproject.toml`, `pixi.toml`, `eon/fileio.py` (`loadcon`, `loadcons`, `savecon`), `eon/structure.py` (`Structure.from_conframe`, `Structure.to_conframe`), `eon/concorpus.py` (`traj_id`, `mirror_con_text`, `store_frame_text`), `eon/geometry/cell.py`, `eon/atoms.py`.

### What changes

Lower bounds become `readcon>=0.17.1` and `readcon-db>=0.1.9`. The pixi lock records the wheels that produced the golden. `readcon-ops` stays at `4d7881a` until the ops section lands, then the rev moves. Do not pretend `>=0.15` still satisfies the byte test.

`savecon` already calls `write_con` / `write_con_string` without `precision`. After the pin that is RoundTrip. Pass nothing new. Do not add `precision=17` to "match the client". The client is moving off 17.

`Structure.from_conframe` prefers `coords_array()`, and that method walks the Python atom list (`src/python.rs` `coords_array`). A parsed frame's column accessor is the `xyz` getter: when `inner` is set it copies `positions.f64_slice()` once. `from_conframe` takes `np.asarray(frame.xyz)` and deletes the per-atom coordinate fallback. Ids and fixed masks stay on `atom_ids_array` / `frame.atoms`, because 0.17.1 has no SoA id getter on the Python object. `atom_ids_array` is the id column, despite a docstring that says atomic numbers.

`Structure.to_conframe` builds an `Atom` list because that is the `ConFrame` constructor. `PyConFrame::to_con_frame` then `add_atom`s. There is no `from_columns` on the Python module. Do not invent a second writer in eOn to avoid the `Atom` list. The bytes come from `write_con` with `precision` omitted. If a profile of `savecon` shows the `Atom` loop, the library addition is a `ConFrame.from_columns(cell, angles, symbols, coords, fixed, atom_ids, masses)` that fills `positions_mut` once and calls `build`. That is a readcon-core change with a Python test against `restart_exact.con`. It is not a blocker for the pin, and eOn does not grow a private serializer while waiting for it.

`length_angle_to_box` / `box_to_length_angle` (`eon/geometry/cell.py`) duplicate `cell_vectors` / `lengths_and_angles` and the client's triclinic block. The CON bridge calls the readcon functions (they are exposed on the frame: `cell`, `angles`, and metadata `lattice_vectors`). Keep `cell.py` only for callers that are not reading or writing CON. `structure.py` stops using it for `from_conframe` / `to_conframe`.

`concorpus.traj_id` hashes `path + NUL + text`. Change it to the path only, the same FNV constants already in the file (`_FNV_OFFSET`, `_FNV_PRIME`), matching `ReadconDbMirror.cpp`. `mirror_con_text` on append currently inserts a one-frame trajectory under an id that changes every time the file grows (`savecon` calls `_mirror_con_text` with only the new frame's text). That cannot be indexed as the movie.

- Stable id from the path.
- `savecon` of a full rewrite calls `append_trajectory_str` once with the file (groups inside the db).
- `savecon(..., w='a')` buffers until 64 frames or until the process drops the corpus cache, then `extend_trajectory` of that batch.
- `store_frame_text` stays a one-frame insert for a saddle in the process catalog (`eon/process_catalog.py`). A single restart is not a group. Return `(traj_id, 0)` still, with the path id, so a later catalog lookup uses `get_frame_text(traj_id, 0)`.

`loadcon` / `loadcons` keep reading the `.con` through `read_first_frame` / `read_con`. The file is the authority. Add a catalog read that uses `get_frame` when the caller has a `(traj_id, frame_idx)` from `store_frame_text`, which `process_catalog.py` already wants ("saddle frame from readcon.db"). That path uses the indexed get, not a rescan of `states/` directories.

### API it needs

`readcon.read_first_frame`, `read_con`, `read_con_string`, `write_con`, `write_con_string` (no precision), `ConFrame.xyz` / `vel` / `frc`, `atom_ids_array` for ids, the existing `Atom` constructor, `cell` / `angles`. Optional, not required to ship the pin: `ConFrame.from_columns` filling `positions_mut`.

`readcon_db.ConCorpus.append_trajectory_str`, `append_trajectory_frames` (the 0.1.9 method that does not shell out to the wheel), `extend_trajectory`, `get_frame`, `get_frame_text`, `get_frame_texts`.

### Order

After the C++ writer matches the golden, and after readcon-db 0.1.9 is the pin. Then: bounds, `to_conframe` / `from_conframe`, `traj_id`, grouped append. Ops pin last, in the same PR as the ops change or immediately after it.

### CI

`tests/test_fileio_readcon.py`, `tests/test_structure_readcon.py`, `tests/test_concorpus.py`, `tests/test_process_catalog.py` stay. Add:

- `savecon` of the shared fixture `cmp`s `restart_exact.con`.
- The same Structure written by `savecon` and by the C++ client's `matter2con` (a checked-in file produced by the Catch2 test, or a subprocess if the client is on `PATH` in that job) is byte-identical.
- `loadcon` of a v0.16 file from `tests` still returns the same positions, ids, and free mask the current test asserts. That is the regression. The new file's bytes are allowed to differ from a precision-17 `savecon` of last week.
- `test_concorpus.py`: 64 appended frames, `get_frame_text` of index 0 and 63 equals the corresponding `write_con_string` slice, and a select on the formula returns that trajectory. If `readcon_db` is absent the test skips, matching `concorpus.py`. The job that claims to prove the corpus installs 0.1.9 and must not skip.
- `tests/test_atoms_without_minimage.py` still imports. Ops behaviour (spacegroup, rotational match) is unchanged for a `Structure` because `atoms.py` passes the protocol object (`r`, `box`, `names`), not a `ConFrame`. One test passes a `ConFrame` from `read_first_frame` through `readcon_ops.as_frame` and checks `r` bitwise against `frame.xyz`. `_is_protocol` runs first, so do not add `cell` to `Structure` or a Structure that also grows `cell` will be read as a protocol object only when `r` is present, which is fine, and as a ConFrame only when `r` is absent.

### Risks

- `write_con_string` of a `Structure` that never set units depends on the builder default. The client sets headers explicitly. The cross-`cmp` fails if the server omits line 1 or the units object. `to_conframe` must keep `prebox_header=["Generated by eOn", ""]` and must let the 0.17.1 constructor stamp units, and the golden must be built the same way.
- Append buffering in `savecon` changes when `mirror_con_text` becomes visible. A test that appends once and immediately selects the corpus sees nothing until flush. Flush at the end of `savecon` when the caller is not in a tight movie loop, and flush every 64 inside the loop. `recycling.py`, `escaperate.py`, and `tools/akmc-cna.py` call `savecon` and must either see the frame (single-frame flush for `w='w'`) or document the 64-barrier for `w='a'`. Simplest rule that still groups: `w='w'` mirrors immediately; `w='a'` buffers and flushes at 64 and on process teardown of the corpus cache. Tests that append once and read the **file** are unaffected. Tests that append once and read the **corpus** must flush. `test_concorpus.py` uses `w='w'` today (`io.savecon(str(dest), atoms)`), so it stays immediate.
- Two implementations of FNV (C++ and Python) drift if one hashes a trailing slash. Both use `Path.resolve` / `weakly_canonical` and hash those bytes with no NUL. A unit test vectors the same path in both languages. One checked-in digest is enough.

---

## chemparseplot

Repository `HaoZeke/chemparseplot`, commit `4e4095b`. Python. Core dependencies are numpy and pint. readcon is optional: `pyproject.toml` extras `neb` and `test`, and `pixi.toml`, all say `readcon>=0.14.5` (the comment names eOn 3.2 `con_spec_version=3`; 0.13 raises `UnsupportedSpecVersion`). The CON boundary the package already claims is `chemparseplot/parse/eon/con_io.py`.

### What the code does today

`con_io.py` is the intended single path. `read_con_frames` calls `readcon.read_con`. `read_con_as_ase` calls `readcon.read_con_as_ase`. `read_first_atoms` takes `[0]` of that full-file ASE conversion. `write_con_frames` calls `write_con` with no `precision` argument, which is RoundTrip once the pin is 0.17.1. `write_atoms_as_con` does `ConFrame.from_ase` and then `frame_with_energy`. `_readcon` raises `ImportError` whose text still says `readcon>=0.7.0`. `tests/parse/test_readcon_boundary.py` asserts that string.

`frame_with_energy` always builds a new `ConFrame(cell, angles, atoms, prebox_header, postbox_header, metadata_dict)` and then calls `set_energy`. The Python constructor (`src/python.rs`) stores `inner = None`, so a later `xyz` read of that object walks atoms via `coords_array` instead of the parsed column. The same function still has a string-metadata fallback (`metadata_dict["energy"] = str(value)`) for a wheel with no `set_energy`. 0.17.1 has `set_energy`. A string energy is not the numeric metadata the 0.17 writer emits.

`to_con_frame` writes from the Python `Atom` list (`x/y/z`, and `dx/fx/sx/...` when set), not from `inner`. A reconstructed frame keeps displacements, forces, and spreads only when those fields are still on the `Atom` objects. `from_ase` does not carry `dx` or `sx`. `read_con_as_ase` / `to_ase` (`ase_from_pyconframe`) copies `atom.x/y/z`, not `frame.xyz`. On a frame just returned by `read_con` those match. After an in-place atom edit they do not.

Callers that already stay on this module:

- `_trajectory_common.py`: `resolve_movie_file` (stem or `stem.con`), `read_first_structure` → `read_first_atoms`, `load_movie_and_table` → `read_con_frames` then `frame.to_ase()`, with a metadata table (`frame.energy`, `frame.frame_index`, `frame.metadata`) and a sidecar TSV fallback. It does not import readcon at module level.
- `frame_series.py`: `energies_from_frames`, `atoms_list_from_frames` (`to_ase` plus `atoms.info["energy"]`), `neb_path_arrays`, `min_trajectory_from_frames`, `dimer_trajectory_from_frames`. The module docstring already says the plot packet is a `ConFrame` sequence.
- `dimer_trajectory.py` `parse_climb_con` and `min_trajectory.py` `parse_min_con` call `con_io.read_con_as_ase`. `load_dimer_trajectory` uses `load_movie_and_table` on `climb`, plus optional `reactant.con` / `pos.con`, `saddle.con`, and `mode.dat` via `np.loadtxt`. These two files are the only `parse/eon` modules allowed a top-level `import readcon` (`test_readcon_boundary`).
- `stitch.py` `stitch_neb_segments` reads with `read_con_frames`, shifts energies through `_frame_with_energy` → `frame_with_energy`, and writes `neb.con`, `neb_path_000.con`, and `sp.con` with `write_con_frames`. An override saddle is `to_ase()` then `write_atoms_as_con`. `neb_000.dat` is a hand-written TSV (`%.6f`). `_cartesian_rmsd` uses `atoms.get_positions()`.

Bypasses, all of which parse `.con` with ASE's eon reader:

- `parse/eon/neb.py` imports `ase.io.read` and calls it on the band `con_file`, `sp_file`, and additional structures (`load_structures_and_calculate_additional_rmsd`, `_process_single_path_step`). The boundary test forbids `ase.io.write` under `parse/eon` and does not forbid `ase.io.read`.
- `parse/surrogate/gpr_optim.py` `_read_saddle` uses `ase.io.read(..., format="eon")` and returns raveled positions. `read_atom_types` uses `format="eon"` when the suffix is `.con`.
- Tests still mint inputs with `ase.io.write(..., format="eon")`: `tests/parse/test_dimer_trajectory.py`, `tests/parse/test_min_trajectory.py`.

Left alone, because they are not CON:

- `parse/grammar/xyz.py` (`parse_xyz_text` / `write_xyz_text`).
- `plot/neb.py` `ase_write` of PNG and XYZ for structure strips.
- `parse/sella/saddle_search.py` ASE `.traj` read and write.
- `parse/eon/gprd.py` ASE trajectories.
- `parse/trajectory/neb.py` `load_trajectory`, documented as extxyz.
- `parse/surrogate/mlneb.py` `predicted.traj` / `evaluated.traj`.
- `util.py` `ase.io.read` of `POSCON_FILENAME`.

There is no readcon-db import. `chemparseplot/api.py` does not define `load_trajectory`, `plot_con_overview`, or `plot_con_overlay`. rgpycrumbs `eon/plt_con.py` imports those three names from `chemparseplot.api` today, and its unit test stubs the module, so the missing names are invisible to `tests/test_plt_con.py`.

### What changes

`neb`, `test`, and `pixi.toml` become `readcon>=0.17.1`. The install hint in `_readcon` and the assertion in `test_readcon_boundary.py` say `readcon>=0.17.1`.

`con_io` keeps the function names it already exports. The bodies change as follows.

- `read_first_atoms` calls `readcon.read_first_frame` and then `to_ase`. It stops parsing the rest of the movie. `read_first_frame` is on 0.17.1 (`src/python.rs`).
- `read_con_frames` stays `read_con` for a whole movie. Plotting a band needs every frame; this is not a corpus `get_frame`.
- `frame_with_energy` copies the frame through the `ConFrame` constructor (so `Atom` sections travel) and calls `set_energy`. The string-metadata branch and the `set_scalar_metadata` branch go away. A wheel without `set_energy` fails the import hint instead of writing `energy` as text.
- Add `frame_with_positions(frame, positions)`. It copies each `Atom`, writes `x/y/z` from the `(N, 3)` array, and leaves `fixed`, `atom_id`, `mass`, velocities, forces, displacements, and spreads. This is the geometry update. `from_ase` is reserved for a structure that was never a `ConFrame`.
- `write_con_frames` keeps `write_con` with `precision` omitted and `canonical` left off. `write_atoms_as_con` stays `from_ase` plus `frame_with_energy` for ASE-born structures. Document that this path drops displacements and spreads and applies the 0.17.1 tag-to-id rule (distinct non-negative tags only).

`parse/eon/neb.py` loads `.con` through `con_io.read_con_as_ase`. `gpr_optim._read_saddle` becomes `np.asarray(read_first_frame(path).xyz).ravel()`. `read_atom_types` on a `.con` takes symbols from that same frame and maps them with `ase.data.atomic_numbers`. Other suffixes stay `ase.io.read`. `stitch.py` keeps writing through `write_con_frames`. The saddle override that currently does `to_ase` then `write_atoms_as_con` writes the original frame via `frame_with_energy` and `write_con_frames`, so `sp.con` is not a `from_ase` rebuild when the source was already a `ConFrame`.

`chemparseplot.api` gains the three names `plt_con` already imports:

- `load_trajectory(path)` uses `con_io.read_con_frames` for `.con` / `.convel` and `ase.io.read` otherwise. The returned object exposes `energies` (from `frame.energy`), `n_frames`, `source` (`"con"` or the ASE format), and a polars `table` with `fmax` taken from `frame.frc` when the forces section exists. Positions for a later strip come from `frame_series.atoms_list_from_frames`.
- `plot_con_overview` and `plot_con_overlay` live next to the other plot helpers and are re-exported. They draw; they do not parse.

`tests/parse/test_readcon_boundary.py` grows a ban on `ase.io.read` and `format="eon"` under `chemparseplot/parse` except `parse/trajectory/neb.py`, `parse/sella/`, `parse/eon/gprd.py`, and `parse/surrogate/mlneb.py`, which are traj/extxyz. Fixture helpers `_write_con` in `test_dimer_trajectory.py` and `test_min_trajectory.py` switch from `ase.io.write(..., format="eon")` to `write_atoms_as_con`. An ASE eon fixture is not a legal 0.17.1 input (fixed-flag tokens, missing units, non-finite energies).

No `readcon-db` dependency. A campaign index stays in eOn. This package reads files.

### API it needs

`readcon.read_con`, `read_first_frame`, `read_con_as_ase`, `write_con` (no precision, canonical off), `ConFrame`, `ConFrame.from_ase`, `ConFrame.set_energy`, `Atom` (sections included), getters `xyz`, `vel`, `frc`, `disp`. `to_ase` remains the plot adapter. Geometry assertions use `xyz`, not `get_positions()`, except where the assertion is specifically about the ASE adapter.

Not used here: `coords_array` as the coordinate source, `readcon-db`, DLPack, the C++ builder.

### Order

After eOn's C++ and Python writers match `restart_exact.con`. Inside this repository: pin, then `con_io` (hint, `read_first_atoms`, `frame_with_energy`, `frame_with_positions`), then the ASE `format="eon"` deletions, then fixture writers, then `api.load_trajectory`, then the byte test. rgpycrumbs waits until this `con_io` is the module it imports.

### CI

`.github/workflows/build_test.yml` (`uv sync --all-extras`, pytest on 3.10–3.12) and `ci_coverage.yml` (pixi env `test`). Add to `tests/parse/test_con_io.py`:

- `write_con_frames` of `[read_first_frame("restart_exact.con")]` `cmp`s the golden. Same for `restart_exact_vel.con`. Canonical stays off.
- `frame_with_energy` on that frame: `xyz` bits match the input `xyz` (`tobytes` of the float64 array), `disp` matches when the fixture has displacements, and `energy` equals the new finite value. The output file is not byte-identical to the input, because the energy line changed.
- `frame_with_positions` changes one coordinate and leaves `dx/fx/sx` equal bitwise on the other atoms' sections.
- `read_con_as_ase` positions on a fresh `restart_exact.con` match `frame.xyz` bitwise. That locks `to_ase`'s `atom.x` copy to the column for a frame nobody has edited.
- `read_first_atoms` on a two-frame file returns frame 0 and does not require the second frame to be a legal 0.17 document for the assertion to run. Implementation check: it called `read_first_frame`.
- Regression: `load_movie_and_table` still prefers frame metadata over the sidecar TSV, and `stitch_neb_segments` still writes `neb.con`, `neb_path_000.con`, `neb_000.dat`, and `sp.con`. The dat file stays `%.6f`. Grammar XYZ tests are unchanged.

### Risks

- `frame_with_energy`'s constructor clears `inner`. Code that does `read_con`, rewrites energy, then reads `xyz` is on the atom walk. The byte test uses a frame that was not mutated before the copy, so atom coordinates still equal the column. A test that edits `atoms[i].x` and then expects `xyz` to return the old column is the other contract.
- `from_ase` on 0.17.1 uses ASE tags as ids only when they are distinct and non-negative. `write_atoms_as_con` of a tagged `Atoms` can renumber ids. `sp.con` from a `ConFrame` must not take that path.
- Rebuilding with `build` stamps minor 1 and `default_v3_units_json` (no `time` key). A velocity frame without `units.time` fails. `restart_exact_vel.con` carries `(amu*angstrom^2/eV)^0.5`. A stitched band has no velocities.
- Two atoms of one symbol with masses further apart than `TYPE_MASS_ABS_TOL` fail `build` with `MassMismatch`. Parsed eOn files already share a mass per symbol. An ASE structure with per-atom masses that disagree has to collapse to the first mass of that symbol before `from_ase`, and a test owns the error.
- `set_energy` rejects a non-finite value. Stitch must not feed NaN from a missing `frame.energy`. That is a data error, surfaced, not written as the string `"nan"`.
- Moving `neb.py` off ASE changes cell construction for a sheared cell if ASE's eon reader and readcon's lengths-and-angles differ by an ulp. The regression check is Cartesian `xyz` bits against the golden, not ASE's cell matrix.

---

## rgpycrumbs

Repository `HaoZeke/rgpycrumbs`, commit `73ddf2e`. Python dispatcher. `pyproject.toml` does not depend on readcon; the comment says plotting stays chemparseplot and eOn config authorship uses `eon-schema`, not `eon-akmc`. readcon enters through pixi, `ensure_import`, and PEP 723 script headers.

### What the code does today

Pins that actually install a wheel:

- `pixi.toml`: `readcon >=0.14.5`, `chemparseplot >=1.11.0,<2` and another `>=1.11.0`.
- `rgpycrumbs/_aux.py` maps `"readcon"` to `"readcon>=0.14.5"` for `ensure_import` / `uv`.
- PEP 723 floors are not one number. `plt_con.py` says `readcon>=0.13.1` and `chemparseplot[neb,plot]>=1.9.17,<2`. `con_splitter.py`, `gen_dimer.py`, `plt_kmc.py`, `plt_min.py`, `plt_neb.py`, `plt_neb_stitch.py`, `plt_saddle.py`, and `uma/prepare_aoti.py` say `>=0.14.5`. `tls_pairs.py` says `>=0.14.9`. `modes_tensormap.py` says `>=0.15.0`. `pimd_centroid.py` says `>=0.16.0` because it writes the spreads section. `tests/test_uma_cli.py` asserts the source contains `readcon>=0.14.5`. `tests/test_con_splitter_readcon.py` accepts any floor at or above 0.7.

`cli.py` treats `readcon` and `chemparseplot` as the in-env stack (`_IN_ENV_STACK_MODULES`). The comment says a missing stack breaks plots of readcon-core CON from eOn 2.16+.

CON reads and writes:

- `eon/con_splitter.py` is a second writer beside `con_io`. `_read_trajectory_frames` uses `read_con` and `frame.to_ase`, copying `frame.energy` into `atoms.info`, and falls through to `ase.io.read(index=":")` for any other suffix. `_apply_frame_energy` duplicates `frame_with_energy` (`set_energy`, `set_scalar_metadata`, reconstruct, then energy as a string). `_write_con_atoms` and `_write_con_frame` call `write_con` with no precision. If alignment replaced the atoms, the write is `ConFrame.from_ase`, which drops displacements, spreads, and forces that lived only on the source frame. Alignment itself is `rgpycrumbs.geom.api.alignment.align_structure_robust`.
- `eon/seed_dimers.py` (top-level `import readcon`) reads `neb.con`, takes energies from `ConFrame.energy`, and `write_con`s the peak frame to `pos.con` (the original frame object). `displacement.con` is `ConFrame.from_ase` of a shifted copy. `direction.dat` is `np.savetxt` with `fmt="%18.12f"`. Position comparison in `_match_eon_mode` uses `to_ase().get_positions()`. `eon/gen_dimer.py` is the CLI over `seed_dimers_from_peaks`.
- `eon/pimd_centroid.py` reads a reference with `read_con` and copies `symbol`, `mass`, and `fixed` off `ref.atoms`. `build_frames` constructs one `Atom` per site, including `sx/sy/sz` and `atom_id=i`, then `ConFrame(cell, angles, atoms, metadata)`. `main` calls `write_con` once for every frame. That is a real multi-frame CON writer. It does not open a corpus.
- `eon/modes_tensormap.py` `read_modes` is read-only: `read_con` of `modes.con`, `frame.disp`, and metadata `mode_eigenvalue`, `hbar_omega`, `wavenumber` into a metatensor `TensorMap`.
- `eon/helpers.py` `load_profile_rows` reads a `.con` band with `read_con` and metadata keys `reaction_coordinate`, `relative_energy`, `parallel_force`, plus optional `reaction_coordinate_mw` and `lowest_eigenvalue`. A legacy `neb_*.dat` stays `np.loadtxt`.
- `eon/tls_pairs.py` uses `read_con(...).to_ase()` and frame metadata. `eon/plt_kmc.py` `collect_kmc_n2_timeline` reads `reactant.con` with `read_con` and `to_ase`. `eon/plt_saddle.py` uses `read_con_as_ase` for the product reference.
- `uma/_io.py` `load_atoms`: `.con` / `.convel` through `ensure_import("readcon")` and `read_con`, first frame, `to_ase`. Anything else is `ase.io.read`. The docstring says there is no local format parser.
- `eon/plt_neb.py`, `plt_min.py`, and `plt_neb_stitch.py` do not parse CON themselves. They call chemparseplot (`load_min_trajectory`, `load_dimer_trajectory`, `stitch_neb_segments`, `parse.eon.neb`). Their PEP 723 header is the pin that selects the wheel.
- `eon/plt_con.py` plots by calling `chemparseplot.api.load_trajectory`. Those names are absent on chemparseplot `4e4095b`, as the chemparseplot section says. The script's own pin is still `readcon>=0.13.1`.

ASE reads of a `.con` path, outside readcon:

- `xts/saddle/cuh2.py` `_cuh2_min` and `xts/cuh2/datgen.py` `get_from_gitroot_con` call `ase.io.read` on `cuh2.con`.
- `eon/to_mlflow.py` `ase.io.read(traj_file)` for an optional trajectory, and `ase.io.write(..., format="png")` for the figure.
- `chemgp/match_atoms.py`, `geom/detect_fragments.py`, and `eon/ptmdisp.py` call `ase.io.read` on whatever path the user passed, which may be a `.con`.

`tests/test_cli_plotting.py` `_write_con_file` and `tests/test_deep_coverage.py` write fixtures with `ase.io.write(..., format="eon")`. `tests/test_con_splitter_readcon.py` checks that splitter preserves energies through readcon. No readcon-db use anywhere in the tree.

### What changes

One floor, everywhere a wheel is selected: `readcon>=0.17.1`. That is `pixi.toml`, `_aux.py` `"readcon"`, and every PEP 723 header listed above, including `pimd_centroid.py` (spreads already forced 0.16; minor-1 units force 0.17.1) and `plt_con.py` (the 0.13.1 floor would let `uv run` install a reader that rejects the file the library pin accepts). `tests/test_uma_cli.py` asserts `readcon>=0.17.1`. The con_splitter floor check asserts `(17, 1)` rather than `(0, 7)`.

chemparseplot `con_io` is the CON facade this package calls. rgpycrumbs does not grow its own `write_con` wrapper.

- Delete `con_splitter._apply_frame_energy`, `_write_con_atoms`, and `_write_con_frame`. Unaligned CON output calls `con_io.write_con_frames` on the original frame (energy through `frame_with_energy` when the splitter changed it). Aligned output calls `con_io.frame_with_positions` and then `write_con_frames`, so forces and displacements on the source frame survive. Non-CON inputs stay `ase.io.read` and, when the destination suffix is `.con`, `write_atoms_as_con`.
- `seed_dimers_from_peaks` writes `pos.con` with `con_io.write_con_frames([peak_frame])`. That is the restart: the parsed frame, RoundTrip, no `from_ase`. `displacement.con` is a new geometry (`from_ase` of the shifted atoms, or `frame_with_positions` on a copy of the peak). `direction.dat` stays `%18.12f`. Energies still come from `ConFrame.energy`. `_match_eon_mode` compares `frame.xyz`, not `get_positions()`.
- `pimd_centroid.build_frames` keeps building `Atom` rows with `sx/sy/sz`. That is the spreads section, and 0.17.1 still has no `from_columns`. `main` writes with `con_io.write_con_frames`. Masses come from the reference frame; two atoms of one symbol that disagree past `TYPE_MASS_ABS_TOL` collapse to the first mass of that symbol before `ConFrame` build, matching the builder rule in the shared section. The reference read is `con_io.read_first_atoms` only for the ASE view; the template needs `symbol/mass/fixed`, so it uses `con_io.read_con_frames(reference)[0]` (one frame file) or `read_first_frame` via a con_io helper. Do not walk the trajectory twice.
- `read_modes`, `load_profile_rows`, `tls_pairs`, `plt_kmc`, and `plt_saddle` call `con_io.read_con_frames` / `read_first_atoms` / `read_con_as_ase`. `frame.disp` stays the displacements accessor (`modes_tensormap.read_modes`). Metadata keys stay as they are.
- `uma/_io.load_atoms` sends `.con` / `.convel` through `con_io.read_first_atoms`. `ensure_import` grows a `"chemparseplot"` spec only if the UMA script does not already import it; the read itself is not a private parser.
- `cuh2.py` and `datgen.py` load `cuh2.con` with `read_first_atoms`. `to_mlflow`, `match_atoms`, `detect_fragments`, and `ptmdisp` branch on the suffix: `.con` / `.convel` through `con_io`, every other suffix through the ASE reader they already use. PNG and XYZ writes stay.
- Fixture writers `_write_con_file` and the `format="eon"` helpers under `tests/` call `write_atoms_as_con`.

No corpus client. Movies are the files eOn wrote. A later catalog read would call readcon-db from eOn, not from a plot script.

### API it needs

From chemparseplot, after that package's section has landed: `con_io.read_con_frames`, `read_con_as_ase`, `read_first_atoms`, `write_con_frames`, `write_atoms_as_con`, `frame_with_energy`, `frame_with_positions`, `is_con_path`, and `chemparseplot.api.load_trajectory` / `plot_con_overview` / `plot_con_overlay`.

From readcon, only where `con_io` does not wrap the constructor: `Atom` with `sx/sy/sz` inside `pimd_centroid.build_frames`, and `frame.disp`, `frame.xyz`, `frame.energy`, `frame.metadata` on frames `con_io` returned. `write_con` is not called from rgpycrumbs once `write_con_frames` is the writer. No precision argument, no `canonical=True`, no readcon-db.

### Order

After chemparseplot's `con_io` byte test is green on 0.17.1. Inside rgpycrumbs: move every pin in one commit (a script left on `>=0.14.5` reinstalls the old wheel under `uv run`), then delete the splitter writer, then point seed-dimer and centroid writes at `con_io`, then the ASE `.con` reads, then the tests that lock the old pin string. `plt_neb` / `plt_min` / `plt_neb_stitch` need no parser edit once their header and the chemparseplot pin agree.

### CI

`.github/workflows/ci_test.yml`: the uv job runs `pytest -m pure` and `--pep723-check`; the pixi job runs the `fragments` and `surfaces` envs. readcon is installed by pixi and by the script headers, not by the `test` extra. The byte tests `importorskip("readcon")` and run in the job that has the wheel (pixi, or uv with the PEP 723 dependency). Add:

- `write_con_frames` of the parsed `restart_exact.con`, reached through `con_splitter` with alignment off, `cmp`s the golden. Alignment on is a different file: `xyz` bits match the aligned coordinates, and a source displacement section is still present bitwise. That is the regression the `from_ase` rewrite would fail.
- `seed_dimers_from_peaks` writes `pos.con` byte-identical to `write_con` of that same peak frame with precision omitted. `displacement.con` is a new frame; its `xyz` matches the shifted positions bitwise and it is not compared to `pos.con`. `direction.dat` stays the savetxt.
- `pimd_centroid` of a two-bead fixture writes `centroid.con` that `read_con` accepts, with `spreads` present and positions equal to the centroid bitwise. A second `write_con_frames` of those frames `cmp`s the file (RoundTrip of a frame this process just built).
- `read_modes` on a one-mode `modes.con` returns `frame.disp` bitwise. `load_profile_rows` still reads `reaction_coordinate` from metadata and still `loadtxt`s a `.dat`.
- `tests/test_uma_cli.py` and the con_splitter floor assertion match `0.17.1`. `tests/test_plt_con.py` still stubs `chemparseplot.api`; a separate test imports the real `load_trajectory` when chemparseplot is installed and checks `energies` against `frame.energy`.
- Regression: `plt_neb_stitch` still calls `stitch_neb_segments`. XYZ, PNG, and `mode.dat` tests stay.

### Risks

- Split pins are the failure mode. `plt_con.py` at `>=0.13.1` next to pixi at `>=0.17.1` installs two readers. One commit moves `pixi.toml`, `_aux.py`, and every PEP 723 header.
- `con_splitter` rewriting through `from_ase` silently drops `dx` and `fx`. `frame_with_positions` exists so the aligned file keeps them. A test with a displacements section is what makes that drop visible; energy-only tests stay green either way.
- `pos.con` from `write_con([peak_frame])` is bit-exact only when the source `neb.con` was itself RoundTrip. A precision-17 band from an old eOn is re-spelled on the way out. The restart check uses `restart_exact.con`, not an archived precision-17 movie. Coordinates of a freshly parsed frame still match `xyz` bits after the rewrite when the source values were exact f64.
- `build_frames` with `mass=None` passes `0.0` into `add_atom` (`to_con_frame` uses `unwrap_or(0.0)`). A reference file is required for production centroids so the type mass is the reference mass. A missing reference with symbols and a cubic cell is the explicit fallback already in `_template`; that fallback has no per-type mass and must pass one mass per symbol rather than a mix of `None` and a number.
- `plt_con` against chemparseplot `4e4095b` raises `ImportError` for `load_trajectory`. Shipping the rgpycrumbs pin bump before the chemparseplot API names exist breaks `plt-con` in any environment that does not stub the module. The order above is the constraint.
- `test_cli_plotting.py` fixtures written with ASE `format="eon"` fail to parse on 0.17.1 for the same reasons as in chemparseplot. Convert the helpers with the pin, not after CI goes red.

---

## readcon-ops

Repository `lode-org/readcon-ops`, pin `4d7881a` from eOn `pixi.toml`. `src/readcon_ops/frames.py` `_from_conframe`.

### What changes

`_from_conframe` already prefers `obj.xyz` over the atom loop (`src/readcon_ops/frames.py`). On a 0.17.1 `ConFrame`, `xyz` is the getter that copies the parsed column. `coords_array` walks atoms. Ops must not switch to `coords_array`. Leave the `xyz`-then-atoms order. Masses still come from `atom.mass`; that walk is the species list, not the coordinate path.

The cell uses metadata `lattice_vectors` when present, otherwise `lengths_angles_to_cell`. That function stays. Ops does not depend on readcon-core (`pyproject.toml` has no readcon runtime requirement). Do not add one. The accessor stays duck-typed, which is what `_is_conframe` already does.

No restart writer. No corpus. The code change is a test, not a new parser. The eOn pin of ops moves only so that test is what eOn runs. If `xyz` on the installed `ConFrame` is already the SoA getter, the rev can stay at `4d7881a` until ops itself needs a commit. Do not churn the pin for its own sake.

### API it needs

`xyz` as an `(N, 3)` array, `cell`, `angles`, `atoms` with `symbol` and `mass`, optional `metadata["lattice_vectors"]` and `metadata["pbc"]`. `xyz` on a parsed 0.17.1 frame is the column copy. `coords_array` is the atom walk and is the wrong source for this function.

### Order

After eOn's frames are 0.17.1. Ops at `4d7881a` already has the `xyz` branch. Add the byte test on ops `main` and point eOn's pixi rev at that commit when the test exists. No other ops change gates the eOn writer.

### CI

Ops' own tests plus eOn `tests/test_atoms_without_minimage.py`. Bit-exact: `as_frame(readcon.read_first_frame(restart_exact.con)).r` matches `frame.xyz` with `array_equal`, which is bitwise for finite f64. Regression: a protocol `Structure` (`r`, `box`, `names`) still takes `_from_protocol` and does not start requiring `cell`. `_is_protocol` is checked first, so a Structure that also grows a `cell` attribute would be misread. Do not add `cell` to `Structure`.

### Risks

`xyz` and `coords_array` can disagree if something edited `atoms` and not the Rust column. `as_frame` keeps `xyz`. A test that mutates `atoms[i].x` and expects `as_frame` to notice is a different contract (`coords_array` exists for that). Restart checks use a frame just returned by `read_first_frame`, where `xyz` is the column.

---

## rgsaddle

Repository `OmniPotentRPC/rgsaddle`. `Cargo.toml` features `readcon` and `readcon-db`. `src/io.rs` `frame_from_con`. `src/band.rs` `BandSession`. `src/lib.rs` re-exports `MolecularFrame` and `frame_from_con`.

### What changes

`readcon-core = "0.14"` becomes `"0.17.1"`. `readcon-db = "0.1"` becomes `"0.1.9"`. Both stay optional. Default `cargo test` in `.github/workflows/ci.yml` does not enable them (`--features capi` only). Add a job that runs `--features readcon,readcon-db`.

`frame_from_con` copies each row through `as_f64_row` into a new `Array1`. `MolecularFrame.positions` is `3N` contiguous, which is the builder's flat layout. Construct it from the f64 position slice in one copy (the frame owns the SoA; the session needs an owned buffer it can step). Do not also keep a `Vec<[f64; 3]>`.

`frame_from_con` reads only the first frame. `read_nth_frame` is the indexed read for a band file. Use it when the host asks for image `k`. Do not `read_all_frames` to discard all but one.

Writes, which do not exist today:

- `write_restart(path, frame: &MolecularFrame, symbols, masses, cell)` builds with `ConFrameBuilder`, fills `positions_mut()` from the `3N` slice, `set_energy` when the host has one, `build`, `ConFrameWriter::new`. Symbols and masses are arguments. rgsaddle does not invent elements from coordinates.
- `write_band(path, positions: ArrayView2<f64>, ...)` writes one frame per row of `BandSession::positions`. `BandSession` does not store symbols; the write function takes the same symbol vector as `write_restart`. Endpoints are frames 0 and `n_images - 1`.
- `store_band(corpus, traj_id, frames)` calls `append_trajectory_frames_with_float_format(..., FloatFormat::RoundTrip)` once, so a band under 64 images is one group when the group shrinks, and a longer band groups on index alignment. This is the feature flagged `readcon-db` and described in the `src/io.rs` module comment. There is no call site now. Put it in `src/io.rs` and gate it with `#[cfg(feature = "readcon-db")]`.

`BandSession::restart` (`src/band.rs`) resets the solver. It is not a file restart. Do not overload that method. The file function is `write_restart`.

`cell_from_header` rebuilds a triclinic cell when `lattice_vectors()` is missing. Prefer `header.lattice_vectors()` / `header.cell_matrix()`. Keep the length-angle fallback for a frame that has no matrix. That is the same formula as `cell_vectors`; call `readcon_core::types::cell_vectors` and delete the local `cy` / `cz_squared` block.

### API it needs

`read_first_frame`, `read_nth_frame`, `ConFrameBuilder::{positions_mut, set_energy, set_units, build}`, `ConFrameWriter::new`, `cell_vectors`, `FrameHeader::lattice_vectors`.

`readcon_db::ConCorpus::{open, append_trajectory_frames_with_float_format, get_frame}` and `FloatFormat::RoundTrip`.

### Order

After eOn's golden exists, so `write_restart` is checked against `restart_exact.con` rather than against a private spelling. The read path can bump to 0.17.1 earlier; `tests/io_cells.rs` is the regression for cells.

### CI

`.github/workflows/ci.yml`: keep the default job. Add `cargo test --features readcon,readcon-db`.

- `tests/io_cells.rs` still accepts `triclinic.con` and `exact_lattice.con`.
- New test: `write_restart` bytes equal `restart_exact.con` for the fixture's symbols and cell; `frame_from_con` of that file returns `positions` whose bits match.
- New test: a 4-image band written with `write_band` and stored with `store_band`, then `get_frame` of image 2, matches row 2 bitwise. The corpus is a temp directory.
- Regression: `BandSession` stepping tests (`tests/double_well.rs` and the autoneb tests) stay on the default feature set and do not link readcon. A saddle step does not start writing files as a side effect.

### Risks

- 0.17 rejects NaN, Inf, and a non-integer fixed column. A 0.14 fixture that relied on those will fail at `read_first_frame`. `tests/io_cells.rs` is the place that surfaces it. Fix the fixture, do not relax the parser.
- `MolecularFrame` has positions, masses, and a cell, not symbols or ids. A restart without a caller-supplied symbol vector cannot be a conforming CON file. The signature requires the symbols. Do not default them to `X`.
- Enabling `readcon-db` pulls the db's core. One `Cargo.lock` resolution must be 0.17.1 for both. A direct `readcon-core = "0.17.1"` and `readcon-db` 0.1.9 that pins `=0.17.1` is the resolution. Do not leave `readcon-db = "0.1"` which can float to the 0.1.8 tag and downgrade the parser.

---

## rgmin

Repository `OmniPotentRPC/rgmin`. `src/minimize.rs` `minimize` / `minimize_method`. `src/report.rs` `Report`. `src/session.rs` `Solver`. No structure type, no file IO.

### What changes

Add feature `readcon = ["dep:readcon-core"]` with `readcon-core = "=0.17.1"`, not in `default`. `default` stays `["simd"]`. The C ABI (`capi`) does not grow CON entry points in this step. A C caller that wants a file uses rgsaddle or eOn, which already link the C++ wrapper.

New `src/con_checkpoint.rs`, compiled only with the feature:

- `write_checkpoint(path, report: &Report, symbols: &[String], masses: &[f64], cell: [[f64; 3]; 3]) -> Result<()>`
- Requires `report.coords.len() == 3 * symbols.len()`.
- `ConFrameBuilder::new` from `lengths_and_angles(cell)`, `add_atom` per symbol, `positions_mut().copy_from_slice(report.coords.as_slice())`, `set_energy(report.value)` when `value` is finite, `set_units` to the default v3 object, `ConFrameWriter::new`.
- `read_checkpoint(path) -> Result<(Array1<f64>, f64)>` via `read_first_frame` and the position slice, plus `header.energy()`. This is how a later `minimize` call restarts: the returned array is the `init` argument. rgmin's `Restart` enum (`Method::Nlcg { restart }`) stays the conjugacy reset. The file is not that enum.

`Report` does not gain a path field. Writing is a function the host calls. `Solver::step` does not open files.

There is no trajectory feature here. A minimizer that wants every accepted step in a corpus is rgsaddle's `store_band` or the host's loop calling `write_checkpoint` and `append_trajectory_frames_with_float_format`. Putting readcon-db inside rgmin would make every optimizer link LMDB. Do not.

### API it needs

`ConFrameBuilder::{new, add_atom, positions_mut, set_energy, set_units, build}`, `ConFrameWriter::new`, `read_first_frame`, `lengths_and_angles`, `FloatFormat::RoundTrip` only as the default of `ConFrameWriter::new`.

### Order

After the golden fixture exists. The feature is independent of rgsaddle's band writer, but the byte test should use the same `restart_exact.con` so a checkpoint written by rgmin and read by rgsaddle's `frame_from_con` matches.

### CI

Default `.github` job, if rgmin has one, stays without the feature (`cargo test`). Add `cargo test --features readcon`.

- `write_checkpoint` of the fixture's coordinates and energy `cmp`s `restart_exact.con`.
- `read_checkpoint` returns bits equal to `Report.coords` and the energy.
- `minimize` on a quadratic with `init` from `read_checkpoint` returns the same `Status` and the same final bits as `minimize` started from the in-memory array. That is the regression: the feature does not change `src/minimize.rs`.
- `cargo test` without the feature still compiles `src/lib.rs` with no `readcon_core` symbol. A grep of `nm` on the default staticlib is enough.

### Risks

- `Report.value` may be a non-finite sentinel on `Status::Iterating` paths. `set_energy` of a non-finite value is a 0.17 hard error (`NonFiniteValue` on the way back in). Omit the energy key unless `value.is_finite()`.
- Masses and symbols are not in `Report`. A host that forgets them cannot get a conforming file. The function returns an error on length mismatch rather than writing a header that does not match `3N`.
- Optional dependency drift: `=0.17.1` exact, so a later 0.17.2 does not silently change checkpoint bytes. Bump the pin in a commit that regenerates nothing if the writer bytes are unchanged, and fails CI if they are.

---

## rgpot

Repository `OmniPotentRPC/rgpot`. `pixi.toml` `readcon >=0.14.7`. `scripts/export_uma_aoti.py` `_read_eon_con`. `CppCore/rgpot/rpc/ase_helpers.py` `atoms_from_con`. `tests/eon_min_landscape.py`. `tests/con_relax_demo.py`.

### What changes

`pixi.toml` becomes `readcon >=0.17.1`. No readcon-db requirement in the potential library itself. A campaign of evaluations belongs to the caller (eOn, rgsaddle).

Delete `_read_eon_con` and the local cell builder it uses (`_cellpar_to_cell` in that script, if nothing else calls it). The function reads line 7 as `ntypes`, line 8 as counts, and then symbol / coordinate blocks. It drops fixed flags, ids, sections, and the JSON line. Replace call sites with `atoms_from_con` in `CppCore/rgpot/rpc/ase_helpers.py`, which already calls `readcon.read_con_as_ase`. `read_con_as_ase` on 0.17.1 attaches energy and forces through `SinglePointCalculator` (`CHANGELOG` 0.17.1). The export script wants `Atoms` for a UMA trace; it should take forces from that calculator when the CON file has them, and ignore them when it does not. Do not re-parse.

`tests/eon_min_landscape.py` writes `pos.con` with `aseio.write(..., format="eon")`. That is ASE's writer, not readcon, and it is not the RoundTrip spelling. Write `pos.con` with `readcon.ConFrame.from_ase` and `write_con` without precision. Read the result with `read_con`, which the test already uses for `minimization.con`. The assertion on the last frame's energy stays.

`con_relax_demo.py` already documents the readcon path. Point it at `atoms_from_con` and, after `AnnealOptimizer.run`, write the relaxed atoms with `ConFrame.from_ase` + `write_con`. That is the restart the demo currently does not emit.

No corpus inside rgpot. `AnnealOptimizer.run` mutates `Atoms` and stores `self.result`. The host writes the CON file. Adding LMDB to a potential repository duplicates eOn's mirror.

### API it needs

`readcon.read_con_as_ase`, `read_con`, `ConFrame.from_ase`, `write_con` (no precision), `has_chemfiles_support` only where a test already branches on it. Not the C++ builder. rgpot's C++ core calculates energies; it does not own the CON codec.

### Order

After eOn 0.17.1 so `minimization.con` from a current client is the file `read_con` is tested against. The deletion of `_read_eon_con` can land as soon as the pin is 0.17.1; it does not wait on the mirror work.

### CI

rgpot's existing pytest job.

- A fixture `pos.con` written by `from_ase` / `write_con` `cmp`s the golden when the atoms match the fixture. ASE `format="eon"` output is no longer an input to that compare.
- `atoms_from_con("restart_exact.con")` positions match `read_first_frame(...).xyz` bitwise, and `get_potential_energy()` works when the golden's energy was attached by `to_ase` / `read_con_as_ase`.
- Regression: `tests/eon_min_landscape.py` still checks the last frame of `minimization.con` when an eOn client is present, and skips the same way it skips today when the client is absent. The potential tests (`test_nwchem_params.py`, `test_cpmd_params.py`) do not import readcon.

### Risks

- `_read_eon_con` accepts files 0.17 rejects (float fixed-flags, `NaN`). Any UMA export input that relied on that tolerance breaks at `read_con_as_ase`. Those files are not restarts. Repair the file.
- `from_ase` uses ASE tags as ids only when they are distinct and non-negative (0.17.1). A structure with duplicate tags gets sequential ids. The byte test uses a structure whose tags are `0..N-1` or absent, so the golden does not depend on tag policy. Document that in the test.
- ASE's eon writer remaining anywhere in `scripts/` will silently produce a file the byte test does not cover. Grep `format="eon"` in CI and fail the job if a hit remains outside a comment.

---

## cpmdc

Repository `OmniPotentRPC/cpmdc`. `include/cpmdc_restart.h`, `tools/cpmdc_restart.c`, `tests/test_cpmd_restart.c`.

### What changes

The binary RESTART stays the checkpoint CPMD reads. `cpmdc_restart_read_path`, `cpmdc_restart_coordinates`, `cpmdc_restart_velocities`, `cpmdc_restart_set_coordinates`, `cpmdc_restart_write_path` stay bit-stable. Do not encode wavefunctions, cutoffs, or states (`cpmdc_restart_cutoff`, `cpmdc_restart_states`) into CON. CON has no slot for them.

Add an optional build (`-Dwith_readcon`, off by default) that links `libreadcon_core` and adds one subcommand to `tools/cpmdc_restart.c`:

```
cpmdc-restart con FILE OUT.con
cpmdc-restart con-vel FILE OUT.con
```

`con` writes positions. `con-vel` writes positions and velocities. Implementation in a new `tools/cpmdc_restart_con.c`:

- `cpmdc_restart_coordinates` / `cpmdc_restart_velocities` into a `double` buffer.
- Multiply by `CPMDC_RESTART_ANGSTROM_PER_BOHR` (`0.529177210859`, the constant already in the header). The inverse divide on the way back, matching `cmd` `patch-positions` in `tools/cpmdc_restart.c`.
- Species and counts from `cpmdc_restart_species`. Symbols from a fixed Z table already used by the positions printer, or from `rkr` `z_to_symbol` if the restart stores Z. If the restart stores CPMD species labels, pass those strings through `rkr_frame_add_atom`. Do not invent a second symbol table if `print_triples` already prints a label.
- Cell from `cpmdc_restart_cell` (`celldm`). Convert bohr to angstrom the same way. Set the v3 units object to angstrom / eV / amu, and for `con-vel` the natural time unit. CPMD velocities are in atomic units. The CON file stores the converted values and the unit label. A reader that ignores `units.time` will mis-scale. 0.17.1 will not ignore it. Set the label.
- Write with `create_writer_from_path_round_trip_c`. Fill coordinates through `rkr_frame_builder_positions_data` after `rkr_frame_add_atom`. That is the accessor. Do not `fprintf` a CON file from `print_triples`.

The reverse, `cpmdc-restart patch-from-con OUT.con RESTART IN OUT`, reads the CON with `read_first_frame` / `rkr_frame_xyz_f64`, converts angstrom to bohr, and calls `cpmdc_restart_set_coordinates` then `cpmdc_restart_write_path`. Other RESTART records stay as `patch-positions` already promises. This is how a geometry step in eOn or rgmin returns a CPMD restart without a second coordinate dialect.

No readcon-db in cpmdc. A campaign of CPMD frames is the caller's corpus ingest of the CON sidecar.

### API it needs

C ABI only: `rkr_frame_new`, `rkr_frame_add_atom`, `rkr_frame_builder_positions_data`, `rkr_frame_builder_velocities_data`, `rkr_frame_builder_set_units`, `rkr_frame_builder_build`, `create_writer_from_path_round_trip_c`, `rkr_writer_extend`, `free_rkr_writer`, `rkr_read_first_frame` or `read_con_file_iterator`, `rkr_frame_xyz_f64`, `free_rkr_frame`. Header `include/readcon-core.h` from the v0.17.1 cxx tarball. cpmdc does not run cbindgen.

### Order

After 0.17.1 is tagged, independent of eOn's mirror. The byte test uses a tiny RESTART fixture `tests/` already has (`tests/test_cpmd_restart.c`) plus `restart_exact` only for the pure CON side. A real RESTART will not `cmp` equal to `restart_exact.con` because the coordinates are a conversion of bohr. The equality is: write CON, read CON, patch a copy of the binary, `memcmp` the coordinate section against the source coordinates.

### CI

`tests/test_cpmd_restart.c` stays on the default build, with no readcon link, so a CPMD-only build does not change. The `with_readcon` job:

- `cpmdc-restart con` then `patch-from-con` reproduces the coordinate bytes of the binary section (`memcmp`).
- Velocities the same for `con-vel`.
- The CON file's UTF-8, read by `read_first_frame` in a Rust one-liner or by Python `read_first_frame`, yields f64 bits equal to `bohr * CPMDC_RESTART_ANGSTROM_PER_BOHR` computed in C with the same multiply. Do the multiply in one place (`cpmdc_restart_con.c`) so the test includes that function's result, not a second copy of the constant expression that could be optimized differently. Then compare bits.
- Regression: `cpmdc_restart_write_path` of an untouched file matches the input bytes (existing test). The CON subcommand must not be invoked by that test.

### Risks

- Unit conversion is not bit-exact across a round trip through decimal **and** through a different Bohr constant. RoundTrip preserves the f64 that the multiply produced. It does not preserve the original bohr bits, because `x * 0.529177210859` is a new value. The `memcmp` after patch-from-con checks that the C reader recovered the same f64 the writer converted, and the binary section matches that converted-then-unconverted value only if the inverse multiply is the exact inverse, which it is not for every input. So the contract is: CON bits match the converted f64, and `patch-from-con` writes those converted values back. A test that expects the original bohr bits after a round trip will fail. State that next to the test. Callers that need the original bits keep the binary RESTART, which is unchanged.
- Linking Rust `libreadcon_core` into a C executable pulls `libstdc++` / `libgcc_s` and a staticlib init. Follow the seams approach: optional, and the default CI does not link it. A failure to configure `-Dwith_readcon` is a missing dependency, not a failed CPMD test.
- Species order is CPMD order, which `tools/cpmdc_restart.c` documents as the coordinate order. `build_with_permutation` will regroup by symbol. The C API `rkr_frame_builder_build` does that too. The patch-from-con path must scatter back with the id column (`atom_id` set to the CPMD index at `add_atom`) or the binary section is permuted. Set `atom_id` to the species-major index and apply the inverse permutation on the way back. Test a two-species water restart, not a one-species fixture, or the bug hides.

---

## seams-core

Repository `d-SEAMS/seams-core`. `meson.build` (the `dependency('readcon-core', version: '>=0.16.2')` block and the readcon-db block), `subprojects/readcon-core.wrap` (`91181ef`), `subprojects/readcon-db.wrap` (`0001a2c`), `src/seams_input.cpp` (`sinp::readCon`, `cloudFromHandle`, `sinp::ingestConCorpus`, `sinp::readConCorpus`), `src/include/internal/seams_input.hpp`.

### What changes

`readcon-core.wrap` revision becomes `v0.17.1`. `readcon-db.wrap` becomes the 0.1.9 commit. `meson.build` lower bound `>=0.16.2` becomes `>=0.17.1`, and `readcon-db` `>=0.1.8` becomes `>=0.1.9`. The 0.1.8 bound is satisfied by `0001a2c`, which is the wrong artifact.

`sinp::readCon` already uses `ConFrameIterator::nth`, which skips with `forward_fast` and parses one frame. Keep that. It is the single-pass read. Do not replace it with `read_all_frames`.

`cloudFromHandle` calls `rkr_frame_to_c_frame` and also `rkr_frame_xyz_f64`, then keeps the SoA only when `xyz[1] == atom.y` and `xyz[2] == atom.z`. That comparison is not a layout check. It is a float equality against the first atom, and it falls back to the AoS copy for a frame whose first atom has a `y` that happens to disagree. Delete the heuristic. If `nxyz == num_atoms`, the pointer is the position SoA (row-major). Copy those doubles into `molSys::Point`. Take `atomic_number` and `atom_id` from the `CAtom` row, which is the metadata the SoA does not carry, then `free_c_frame`. One copy into the point cloud is required because `Point` is AoS. A second copy through `atom.x/y/z` is the duplicate.

`sinp::ingestConCorpus` calls `rkrdb_append_trajectory` on the file. That is the batch path, so a multi-frame CON file groups inside 0.1.9. Keep it. Do not read the file in seams and re-append frame by frame.

`sinp::readConCorpus` already selects and decodes. Point the decode at `rkrdb_get_positions` (and the symbol/id fields it still needs from `rkrdb_get_frame` only if positions are not enough). Prefer `rkrdb_get_positions` so a `RKRConFrame*` allocated by the db's vendored core is never freed with seams' `libreadcon_core`. The comment in `meson.build` already says the two cores must not exchange handles. `cloudFromHandle` on a handle returned by `rkrdb_get_frame` is that exchange. Stop doing it. Fill the point cloud from `rkrdb_get_positions` plus `rkrdb_frame_formula` or the text decoded in the db and parsed with **seams'** reader via `read_con_string_iterator` only if the positions ABI is short a symbol. `readConCorpus` in `seams_input.cpp` already has a `read_con_string_iterator` path. One of the two stays: the string parsed by seams' core, or the positions filled from `rkrdb_get_positions`. Not a handle from the other core. The string path re-parses. The positions path is the indexed accessor. Use positions plus a symbol array from the C ABI if 0.1.9 already returns one; if it does not, the string parsed by seams' own `read_con_string_iterator` is the safe choice and the handle from `rkrdb_get_frame` is not stored.

`campaignShardCount` hand-parses `shards.json` for `n_shards`. That is a duplicate of the db's shard manifest reader, and a hand scan can truncate. If 0.1.9's C ABI can open a sharded root, call that. If it cannot (`rkrdb_open` is one env, which the comment in `seams_input.cpp` already says), keep the fan-out but parse `n_shards` with a real JSON reader or the helper the db ships. Do not extend the `find("\"n_shards\"")` scan.

`applyConCell` / `mi_cell_from_con_box` stays. The minimage cell is seams' box, not a second CON writer. seams does not grow a CON writer in this plan. Analysis output that must be a campaign frame calls `rkrdb_append_trajectory` on a file the caller already wrote, or stays a LAMMPS dump. Adding a writer here duplicates eOn.

### API it needs

readcon-core C++: `ConFrameIterator::nth`, `rkr_frame_xyz_f64`, `rkr_frame_to_c_frame`, `free_c_frame`, `read_con_string_iterator`.

readcon-db C: `rkrdb_open`, `rkrdb_append_trajectory`, `rkrdb_get_positions`, `rkrdb_select_campaign`, `rkrdb_result_key`, `rkrdb_get_frame_text`. Not `rkrdb_get_frame`'s bare pointer across the two cores.

### Order

Last. Bump both wraps in one commit so a build cannot see 0.17.1 core beside a 0.16.1 db. Then delete the `xyz[1] == atom.y` heuristic. Then switch `readConCorpus` off the foreign handle.

### CI

`tests/test_readcon.cpp` (`readCon` frame select, missing frame, `readConCorpus`, sharded root) stays.

- `readCon` of `restart_exact.con` frame 1 yields point coordinates whose bits match the golden positions. The current tests check selection, not bits. Add the bit check.
- `ingestConCorpus` of a 64-frame file, then `readConCorpus` of hit 1 and hit 64, returns both. That fails on the `0001a2c` db if the test is written against group redirects and the wrap was not bumped. Good.
- A two-core test: build with both dependencies, ingest, decode, and exit under ASan. Freeing the wrong core's frame is a heap error. The test passes only if `readConCorpus` does not `free` a db handle with seams' core.
- Regression: `readCon` on `con/tiny_multi_cuh2.con` still returns the frame the existing `TEST_CASE`s name. LAMMPS `forEachLammpsFrame` tests are untouched. `nLammpsFrames` stays the dump index, not a CON index.

### Risks

- Wrap `91181ef` is a CI commit from 2026-10-09 ("preserve coverage reports"), not a release tag. Moving to `v0.17.1` changes parse rejection (NaN, fixed-flag tokens, empty headers). `tests/test_readcon.cpp` fixtures from the readcon suite should already be legal. A seams-local fixture that is not legal fails this bump and gets repaired.
- `mi_cell_from_con_box` and `cell_vectors` can disagree on a sheared cell by an ulp. `applyConCell` is the seams box used by linkcell. Do not replace it with a fresh implementation in the same change as the wrap bump, or a geometry failure is ambiguous. The bit check is on atomic coordinates, not on `yCloud.box`.
- Sharded ingest uses `trajId % n_shards`. That mapping stays. Grouping is inside one shard's env. A 64-frame file ingested to one shard groups. A campaign that splits one trajectory across shards by frame will not. `ingestConCorpus` appends a whole path to one shard. Keep that.

---

## What this plan does not do

- It does not change the CON specification. 0.17.1 is already the writer and the reader.
- It does not put a second parser in any consumer. The hand parser in `rgpot/scripts/export_uma_aoti.py` is removed. ASE `format="eon"` reads of `.con` in chemparseplot and rgpycrumbs are removed. The cell reconstructions in `eon/geometry/cell.py` (for the CON bridge), `client/ConFileIO.cpp` `cell_to_lengths_angles`, and `rgsaddle/src/io.rs` `cell_from_header` call `cell_vectors` / `lengths_and_angles` instead.
- It does not make rgmin, rgpot, chemparseplot, or rgpycrumbs open an LMDB. The corpus writers are eOn (the run), rgsaddle (the band), and seams (ingest of a file that already exists). Plotters read the `.con` eOn already wrote.
- It does not fold XYZ, PNG, ASE `.traj`, `mode.dat`, `neb_*.dat`, or `direction.dat` into CON. `chemparseplot/parse/grammar/xyz.py`, `plot/neb.py` image and xyz dumps, sella trajectories, and `np.savetxt` mode files stay.
- It does not replace CPMD's binary RESTART, and it does not try to make `x * BOHR_TO_ANGSTROM` invert onto the original bits.
- It does not treat rgmin's conjugacy `Restart` or `BandSession::restart` as files.
- It does not require canonical JSON. Byte equality is RoundTrip with canonical left off, on `restart_exact.con`.
