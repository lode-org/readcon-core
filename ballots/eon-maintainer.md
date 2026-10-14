# Ballot: eOn production maintainer

Persona: the maintainer of a preempted AKMC, minimization, or dynamics run. The file the job already opens is the resume. The corpus is a copy. A missing `libreadcon_db` must not fail the step, and a second `libreadcon_core` on `PATH` must not stop the binary from starting.

Rules used: a feature counts once a production caller uses it; the working behavior is the baseline a change has to beat; the result is the current library, readcon-core 0.17.1 RoundTrip plus a 64-frame group that a real movie actually stores.

Designs read in full: `design/consumers-A.md` (`97d352e` on `design/consumers-a`), `design/consumers-B.md` (`06044cc` on `design/consumers-b`), `design/consumers-C.md` (`80cf36a` on `design/consumers-c`), and `design/consumers-critique.md` on `design/consumers-decision`. The critique's eight factual errors were checked against the trees below, not taken from the critique.

| Tree | Commit checked |
| --- | --- |
| lode-org/readcon-core `v0.17.1` | `96fd38f` (writer and Python accessors; `main` has since only changed the round-trip float printer) |
| lode-org/readcon-db `main` | `0725c94` |
| lode-org/readcon-db tag `v0.1.8` | `0001a2c` |
| TheochemUI/eOn | `cc4f699` |
| lode-org/readcon-ops | `4d7881a` |
| d-SEAMS/seams-core | `305fb3c` |
| OmniPotentRPC/cpmdc | `c518e1e` |
| HaoZeke/chemparseplot `write_con_frames` | `4e4095b` |
| HaoZeke/rgpycrumbs `write_con` | `73ddf2e` |

## Vote

Rank: **A, B, C**

Confidence that A is the right top pick: **0.86**

Option I expect the other four personas to pick: **A**

## What production resumes today

This is the baseline. I checked it in eOn `cc4f699`.

- `MinimizationJob` and `MonteCarloJob` load `pos_cp.con` only when `main.checkpoint` is set. `relaxMatter` rewrites `{prefix}_cp` through `matter2con`. L-BFGS pairs and FIRE velocity are not in that file. The empty stepper is the resume we ship.
- `SaddleSearchJob` loads `displacement_cp.con` only together with `mode_cp.dat`. `saveMode` prints `%.17g`. `direction.dat` in the seed tools is the same kind of sidecar.
- `Hessian::saveColumnCheckpoint` writes `eon_hess_ckpt` at `precision(17)`. `modes.con` and `instanton_centroid.con` are results.
- `Dynamics::run` appends `dynamics.con` through `matter2con`, which passes `with_velocities=false`. `DynamicsJob` loads `pos.con` via `getRelevantFile` and writes `final.con` the same way. There is no mid-run dynamics resume, and that movie has no velocities.
- Forces are opt-in. The comment in `apply_geometry` says ASE-class readers reject a forces section. `con2matter` calls `restoreFileForces` when a forces section is present, and sets `recomputePotential` when it is not.
- The client writes with `kConPrecision = 17` and `kConvelPrecision = 6` (`FloatFormat::DecimalPlaces`). `eon/fileio.py` `savecon` calls `write_con_string([frame])` with precision omitted. `eon/process_catalog.py` still calls `write_con_string([frame], 17)`.
- `mirror_con_corpus` runs only when `concatenate` is false. The id is FNV-1a of the absolute path, a NUL, and the file text, in both `ReadconDbMirror.cpp` and `eon/concorpus.py`. The return of `rkrdb_append_trajectory_str` is ignored. Windows compiles the mirror out (`#if !defined(_WIN32)`). A missing library returns without changing `IoStatus`.
- An uncompressed tail this process did not write is parsed before any byte is added. Failure returns `IoStatus::AppendError` and leaves the file alone. Gzip and zstd are rewritten as a whole file.
- `client/meson.build` already records `STATUS_ENTRYPOINT_NOT_FOUND` when a second `readcon_core.dll` is earlier on `PATH`. The wrap is `revision = v0.16.0`.

## Why A, then B, then C

A is the only plan that changes the spelling without changing which file a job opens, and the only plan whose eOn mirror can make the 64-frame codec a production feature.

