# perf25 reader exchange

Every arm is one fresh process on core 0. One warmup, then six repeats, warm and then cold. The clock is the read named below. The coordinate check and the frame and atom count check run after the clock. A sample whose frame count is not the count in this table, or whose atom count is not 32, is an error and the run stops.

`eon_all` is compared with `readcon_eon_api`. `eon_first` is compared with `readcon_eon_api_first`. Each pair runs the same `eon_allframes` binary. `first` reads one frame with `read_first_frame` and calls `con2matter` once. `all` reads every frame with `read_all_frames` and calls `con2matter` on each frame. That is eOn's ConFileIO path. `Matter.con2matter(path)` also calls `mirror_con_corpus`, which reads the whole file into a corpus, so that call is not one of these arms.

`readcon_db` is readcon-db 0.2.1 at `564ea6e51065c40a1eb3b6b25921465d2f326523` (`fix/ingest-species-count`). The clock is `ConCorpus.get_positions_all`, which copies the cooked coordinate blob into one float64 array of shape `(frames, atoms, 3)`. `append_trajectory_str` writes that blob and runs before `READY`, outside the clock.

| arm | frames | materialized | returned |
| --- | --- | --- | --- |
| readcon_tip | all | positions only, `read_positions` | `(frames, 32, 3)` |
| readcon_base | all | full frames via `read_con`, then `.xyz` | positions |
| readcon_v0173 | all | full frames via `read_con`, then `.xyz` | positions |
| readcon_first | 1 | one frame via `read_first_frame`, then `.xyz` | positions |
| readcon_db | all | positions only, `get_positions_all` | `(frames, 32, 3)` |
| ase_eon | all | ASE atoms, then positions | positions |
| eon_first | 1 | `read_first_frame` plus one `con2matter` | Matter positions |
| readcon_eon_api_first | 1 | the same call as `eon_first` | Matter positions |
| eon_all | all | `read_all_frames` plus `con2matter` on every frame | Matter positions |
| readcon_eon_api | all | the same call as `eon_all` | Matter positions |
| eon_py | all | `eon.fileio.loadcons`, one Structure per frame, then `.r` | positions |
| conbin | all | positions; velocities are read and discarded | positions |
| numpy | all | parsed xyz blocks, coordinates only | positions |
| chemfiles | all | one chemfiles frame, then positions | positions |
| ovito | all | one pipeline frame, then positions | positions |
| ase_extxyz | all | ASE atoms, then positions | positions |
| pymatgen | all | one molecule, then `cart_coords` | positions |
| h5py | all | the position dataset | positions |
| mdanalysis | all | copied universe positions, one frame at a time | positions |