The writer cutover is required. Client files are 17 and 6 decimal places. Once the server wheel is 0.17.1, `savecon` is already RoundTrip, and the two languages stop matching while the wrap stays on `v0.16.0`. A deletes `kConPrecision` and `kConvelPrecision` and constructs `ConFrameWriter` with no precision. That symbol is `create_writer_from_path_c`, which passes `precision = None` and builds `ConFrameWriter::new`. It is already in the core the client links. `matter2con` stays `with_velocities=false`. Forces stay behind `g_write_con_forces`. `InvalidUnits` stays inside the `IoStatus::InvalidArgument` catch `frame_from_matter` already has. `MassMismatch` is collapsed to the first mass of the symbol before `build`, with a log line and a two-Cu test. The append scratch stays, so RoundTrip does not need a new buffer API, and the foreign-tail check stays with it.

The corpus stays a copy. A keeps `dlopen`. A missing `libreadcon_db` still skips. Windows stays a no-op. The trajectory id becomes FNV-1a of the canonical path only, shared by the C++ and Python constants, with no NUL. Streaming appends buffer up to 64 serialized frames under the append lock that already forbids a potential evaluation, then extend that batch once. `group_prepared` returns immediately when `prepared.len() < 2`, and `pack_aligned` emits `0xFD 0x03` only for a run longer than one frame inside that call. A's buffer is the call shape that can produce a group. A crash may drop unflushed corpus frames. The `.con` file is the copy the next process opens. I will not fail an AKMC step to prove a group. Old directories stay readable under the keys they have. A new run uses a new `readcon.db` rather than rehashing blobs during the job.

B keeps the soft mirror and names the catalog call A and C both skip, and then couples three production regressions to the same commit. `Dynamics::run` starts writing velocities, and `DynamicsJob` starts reading the last `dynamics.con` frame when `main.checkpoint` is set. An old movie has no velocities. That is a new job, and it lands in the same change that regenerates `ApproveConFileIO`. The corpus side calls `rkrdb_extend_trajectory_frame` once per step. That prepares one frame, so a dynamics or band movie stays a sequence of `0xFD 0x01` or raw UTF-8. The design describes a group the implementation never stores. `set_canonical(true)` is a separate switch. On 0.17.1 `header.metadata` is a `BTreeMap`, `write_frame` emits sections in a fixed order, and `self.canonical` only disables the metadata cache. The flag does not produce a second spelling today, and it will the day the comment is implemented. The cpmdc `export-con` step multiplies Bohr by `1/0.529177210859`. `print_triples` multiplies by `CPMDC_RESTART_ANGSTROM_PER_BOHR` (`0.529177210859`) to print angstroms, and `patch-positions` divides by that same macro. B's factor is the reciprocal. The client would read the sidecar as angstroms.

C leaves dynamics velocities alone and names the foreign-tail check, and then makes the corpus a load dependency of `eoncbase`. Deleting `dlopen` and linking `readcon-xfer` stacks a second core into the process. `client/meson.build` already says what that costs on Windows. The regression is paid before a checkpoint byte improves. `matter2con(..., append=true)` still hands `trajectory_append` one frame, so the group still does not appear. Checkpoints keep path-plus-text ids while movies use a path-only id, so a resumed job and a plotted movie disagree about which key is current. `checkpoint_write` specifies identical stored text as success. `append_trajectory_str` commits with `replace_meta = false`, and `commit_prepared` returns `TrajExists` as soon as `traj_meta` has that id. The bytes are not compared. `workflow_dedup_identical_ingest` stores one file under two trajectory ids. The Python resume reads `coords_array`, which copies `atom.x/y/z`. The column copy on a parsed frame is `xyz` (`positions.f64_slice()` when `inner` is set). `to_ase` walks atoms and does not call `coords_array`. A fresh-frame witness can pass while an edited frame diverges. Plot writers grow a corpus client, and rgmin's ASE adapter starts loading a `.con` where `Optimizer.read` raises `NotImplementedError` today.

B is second because the process still starts and the resume file is still the file. C is third because the binary's link line changes first.

The 0.14 gap under 0.86 is A's own document. Two sections describe APIs the pinned trees do not have, and A never names `process_catalog.py`. Those are repairs, listed below. They are not a reason to take B's dynamics resume, B's reciprocal, or C's link line.

## The eight errors, as checked

1. **Holds.** eOn's pixi rev `4d7881a` is the ops pin. At that commit the package is `src/readcon_ops/match.py` and `wulff.py`. `__all__` is `identical`, `internal_motion`, `rotate`, `rotational_match`, `spacegroup`, `wulff_vertices`. The module docstring says it does not read a file. `pyproject.toml` depends on numpy, spglib, and minimage. A frame is any object with `r`, `box`, `names`, `copy`, and `__len__`. There is no `frames.py`, `_from_conframe`, `as_frame`, `_is_protocol`, `_is_conframe`, or `lengths_angles_to_cell`. `eon/structure.py` `Structure` already has `r`, `box`, and `names`. `eon/atoms.py` passes that object to `spacegroup` and `rotational_match`. A's ops section describes an API that is not in the pin.

2. **Holds.** `sinp::readConCorpus` calls `rkrdb_get_frame_text`, closes the database, parses with seams' `read_con_string_iterator`, then `cloudFromHandle` on that local handle and `free_rkr_frame`. The tree has no `rkrdb_get_frame` call. The `meson.build` comment is the constraint: the db crate vendors its own core, and seams does not free that handle with this build's `libreadcon_core`. The live bug is real. `cloudFromHandle` keeps the SoA only when `xyz[1] == atom.y` and `xyz[2] == atom.z`, and otherwise copies `atom.x/y/z`.

3. **Holds in substance.** `rkrdb_extend_trajectory_frame` and `rkrdb_extend_trajectory` are in `include/readcon-db.h` on tag `v0.1.8` (`0001a2c`, which pins `readcon-core = "=0.16.1"` and has no `frame_codec.rs`) and on `0725c94`. Rust `ConCorpus::extend_trajectory_frames` is on main. `extend_trajectory_str` / `rkrdb_extend_trajectory_str` are absent. Python `ConCorpus.extend_trajectory` calls `extend_trajectory_path_units`. Python `append_trajectory_frames` imports the installed `readcon` wheel and calls `write_con_string`. That part of A is right. The headline is slightly wide: A does not name the one-frame symbol as the thing 0.1.9 might grow. A says `rkrdb_extend_trajectory` might be missing, and that a batch-frame dlsym might be new. Both C entry points are already in the 0.1.8 header. The string extend C asks for is the symbol that is actually missing.

4. **Holds.** `include/cpmdc_restart.h` defines `CPMDC_RESTART_ANGSTROM_PER_BOHR` as `0.529177210859`. The comment says this matches OpenCPMD `cnst%fbohr`, which is `1/0.529177210859`. `print_triples` multiplies by the macro. `patch-positions` divides by the macro. B's `export-con` step converts Bohr to angstrom with `1/0.529177210859`. `CPMDC_BOHR_TO_ANGSTROM` in `src/cpmdc_params.h` is `0.529177210903`, a different number. A and C name the restart macro and multiply by it.

5. **Holds.** The client writer is `ConFrameWriter(path, compression, precision)` at 17 and 6. `savecon` omits precision. chemparseplot `write_con_frames` and the rgpycrumbs `write_con` calls omit precision and pass no canonical flag. The Python default is `canonical=false`. `FloatFormat::default` is `RoundTrip`. `create_writer_from_path_c` uses `ConFrameWriter::new`. On `96fd38f`, `self.canonical` is read only to skip the metadata cache. The production Python path that still passes a precision is `process_catalog.py`. A and C do not name that call. B names it and then turns canonical on.

6. **Holds.** `group_prepared` returns when `prepared.len() < 2`. `pack_aligned` writes `0xFD 0x03` only for a run with more than one frame, and only when the group is shorter than the per-frame values. `rkrdb_extend_trajectory_frame` calls `extend_trajectory_frames` with `slice::from_ref` of one frame. A one-frame extend cannot fill a group. A full-file `append_trajectory_str` or `rkrdb_extend_trajectory` of many frames in one call can. eOn's `matter2con(..., append=true)` hands the writer one frame.

7. **Holds.** `coords_array`, `velocities_array`, and `forces_array` copy `Atom` fields. `xyz`, `vel`, and `frc` copy `f64_slice()` when `inner` is set. `disp` and `spread` walk atoms. `ase_from_pyconframe` copies `atom.x/y/z` and does not call `coords_array`. `atom_ids_array`'s docstring says atomic numbers; the values are `atom_id`. C leaves `coords_array` in the contract and offers a later library change if a witness fails.

8. **Holds.** `append_trajectory_str` calls `commit_prepared` with `replace_meta = false`. That returns `TrajExists` when the id is already in `traj_meta`, with no byte compare. Identical-text success would be new code in front of that call. eOn's mirror ignores the status today, so a second insert of the same id fails quietly.

## What the final plan must adopt from B and C

From B:

- `eon/process_catalog.py` stops passing `17`. The saddle text is `write_con_string([frame])` with precision omitted, the same RoundTrip spelling as `savecon` after the 0.17.1 pin. Canonical stays at the writer default. B's `canonical=True` does not come with this line.
- `seed_dimers` writes `displacement.con` with the calculator cleared before `from_ase`, and the reloaded file has no forces section. `pos.con` stays the parsed peak frame. `direction.dat` stays `%18.12f`. `restoreFileForces` would trust peak forces on the moved geometry and skip the potential. A's `frame_with_positions` is the edit that keeps `dx` / `fx` / `sx` when a splitter only translates. It is the wrong helper for this seed.
- Dynamics stay on the current writer through the spelling cutover. An old `dynamics.con` remains a geometry history. A later campaign may write velocities and resume the last frame. That campaign is its own change, after `ApproveConFileIO` has moved once, old 0.16 fixtures still load, and one existing short minimization still meets the energy tolerance it already uses.
- The cpmdc import path calls `cpmdc_restart_set_cell` together with `cpmdc_restart_set_coordinates` and `cpmdc_restart_set_velocities`. A geometry step that updates the cell in the CON and leaves the binary cell records alone has two cells. The coefficient records stay byte-identical to the input. The conversion multiplies and divides by `CPMDC_RESTART_ANGSTROM_PER_BOHR`. The test states that the original Bohr bits do not survive the trip. `CPMDC_BOHR_TO_ANGSTROM` stays in the params header and is not this bridge.
- rgmin gains no readcon dependency. The host writes the geometry. `python/rgmin/ase.py` keeps raising on `restart=`. `test_todict_and_restart_refusal` stays the proof. `BandSession::restart` and rgmin's conjugacy `Restart` stay in-memory wipes.
- Downstream jobs download one golden byte string produced by `ConFrameWriter::new` on 0.17.1. They `cmp` those bytes. A writer built with precision 17 is asserted different, once, in readcon-core, on a value RoundTrip preserves and 17 digits do not.

From C:

- The uncompressed-append contract stays in the writer cutover, in the words C uses and in the code `matter2con` already runs. A tail this process did not write is parsed first. Parse failure returns `AppendError` and writes nothing. Gzip and zstd stay whole-file rewrites. A's scratch file is how that contract survives without a new buffer API.
- readcon-db 0.1.9 adds `extend_trajectory_str` / `rkrdb_extend_trajectory_str`, the text append that is absent today. Python `extend_trajectory` is the path binding, and pointing it at a growing movie duplicates frames. The eOn mirror may call that string entry with the buffered batch, or it may write the same batch to a scratch and call the existing `rkrdb_extend_trajectory`. It does not call `rkrdb_extend_trajectory_frame` once per step, and it does not wait on a new xfer repository. `rkrdb_append_trajectory_str`'s signature stays, because eOn `dlsym`s it.
- The bit witness is C's three equalities with the Python side on `xyz`, `vel`, and `frc`. The UTF-8 from `ConFrameWriter::new`, from `write_con_string` with precision omitted, and from `get_frame_text` after a group decode are the same bytes. The xxh3-128 of that UTF-8 is the stored hash. The f64 bits from `rkr_frame_xyz_f64` match the Python column getter. `get_positions` and `rkrdb_get_positions` are not the restart read. Cooked SoA stays off this path.
- Seams, last, keeps `rkrdb_get_frame_text`, closes the database, and parses with its own `read_con_string_iterator`. The `xyz[1] == atom.y` heuristic is deleted in that wrap bump, and the coordinate check is `rkr_frame_xyz_f64` of the frame seams parsed. Both wraps move in one commit, after the golden exists, so a build cannot see a 0.17.1 core beside a 0.16.1 db.

## What A must drop before it is the plan

- The readcon-ops pin stays at `4d7881a`. That package already compares a `Structure`. No `frames.py` work belongs in this cutover.
- Seams does not switch `readConCorpus` to `rkrdb_get_positions`. There is no foreign `rkrdb_get_frame` handle to stop freeing. The current decode already parses text with seams' core.
- `rkrdb_extend_trajectory` is not a symbol 0.1.9 might grow. It has been in the header since `v0.1.8`. The mirror uses it, or the new string extend, on a batch. A missing db symbol still soft-skips.
