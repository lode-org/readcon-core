# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

## Unreleased (611aa4a..815585c)
#### Maintenance
- bump to v0.14.0 - (cd7522e) - *HaoZeke*
#### Benchmarks
- chemfiles Cachegrind scenarios, measured-only Pareto, refresh I-refs - (ad70e47) - *HaoZeke*
#### Features
- (**bindings**) frame section buffers and multi-frame ergonomics - (09c4e8a) - *HaoZeke*
- (**ffi**) complete index_proj wiring across languages - (d1141d4) - *HaoZeke*
- (**ffi**) expose index_proj through C, C++, Python, Fortran - (1fb91b0) - *HaoZeke*
- (**ffi**) DLPack export accepts full DLDataType/DLDevice space - (f3212a0) - *HaoZeke*
- (**ffi**) DLPack export options use DLDataType and DLDevice layout - (f67a9da) - *HaoZeke*
- (**ffi**) RKRDlpackExportOptions for float32/64 and device tags - (2527756) - *HaoZeke*
- (**ffi**) assert DLPack shape/dtype; drop host-f64 consumer requirement - (620015d) - *HaoZeke*
- (**ffi**) frame velocities/forces/energies DLPack (uu0a) - (30b2eee) - *HaoZeke*
- (**ffi**) finalize open readcon vissues — iterators, sections, docs - (479aecc) - *HaoZeke*
- (**ffi**) feature matrix CI, lean stubs, Arc DLPack borrowed aliases - (e821cf4) - *HaoZeke*
- (**ffi**) full metatensor C API + DLPack Fortran parity - (4c4dbe7) - *HaoZeke*
- (**ffi**) metatensor TensorBlock C ABI + full Fortran DLPack layout - (de6213b) - *HaoZeke*
- (**ffi,fortran**) chemfiles read C API, DLPack delete, buffer/dlpack Fortran - (ecbb57c) - *HaoZeke*
- (**fortran**) full C-ABI surface — iter/builder/writer/select + fpm CI - (a1e2c86) - *HaoZeke*
- (**fortran**) fpm ReadCon package, frame_t metadata API, multi-lang panels - (5ec88c2) - *HaoZeke*
- (**fortran**) ISO_C_BINDING module; document closed trackers - (ac56a3a) - *HaoZeke*
- (**index_proj**) campaign screening projection and ingest contracts - (234cad3) - *HaoZeke*
- (**iter**) next_with_raw_span for zero-copy corpus ingest - (1ec7650) - *HaoZeke*
- (**python**) multi-frame chemfiles selection for trajectory H positions - (9c9ef96) - *HaoZeke*
- (**python**) export read_all_frames alias for batch ergonomics - (9fe7d9d) - *HaoZeke*
- (**selection**) multi-frame chemfiles select with per-frame H positions - (91002a6) - *HaoZeke*
- (**selection**) multi-frame chemfiles select with per-frame H positions - (6abeed3) - *HaoZeke*
- host all dlpk-owned DLPack element types in SoA storage - (fe5ea6c) - *HaoZeke*
- allocate SoA in any supported storage dtype on build - (d9db3d0) - *HaoZeke*
- v3 storage_dtypes + FloatArray SoA; standards DLPack/units prose - (6169854) - *HaoZeke*
- CON v3 mandates units; metatensor-style as_dlpack/from_dlpack - (e72e60f) - *HaoZeke*
#### Bug Fixes
- (**bindings**) complete ergonomics gaps from skeptic review - (6319843) - *HaoZeke*
- (**c6ox**) always declare optional metatensor and zstd C APIs - (16dd0a3) - *HaoZeke*
- (**ci**) drop Fortran chemfiles runtime; exclude lagging Pages URLs - (660a16d) - *HaoZeke*
- (**ci**) repair pixi.lock conflicts; harden Fortran chemfiles FPE - (d3318cc) - *HaoZeke*
- (**ci**) sync cbindgen headers; Fortran tests via script and ROOT env - (6ca0bdf) - *HaoZeke*
- (**ci,docs**) refresh pixi.lock, shibuya logos, reliable Sphinx build - (483bfe9) - *HaoZeke*
- (**docs**) do not treat Sphinx warnings as errors in CI docbld - (695a0d0) - *HaoZeke*
- (**docs**) remove sphinxcontrib-rust from pixi docs env - (b56a9a1) - *HaoZeke*
- (**docs**) drop sphinxcontrib_rust in Sphinx CI path - (9d5dfad) - *HaoZeke*
- (**docs**) never run sphinx-rustdocgen in CI Sphinx builds - (41a52fd) - *HaoZeke*
- (**ffi**) bool DLPack arm error type mismatch - (5ca5143) - *HaoZeke*
- (**ffi**) ArcArray f32 cast for DLPack float_bits=32 - (a2cc6ec) - *HaoZeke*
- (**ffi**) drop fake *_dlpack_borrowed; document dlpk ArcArray share - (3ad5613) - *HaoZeke*
- (**ffi**) FEATURE_DISABLED (-11); Fortran gzip/zstd writers - (bf232ec) - *HaoZeke*
- (**ffi**) gate metatensor C ABI; assert block shape and label counts - (adf52a3) - *HaoZeke*
- (**ffi**) metatensor always-link stubs; complete Fortran DLPack+mts surface - (5a2e205) - *HaoZeke*
- (**ffi**) always export metatensor symbols (stubs without feature) for Fortran link - (04e72e7) - *HaoZeke*
- (**fortran**) no lean-link dependency on metatensor C symbols; cpp only in tests - (6fb9969) - *HaoZeke*
- (**fortran**) PUBLIC only in specification part; fpm tests pass - (2d7f930) - *HaoZeke*
- (**metatensor**) unique sample labels; catch_unwind on C exports - (af95200) - *HaoZeke*
- (**parse**) sync SoA sections after declared section parse - (2852498) - *HaoZeke*
- (**parser**) reject unsupported version before v3 units check - (6a587ea) - *HaoZeke*
- defer float16 as_dlpack on half/dlpk version skew - (26b174e) - *HaoZeke*
- StorageDtypes path in con_frame_from_atom_data - (a07c5b0) - *HaoZeke*
- skeptic gaps — DLPack value RT, v3 units parse/write, typed units - (50d0009) - *HaoZeke*
#### Performance
- (**parse**) skip position SoA rewrite in section sync - (db86a1a) - *HaoZeke*
- (**parser**) SoA-primary coords and stack line floats on hot path - (a17fd1e) - *HaoZeke*
- skip default storage_dtypes metadata on hot build path - (a0e3c86) - *HaoZeke*
- avoid redundant SoA sync and default storage_dtypes metadata - (4187934) - *HaoZeke*
#### Documentation
- (**a11y**) darken logo-light CORE subtitle for WCAG AA on white - (815585c) - *HaoZeke*
- (**architecture**) point at metatensor gate and env file - (c37d8c9) - *HaoZeke*
- (**brand**) original CON-ingress logo and clearer site map - (9129fde) - *HaoZeke*
- (**chemfiles**) Org-mode is sole executable notebook source - (611aa4a) - *HaoZeke*
- (**css**) accessible token colours on dark code fences - (1cf08ca) - *HaoZeke*
- (**css**) force inline spans in code fences (fix whitespace) - (8694c5d) - *HaoZeke*
- (**css**) force inline data-line spans for correct fence whitespace - (3132cf0) - *HaoZeke*
- (**css**) restore normal code whitespace (no block on data-line) - (8300cce) - *HaoZeke*
- (**css**) keep code [data-line] as block (R/Python fences) - (568b367) - *HaoZeke*
- (**css**) single frame on code blocks (no nested border lines) - (f965edc) - *HaoZeke*
- (**readme**) link readcon-db as ecosystem corpus layer - (189c84d) - *HaoZeke*
- (**site**) ecosystem nav, figures, shibuya features like rgpot - (36c3fe2) - *HaoZeke*
- (**site**) fix Sphinx links, Atkinson Hyperlegible, clearer home - (b306ef4) - *HaoZeke*
- (**sphinx**) ecosystem nav and intersphinx to readcon-db - (627846b) - *HaoZeke*
- (**sphinx**) theme-align Org chemfiles pages with shibuya site - (a9d53cd) - *HaoZeke*
- override theme pre{display:grid} for code fences - (c6f8f87) - *HaoZeke*
- setProperty important for inline code token spans - (cf00fb8) - *HaoZeke*
- force inline code token spans in page JS - (6958d72) - *HaoZeke*
- fix code fence whitespace (unwrap data-line + inline tokens) - (e60c4a4) - *HaoZeke*
- unwrap Sphinx data-line spans for correct code whitespace - (391f026) - *HaoZeke*
- center CON selection; chemfiles is optional ingress only - (9d859b0) - *HaoZeke*
- align chemfiles selection prose with in-repo FAQ voice - (27f7edc) - *HaoZeke*
- drop leftover 'contract' wording in selection notes - (355c735) - *HaoZeke*
- write selection limits in a human, NumPy-like voice - (27ca4c7) - *HaoZeke*
- tighten selection-scope prose (vale E-Prime soft) - (22511b6) - *HaoZeke*
- rewrite chemfiles selection scope (no vague gap list) - (66207ca) - *HaoZeke*
- map lean/fat metatensor and option A moving parts - (10fff21) - *HaoZeke*
- metatensor C/Fortran ABI and full DLPack parity in bindings - (b60d924) - *HaoZeke*
- export issue-status RST for Sphinx - (a9cc066) - *HaoZeke*
- larger code type, stronger a11y and contrast - (401fbbe) - *HaoZeke*
- add fix_doc_links.py required by docbld - (d0357c4) - *HaoZeke*
- fix broken in-page .rst links; keep Pages deploy unblocked - (4ab3685) - *HaoZeke*
- remove leftover fake-viz claims from tutorial and nav - (7f5d285) - *HaoZeke*
- delete fabricated figure assets entirely - (c3505c5) - *HaoZeke*
- conversion-first getting started, drop fake molecule art - (d6c8cbc) - *HaoZeke*
- lychee link gate, track RST, WCAG-oriented site chrome - (f990148) - *HaoZeke*
- WBO-style figures, full Shibuya sidebars, ecosystem nav - (bdc7e30) - *HaoZeke*
#### Tests
- (**core**) skeptic pass — chemfiles skip gate, projection equality, C sample - (fc8a967) - *HaoZeke*
- (**core**) strengthen SoA/sync contracts and stack line parse checks - (626401f) - *HaoZeke*
- (**ffi**) assert positions block shape via mts_array without mts_labels_count - (e340f0e) - *HaoZeke*
- (**ffi,python**) drive full projection contract and canonical writes - (693d387) - *HaoZeke*
- (**python**) restore single-frame chemfiles selection (atom context) - (4fddf86) - *HaoZeke*
- (**python**) restore single-frame chemfiles selection regression suite - (868d34c) - *HaoZeke*
#### CI
- (**bench**) Cachegrind I-refs on main for always-fresh docs numbers - (a5af9d4) - *HaoZeke*
#### Refactoring
- (**ffi**) option A — metatensor-sys on the C boundary - (0abc86d) - *HaoZeke*
- ConFrame SoA ArcArray is primary numeric store (DLPack-shaped) - (de4b276) - *HaoZeke*
#### Chores
- (**bench**) refresh Cachegrind I-refs for docs - (386d1d1) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (6835f7e) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (4ce3288) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (851ca9b) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (538e1be) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (0af969e) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (22301d7) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (f266768) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (486831f) - github-actions[bot]
- (**capi**) regenerate headers after index_proj FFI - (e8e9112) - *HaoZeke*

- - -

## v0.13.1 - 2026-06-26
#### Features
- (**docs**) papermill-executable chemfiles ingress notebook - (6cc9895) - *HaoZeke*
- (**python**) idiomatic chemfiles ingress and frame.select APIs - (0a12c24) - *HaoZeke*
#### Documentation
- (**chemfiles**) Diátaxis tutorial, how-to, explanation, and reference - (486fd8f) - *HaoZeke*
#### Chores
- (**release**) prepare v0.13.1 - (94b9f53) - *HaoZeke*

- - -

## v0.13.0 - 2026-06-26
#### Maintenance
- (**release**) sync meson and sphinx version to 0.13.0 - (da94d13) - *HaoZeke*
#### Merges
- land v0.11–v0.12 builder mutation, SoA, DLPack, ArcArray - (eb2101f) - *HaoZeke*
#### Features
- (**bindings**) chemfiles selection parity across C/Python/Julia surfaces - (ecfa758) - *HaoZeke*
- (**chemfiles**) Python chemfiles extra and always-on Rust API stubs - (376b407) - *HaoZeke*
- (**chemfiles**) selection grammar via C/C++/Python when enabled - (af76eea) - *HaoZeke*
- (**cpp**) compressed ConFrameWriter - (ef1c924) - *HaoZeke*
- (**ffi**) C ABI for gzip/zstd compressed writers - (c5ccbaf) - *HaoZeke*
- (**topology**) optional frame bonds + chemfiles projection (v0.13.0) - (84c7ab3) - *HaoZeke*
- optional chemfiles import into ConFrame with metadata - (c7d68a5) - *HaoZeke*
#### Bug Fixes
- (**capi**) always export chemfiles selection FFI; skip Win chemfiles wheels - (a17339e) - *HaoZeke*
- (**chemfiles**) preserve display name/type sidecars for selection parity - (fae51fe) - *HaoZeke*
- (**cpp**) use RKR_STATUS_SUCCESS in compressed writer wrapper - (aaa0932) - *HaoZeke*
- (**docs**) bind antics tracker to site token - (5b54192) - *HaoZeke*
#### Documentation
- (**changelog**) complete v0.11–v0.13 narrative for the v0.13.0 cut - (d696f08) - *HaoZeke*
- (**contributing**) release-PR, crates.io token, and tag CI map - (1aa4c3e) - *HaoZeke*
- (**faq,bindings**) point chemfiles FAQ and matrix at tutorials - (8f8d275) - *HaoZeke*
- (**tutorials**) chemfiles converter and bond-angle selection guides - (492fb3a) - *HaoZeke*
#### Tests
- (**chemfiles**) port selection.cpp topology regression + fix bond index remap - (59efd43) - *HaoZeke*
- cover compressed writer round-trip through the C ABI - (dae4743) - *HaoZeke*
#### Build system
- (**cbindgen**) sync header and define chemfiles feature guard - (0e92d3a) - *HaoZeke*
- (**cbindgen**) regenerate C header for compressed writers - (4182f9b) - *HaoZeke*
- (**chemfiles**) set CMAKE_POLICY_VERSION_MINIMUM for chemfiles-sys - (6d1b173) - *HaoZeke*
#### CI
- (**crates**) resolve publish version from Cargo.toml - (6595554) - *HaoZeke*
- (**release**) cargo-dist PR plan, crates.io secret workflow, checklist script - (b8a80c8) - *HaoZeke*
- (**wheels**) run pyproject variant select under bash on Windows - (d5212e5) - *HaoZeke*
- (**wheels**) use include-only matrix for dual distributions - (f1de0d8) - *HaoZeke*
- (**wheels**) dual matrix for readcon and readcon-chemfiles on PyPI - (2d294b0) - *HaoZeke*
- (**wheels**) retry maturin on transient crates.io failures - (2f843e8) - *HaoZeke*
#### Chores
- (**release**) prepare v0.13.0 - (9d34e66) - *HaoZeke*

- - -

## v0.12.0 - 2026-05-11
#### Work in progress
- (**builder**) arc-push helpers + drop positions_dlpack_mut for v0.12 - (7548148) - *HaoZeke*
- (**builder**) switch storage from Array2/Array1 to ArcArray2/ArcArray1 - (cd45814) - *HaoZeke*
#### Features
- (**ffi+cpp**) rkr_frame_builder_clone + C++ ConFrameBuilder::clone() - (00e6e08) - *HaoZeke*
#### Tests
- (**builder**) clone_shares_storage_until_cow demonstrates ArcArray semantics - (512872c) - *HaoZeke*
#### Build system
- (**cbindgen**) regenerate readcon-core.h with rkr_frame_builder_clone - (6c2a676) - *HaoZeke*

- - -

## v0.11.4 - 2026-05-10
#### Features
- (**builder**) add set_atom_id(i, atom_id) for post-add atom-id mutation - (8fed5a5) - *HaoZeke*
#### Documentation
- (**bib**) cite Bigi et al. (metatensor JCP 2026) via sphinxcontrib-bibtex - (a3a9d6c) - *HaoZeke*
#### Build system
- (**cbindgen**) regenerate readcon-core.h with set_atom_id - (876eaaa) - *HaoZeke*

- - -

## v0.11.3 - 2026-05-10
#### Features
- (**helpers**) map D and T to Z=1; clarify informational/non-binding semantics - (a3e3c3a) - *HaoZeke*

- - -

## v0.11.2 - 2026-05-10
#### Features
- (**ffi+cpp**) raw-pointer data accessors for in-process hot path - (67d364d) - *HaoZeke*
#### Build system
- (**cbindgen**) regenerate readcon-core.h with raw-pointer data accessors - (b5f9de1) - *HaoZeke*

- - -

## v0.11.1 - 2026-05-10
#### Bug Fixes
- (**cbindgen**) forward-declare RKRDLManagedTensorVersioned in C header - (99967fc) - *HaoZeke*
#### Documentation
- (**changelog**) add v0.11.0 entry - (f7f7941) - *HaoZeke*

- - -

## v0.11.0 - 2026-05-10
#### Dependencies
- (**builder**) hard-dep dlpk + ndarray for v0.11 SoA storage - (bb3e7bd) - *HaoZeke*
#### Features
- (**array**) introduce src/array.rs with Array trait + ndarray backing - (23a02bd) - *HaoZeke*
- (**builder**) in-place mutation API for ConFrameBuilder - (4dcdd76) - *HaoZeke*
- (**cpp**) C++ wrapper for v0.11.0 in-place builder mutation - (e093b7e) - *HaoZeke*
- (**ffi**) tier-3 DLPack export functions for builder fields - (40a4de6) - *HaoZeke*
- (**ffi**) C ABI for v0.11.0 in-place builder mutation - (82ce7a6) - *HaoZeke*
#### Documentation
- (**spec**) codify v0.11 ndarray storage + DLPack contract in §17 - (58048e1) - *HaoZeke*
- (**spec**) add builder mutation surface (informative) to spec.org - (b92b6a6) - *HaoZeke*
#### Tests
- (**dlpack**) pin cross-language export contract for builder fields - (64ac443) - *HaoZeke*
- (**ffi**) smoke tests for DLPack tier-3 export - (f7c187f) - *HaoZeke*
#### Refactoring
- (**builder**) SoA storage via ndarray::Array2/Array1 with DLPack - (1fe6dc6) - *HaoZeke*
#### Chores
- (**version**) bump readcon-core to 0.11.0 - (e2fb998) - *HaoZeke*

- - -

## v0.10.0 - 2026-05-10
#### Generated
- regenerate CHANGELOG.md from cog - (303be90) - *HaoZeke*
- regenerate CHANGELOG.md from cog - (b3caca7) - *HaoZeke*
#### Maintenance
- bump to v0.10.0 - (35ee566) - *HaoZeke*
#### Documentation
- (**analytics**) swap site-foot Umami credit for antics - (4ac3f97) - *HaoZeke*
- (**architecture**) document cargo-c install contract - (9a64ac4) - *HaoZeke*
- (**contributing**) document profile-guided optimisation workflow - (9822fda) - *HaoZeke*
- (**export**) publish docs/orgmode/img/ assets to docs/source/img/ - (0381f18) - *HaoZeke*
- (**faq,bindings**) cover v0.10.0 surface (energies, zstd, atom_id index, NumPy views, metatensor) - (17ce6fc) - *HaoZeke*
- (**spec**) expand energies section with RFC 2119 normative language - (1c4020f) - *HaoZeke*
- (**spec**) document the energies section format - (effb179) - *HaoZeke*
#### Benchmarks
- add trajectory-style write fixture with heavy shared metadata - (71cbbb5) - *HaoZeke*
- write 100-frame trajectory through ConFrameWriter - (4b960b9) - *HaoZeke*
#### Features
- (**bindings**) plumb per-atom energies through every binding - (596862c) - *HaoZeke*
- (**cpp**) morton_sort + atom_index_by_id mirroring the FFI - (a198e57) - *HaoZeke*
- (**helpers**) expose symbol/atomic-number lookup via FFI - (f214fd6) - *HaoZeke*
- (**julia**) morton_sort, atom_index_by_id, build_atom_id_index - (ade1551) - *HaoZeke*
- (**metatensor**) export per-atom positions / velocities / forces / energies as TensorBlocks - (737dc0d) - *HaoZeke*
- (**perf**) Morton spatial sort + O(1) atom_id reverse index - (ed8079d) - *HaoZeke*
- (**python**) NumPy array views for coords / velocities / forces / energies / atom_ids - (55940cc) - *HaoZeke*
- (**python**) add morton_sort, atom_index_by_id, build_atom_id_index - (b3d0a8a) - *HaoZeke*
- (**spec**) add energies section for per-atom energy contributions - (32afa53) - *HaoZeke*
- (**zstd**) add transparent zstd compression behind feature flag - (51dd170) - *HaoZeke*
#### Bug Fixes
- (**metatensor**) use Labels::count for row count in test (size = ndim) - (1582e08) - *HaoZeke*
- (**metatensor**) use as_ndarray_lock + RwLock read in shape assertion - (0ec5616) - *HaoZeke*
- (**metatensor**) pass ArrayD (dynamic dim) to TensorBlock::new - (eec2a8c) - *HaoZeke*
- (**parser**) keep string-based identity parsing for strict v2 semantics - (9572c96) - *HaoZeke*
- (**python**) align ndarray dep with numpy 0.28's transitive ndarray 0.17 - (7024d26) - *HaoZeke*
- (**release**) set User-Agent on crates.io skip check; skip existing wheels on PyPI - (342b0d1) - *HaoZeke*
- (**wheels**) skip-existing on PyPI publish so re-runs fill missing wheels - (29480aa) - *HaoZeke*
#### Performance
- (**iterators**) add memchr-backed forward_fast skip path - (c41abf5) - *HaoZeke*
- (**parallel**) boundary scan via forward_fast (O(N), not O(N^2)) - (48134ee) - *HaoZeke*
- (**parser**) arena-back per-atom parse buffers via bumpalo - (a94aa9b) - *HaoZeke*
- (**parser**) lift identity columns from already-parsed floats; fix energies validate - (dfb5bcf) - *HaoZeke*
- (**profile**) tighten release and dist build profiles - (9538ea1) - *HaoZeke*
- (**writer**) cache the serialised JSON metadata line across frames - (5663a6c) - *HaoZeke*
#### Revert
- (**parser**) drop bumpalo arena experiment - (ba74d8e) - *HaoZeke*
- (**perf**) drop Morton spatial sort from v0.10.0 surface - (2ee6daa) - *HaoZeke*
#### Tests
- (**julia**) update CAtom/CFrame field order tests for energy fields - (6bdab08) - *HaoZeke*
- (**metatensor**) smoke test the four block builders - (14f861a) - *HaoZeke*
- (**python**) cover NumPy array views + atom_id index - (6070251) - *HaoZeke*
- (**types**) cover morton_encode locality, sort+type grouping, atom_id index - (971c04f) - *HaoZeke*
#### Build system
- (**pixi**) refresh lockfile for numpy>=1.22 in python feature env - (230ef4c) - *HaoZeke*
- (**pixi**) add numpy to python feature env so array tests run - (2d0092d) - *HaoZeke*
- (**release**) add publish-crates-io job to release workflow - (039d1a5) - *HaoZeke*

- - -

## v0.9.0 - 2026-05-10
#### Maintenance
- bump to v0.9.0 - (b1cc006) - *HaoZeke*
#### Buildsystem
- (**capi**) trim cargo-c metadata to defaults, fold drift check into script - (71c1380) - *HaoZeke*
- (**capi**) ship pre-generated header, drop cbindgen build dep - (c4379bd) - *HaoZeke*
#### Features
- (**builder**) validate metadata schema in set_metadata_json - (ed1b470) - *HaoZeke*
- (**cpp**) mark legacy fields deprecated, document standard, polish iterator - (df5f6b4) - *HaoZeke*
- (**cpp**) improve C++ wrapper ergonomics - (d81eefd) - *HaoZeke*
- (**ffi**) preserve builder masks and forces - (c849c90) - *HaoZeke*
- (**ffi**) use structured RKRStatus enum for error handling - (184c0ba) - *HaoZeke*
- (**julia**) add metadata and writer support - (7b936d1) - *HaoZeke*
- (**parser**) enforce strict v2 validation - (f55e4e4) - *HaoZeke*
- (**parser**) validate section identity on request - (758a30f) - *HaoZeke*
- (**python**) expose live frame containers - (cb22ebf) - *HaoZeke*
- (**repo**) add CITATION.cff - (d76985e) - *HaoZeke*
#### Bug Fixes
- (**capi**) restore pkg_config filename so install drops readcon-core.pc - (c98224b) - *HaoZeke*
- (**ffi**) harden status and Julia ABI bindings - (f110726) - *HaoZeke*
- (**python**) preserve [String; 2] prebox_header for Python ABI - (f11a565) - *HaoZeke*
- (**python**) convert metadata through native objects - (172a422) - *HaoZeke*
- (**python**) expose native metadata values - (4232740) - *HaoZeke*
- (**types**) exclude cached fields from FrameHeader equality - (f7ce57f) - *HaoZeke*
#### Performance
- (**parser**) drop intermediate String for Arc<str> symbol; fold validate extraction - (bde2fce) - *HaoZeke*
- (**parser**) cache sections_declared flag instead of re-parsing JSON - (cb1e4b9) - *HaoZeke*
- (**parser**) cache validate flag on FrameHeader - (aa68afa) - *HaoZeke*
- (**parser**) single-pass metadata extraction in parse_frame_header - (3520198) - *HaoZeke*
- (**parser**) drop unconditional is_finite from float parsers - (18a28ab) - *HaoZeke*
- (**parser**) swap sections vec via mem::take instead of clone - (1959da5) - *HaoZeke*
- (**python**) drop serde_json::Value roundtrip in metadata getters - (fdfe6ed) - *HaoZeke*
#### Documentation
- (**analytics**) replace dead Umami snippet with antics tracker - (35007b8) - *HaoZeke*
- (**analytics**) replace dead Umami snippet with antics tracker - (1bff978) - *HaoZeke*
- (**bindings**) add parity matrix; document Python and Julia typed metadata setters - (5fefc40) - *HaoZeke*
- (**bindings**) document ergonomic binding parity - (20620ce) - *HaoZeke*
- (**bindings**) refresh FFI and metadata references - (d94412d) - *HaoZeke*
- (**ffi**) document ownership, sentinels, threading, error signaling - (33d0a81) - *HaoZeke*
- (**ffi**) add safety sections and optimize symbol storage with Arc<str> - (db2a680) - *HaoZeke*
- (**readme**) expand to Diataxis structure - (86c4ca2) - *HaoZeke*
- (**readme**) remove quick-start trailing whitespace - (63a9a6e) - *HaoZeke*
- (**spec**) enumerate validation rules with ParseError variants - (cfabf9c) - *HaoZeke*
- (**types**) document each meta:: constant with JSON type and semantics - (52ff5ca) - *HaoZeke*
#### Tests
- (**lint**) satisfy strict clippy checks - (08acf7f) - *HaoZeke*
#### Refactoring
- (**builder**) unify ConFrameBuilder on &mut self -> &mut Self - (1df0561) - *HaoZeke*
- (**builder,ffi**) collapse add_atom fan-out - (afffbc5) - *HaoZeke*
- (**core**) drive-by ergonomic cleanups - (1082d72) - *HaoZeke*
- (**core**) replace Rc with Arc for thread-safety and fix clippy warnings - (f43728d) - *HaoZeke*
- (**python**) use [String; 2] for prebox/postbox header in PyConFrame - (0f73aca) - *HaoZeke*
- (**types**) wrap managed JSON line in PreboxHeader struct - (d04620b) - *HaoZeke*
- (**types**) collapse per-axis Option<f64> velocity/force fields - (3893985) - *HaoZeke*
- (**types**) centralize JSON metadata key constants - (ece4d94) - *HaoZeke*
- (**types**) derive PartialEq for AtomDatum and ConFrame - (c4f429b) - *HaoZeke*
#### Chores
- (**julia**) ignore local test manifest - (321cd28) - *HaoZeke*
#### Style
- (**lints**) scope clippy allows from crate-level to call sites - (334aaec) - *HaoZeke*
- (**parser**) satisfy strict validation lints - (36dbb89) - *HaoZeke*
- apply rustfmt - (76e4aa8) - *HaoZeke*

- - -

## v0.8.0 - 2026-04-20
#### Buildsystem
- (**capi**) add cargo-c metadata and compatibility feature - (f776281) - *HaoZeke*
#### Maintenance
- bump to v0.8.0 - (f5b14a8) - *HaoZeke*
#### Generated
- regenerate CHANGELOG.md from cog - (4520b3e) - *HaoZeke*
#### Features
- (**ffi**) add builder metadata setters and JSON escape hatch - (75a756e) - *HaoZeke*
- (**python**) add metadata helper parity across bindings - (3d6ca04) - *HaoZeke*
#### Bug Fixes
- (**parallel**) use Arc for shared atom symbols - (5224b02) - *HaoZeke*
#### Documentation
- (**readme**) regenerate from readme_src.org - (ec03eb9) - *HaoZeke*

- - -

## v0.7.3 - 2026-03-27
#### Generated
- regenerate CHANGELOG.md from cog - (0cc3353) - *HaoZeke*
#### Chores
- bump to v0.7.3 - (180a49d) - *HaoZeke*

- - -

## v0.7.2 - 2026-03-27
#### Features
- pbc + lattice_vectors metadata, changelog catch-up, v0.7.2 - (e2df964) - *HaoZeke*
- pbc and lattice_vectors metadata keys, bump to v0.7.1 - (c370728) - *HaoZeke*

- - -

## v0.7.1 - 2026-03-26
#### Bug Fixes
- use path.string().c_str() for Windows wchar_t compatibility - (ce8f6ba) - *HaoZeke*

- - -

## v0.7.0 - 2026-03-25
#### Benchmarks
- publication-quality plots, feature matrix, Pareto front - (a44e269) - *HaoZeke*
- scaling benchmarks with memory usage across file sizes - (851076a) - *HaoZeke*
- add C sscanf reader, real 4-way comparison - (861191e) - *HaoZeke*
- real cross-implementation numbers (readcon 8-9x faster than ASE) - (3e40cdd) - *HaoZeke*
#### Documentation
- rewrite spec.org as implementation-neutral format standard - (75f55b6) - *HaoZeke*
- evolution rationale, reference impls, benchmark script, spec bitmask table - (06c26d2) - *HaoZeke*
- spec update for forces/sections/compression, FAQ, benchmarks - (73e4edd) - *HaoZeke*
- add recommended metadata keys to CON spec - (389d16f) - *HaoZeke*
#### Maintenance
- rebuild .gitignore with gibo (Rust, C++, C, Python, CMake, macOS, Linux) - (e4458cb) - *HaoZeke*
#### Features
- per-direction constraint bitmask (column 4) - (c67a499) - *HaoZeke*
- test fixtures, integration tests, version bump to v0.7.0 - (e018c08) - *HaoZeke*
- transparent gzip compression for read and write - (41ef92a) - *HaoZeke*
- forces support with JSON-declared sections - (d24e1d5) - *HaoZeke*
- typed metadata helpers on FrameHeader - (33c74ec) - *HaoZeke*
#### Bug Fixes
- (**ci**) update C/C++ headers and RPC for bitmask + force fields - (c6f9444) - *HaoZeke*
- (**ci**) target bench binary in benchmark workflow - (7e5d910) - *HaoZeke*
- remove compiled benchmark binary from repo, add to gitignore - (634b8d7) - *HaoZeke*
- update Python tests for fixed: [bool; 3] API - (37f9dd5) - *HaoZeke*
- remove archived ASE/eOn Python (use installed packages instead) - (91b0f79) - *HaoZeke*
#### CI
- add doc preview commenter workflow for PRs - (7de693c) - *HaoZeke*
#### Chores
- (**docs**) orgmode fixes - (c41f3e9) - *HaoZeke*
- (**docs**) exclude auto-generated binary docs from sphinx build - (8469e90) - *HaoZeke*
- (**docs**) standardize atom_id terminology across all org files - (28d9917) - *HaoZeke*
- (**docs**) fix broken link - (875f4b1) - *HaoZeke*
- (**docs**) rework - (84addba) - *HaoZeke*
- (**org**) format - (cbfb637) - *HaoZeke*
- (**spec**) cleanup - (4787b8f) - *HaoZeke*
- (**title**) no  ~~ - (e699b01) - *HaoZeke*

- - -

## v0.6.0 - 2026-03-25
#### Features
- JSON metadata line on line 2 of CON header (spec v2) - (ac94cd1) - *HaoZeke*

- - -

## v0.5.2 - 2026-03-25
#### Features
- transfer velocities and masses in ASE conversion - (633adfa) - *HaoZeke*
#### Chores
- bump to v0.5.2 - (9fbae89) - *HaoZeke*

- - -

## v0.5.1 - 2026-03-25
#### Features
- transfer atom_id to/from ASE Atoms via tags and custom array - (75fc1ef) - *HaoZeke*
#### Bug Fixes
- do not overwrite ASE tags in to_ase(), use only atom_id array - (3f99f49) - *HaoZeke*

- - -

## v0.5.0 - 2026-03-22
#### Features
- (**spec**) clarify column 5 as original atom index, make optional - (b9df215) - *HaoZeke*
- expose spec version as compile-time and runtime constants - (be99967) - *HaoZeke*
#### Bug Fixes
- (**ci**) use explicit features for coverage, skip parallel - (18723c5) - *HaoZeke*
- (**rpc**) capnpc src_prefix, capnp-rpc 0.20 API compat - (9a2407f) - *HaoZeke*
- update TurtleTech turtle SVG (closed arm paths) - (2020bc3) - *HaoZeke*
#### Documentation
- (**spec**) rewrite as versioned normative spec (v1, v2) - (9c2caf2) - *HaoZeke*
- update orgmode docs for spec v2 and version query APIs - (81e61ab) - *HaoZeke*

- - -

## v0.4.4 - 2026-03-16
#### Documentation
- add v0.4.0-v0.4.3 changelog, update tutorials and bindings - (3eed202) - *HaoZeke*
#### Features
- (**docs**) add Umami analytics and TurtleTech footer - (9f5606b) - *HaoZeke*
#### Bug Fixes
- (**bld**) use link_args instead of link_with in declare_dependency - (261aa19) - *HaoZeke*
- (**bld**) do not install cargo custom_target - (a861711) - *HaoZeke*
- Windows support for meson build - (3b80468) - *HaoZeke*
#### Chores
- bump to v0.4.4 - (ec241bc) - *HaoZeke*

- - -

## v0.4.3 - 2026-02-24
#### Bug Fixes
- (**ci**) set PYO3_PYTHON for coverage with --all-features - (7ebbd3c) - *HaoZeke*
#### Performance
- use read_to_string for small files, add read_first_frame - (fc1b0d6) - *HaoZeke*
#### Chores
- bump to v0.4.3 - (d797dc3) - *HaoZeke*

- - -

## v0.4.2 - 2026-02-24
#### Tests
- add coverage for precision, constructors, mass roundtrip - (ebc3873) - *HaoZeke*
#### Features
- (**py**) expose per-atom mass in Python bindings, bump v0.4.2 - (0c08b7f) - *HaoZeke*
#### Bug Fixes
- (**ci**) add cargo bin to PATH for sphinx-rustdocgen - (e36eabb) - *HaoZeke*

- - -

## v0.4.1 - 2026-02-24
#### Bug Fixes
- (**docs**) toctree rendering, add sphinxcontrib-rust for Rust API docs - (1f5aa2b) - *HaoZeke*
#### CI
- add release workflow for native library artifacts - (dfdc873) - *HaoZeke*
#### Chores
- (**version**) v0.4.1 - (a37ef79) - *HaoZeke*

- - -

## v0.4.0 - 2026-02-24
#### Buildsystem
- modernize CI workflows - (5b93a7f) - *HaoZeke*
#### Features
- add Python constructors, precision, and ASE conversion - (32ed476) - *HaoZeke*
- add frame builder and mmap reader FFI - (c73a971) - *HaoZeke*
- add configurable writer precision - (b5b2752) - *HaoZeke*
- add Rust-native ConFrameBuilder - (406bee3) - *HaoZeke*
#### Bug Fixes
- (**ci**) use pixi for coverage workflow capnproto - (7edfff3) - *HaoZeke*
- (**ci**) regenerate pixi.lock - (e219ce2) - *HaoZeke*
- (**ci**) switch meson build to cargo custom_target - (bd0627d) - *HaoZeke*
- docs build with MELPA ox-rst, pixi pypi deps, setup-pixi v0.9.4 - (9988860) - *HaoZeke*
#### Chores
- (**version**) v0.4.0 - (16d9d01) - *HaoZeke*

- - -

## v0.3.2 - 2026-02-24
#### Buildsystem
- add benchmark regression CI, fix wheel builds, update README - (317258f) - *HaoZeke*
#### Chores
- (**version**) v0.3.2 - (bf38176) - *HaoZeke*

- - -

## v0.3.1 - 2026-02-24
#### Chores
- (**version**) v0.3.1 - (46d9b38) - *HaoZeke*

- - -

## v0.3.0 - 2026-02-24
#### Buildsystem
- add CMakeLists.txt and update meson.build for subproject use - (01738af) - *HaoZeke*
#### Documentation
- add developer workflow, release guidelines, contributing guide - (7792fe3) - *HaoZeke*
- update README source with convel, bindings, and performance features - (eda3109) - *HaoZeke*
- add tutorials page with examples for all languages - (931823a) - *HaoZeke*
- add Sphinx docs site with org-mode source and con/convel spec - (e6c8c23) - *HaoZeke*
#### Enhancements
- update C/C++ examples with velocity field access - (d37ac52) - *HaoZeke*
- integrate fast-float2, memmap2 reader, and parallel parsing - (13dc682) - *HaoZeke*
#### Features
- add Rust standalone usage example - (f4d2838) - *HaoZeke*
- add Julia ccall bindings package - (07e0288) - *HaoZeke*
- add PyO3 Python bindings with read/write functions - (eb2b971) - *HaoZeke*
- add Cap'n Proto RPC schema, server, and client - (f5e01df) - *HaoZeke*
- add convel format support with optional velocity fields - (d4c699f) - *HaoZeke*
#### Bug Fixes
- add readme to pyproject.toml for PyPI long description - (934073e) - *HaoZeke*
- bump PyO3 to 0.28 and fix Python build configuration - (13f3837) - *HaoZeke*
#### CI
- add Python wheel CI/CD with PyPI publishing via trusted publisher - (89cd7eb) - *HaoZeke*
#### Chores
- (**version**) v0.3.0 - (55838f6) - *HaoZeke*

- - -

## v0.2.0 - 2025-08-14
#### Buildsystem
- Bump for doctests - (bfe85e1) - *HaoZeke*
- Enable doctests - (1d79f3a) - *HaoZeke*, *bonzini*
#### Maintenance
- Bump versions - (3619311) - *HaoZeke*
- Even faster fails - (f729de5) - *HaoZeke*
- Cleanup and reduce scope - (a734715) - *HaoZeke*
- Cleanup - (3575fcf) - *HaoZeke*
- Fail faster for the FFI writer - (a343b86) - *HaoZeke*
- Nicer documentation - (84b33db) - *HaoZeke*
- Cleanup with constants - (70cad4f) - *HaoZeke*
- Minor cleanup - (a9892c6) - *HaoZeke*
- Remove dup - (dade44d) - *HaoZeke*
- Update format string - (a874a98) - *HaoZeke*
- Fix test [BENCH] - (b53fa91) - *HaoZeke*, *Copilot*, *Copilot*
- Use more constants - (973f924) - *HaoZeke*
- Update gitig - (64e9a79) - *HaoZeke*
- Add an inverse helper for writes - (6170681) - *HaoZeke*
- Minor documentation update - (b89931a) - *HaoZeke*
#### Tests
- Add some for writers - (0a59fcd) - *HaoZeke*
#### Generated
- Update generated readme - (0277e8b) - *HaoZeke*
- Update with a void pointer - (f415740) - *HaoZeke*
#### Documentation
- Discuss the design.. - (9229f0d) - *HaoZeke*
#### Enhancements
- Single pass for the writer - (ae39401) - *HaoZeke*
- More ergonomic without constants for C++ - (7d78227) - *HaoZeke*
- Add a cache for better performance - (ec8244d) - *HaoZeke*
- Rework to use a writer object - (7029562) - *HaoZeke*
- Update to do better on benchmarks - (063a89c) - *HaoZeke*
- Setup the C++ API - (c54daf7) - *HaoZeke*
- Rework to use opaque pointers - (736bb71) - *HaoZeke*
- Rework the FFI for writes - (baae1c8) - *HaoZeke*
- Update the C API sample - (5854ccc) - *HaoZeke*
- Rework CLI to test things a bit - (a1177b6) - *HaoZeke*
- Add a basic writer - (9b825f8) - *HaoZeke*
#### CI
- Try to run benchmarks more - (049c077) - *HaoZeke*
#### Chores
- (**version**) v0.2.0 - (6b762d9) - *HaoZeke*

- - -

## v0.1.1 - 2025-07-19
#### Maintenance
- Fix category tags - (19b7499) - *HaoZeke*
- Bump version - (09ae400) - *HaoZeke*
- Stop hardcoding paths - (7dbb381) - *HaoZeke*
- More sane returns - (66fed6a) - *HaoZeke*
- Add a valgrind suppression file - (9ea9c89) - *HaoZeke*
- Rework to better explain behavior - (d65634a) - *HaoZeke*
- Try to use cargo-dist for generating things - (2ff5ce6) - *HaoZeke*
- Fix license and keywords - (aa016b2) - *HaoZeke*
#### Bugfixes
- Fixup a misunderstanding of lifetimes - (038cc5c) - *HaoZeke*
#### Generated
- Update for criterion - (f1fcfa2) - *HaoZeke*
#### Enhancements
- Demonstrate more of the C++ usage - (f9f838c) - *HaoZeke*
- Setup the iterator usage in the C example - (596f65a) - *HaoZeke*
- Add a more elegant iterator interface to C++ - (706f14b) - *HaoZeke*
- Expose iterators through C interface - (aad794a) - *HaoZeke*
- Implement a basic forward skipper - (6e2c8a4) - *HaoZeke*
#### Benchmarks
- Add iterator validation - (9c49c86) - *HaoZeke*
#### Tests
- Add a test for the forward iterator - (0917875) - *HaoZeke*
#### Buildsystem
- Use the multi con for examples - (cbdfd6a) - *HaoZeke*
#### CI
- Only run benchmarks on request - (222d727) - *HaoZeke*
- Kill useless release thing - (96aa79a) - *HaoZeke*
- Run benchmarks - (f60a32a) - *HaoZeke*
- Use valgrind for gha - (0b2179e) - *HaoZeke*
#### Chores
- (**version**) v0.1.1 - (17cb3b0) - *HaoZeke*

- - -

## v0.1.0 - 2025-07-19
#### Tests
- Update for multi con reads - (6590e83) - *HaoZeke*
- Add more unit tests - (7cd595d) - *HaoZeke*
- Add a more interesting test - (b4c0049) - *HaoZeke*
- Start with a simple test - (fbd71c7) - *HaoZeke*
#### Data
- Import test data from readCon - (c5cf85e) - *HaoZeke*
#### Enhancements
- Add and check a C++ interface - (b713997) - *HaoZeke*
- Add an example for the C API usage - (94cd71d) - *HaoZeke*
- First pass at a baseline C FFI - (577d185) - *HaoZeke*
- Start wiring up C connections for readcon - (5f35e54) - *HaoZeke*
- Add in first working CLI - (74c25fb) - *HaoZeke*
- Add in an iterator - (f7a618d) - *HaoZeke*
- Parse a single frame - (d79938a) - *HaoZeke*
- Setup the parse header function - (4491175) - *HaoZeke*
- Start with error types and a parser - (817e8a8) - *HaoZeke*
- Setup some nicer error handling - (f054edd) - *HaoZeke*
- Use cog - (7d09a68) - *HaoZeke*
#### Maintenance
- Use a tag prefix - (f1f68af) - *HaoZeke*
- Minor renaming - (a871512) - *HaoZeke*
- Be safer to ensure null termination - (ca239bc) - *HaoZeke*
- Update cog setup - (96cbe69) - *HaoZeke*
- Cleanup build for release details - (9af5629) - *HaoZeke*
- Additions for coverage - (3d985ee) - *HaoZeke*
- Stop using designated initializers for hpp - (9bab1f9) - *HaoZeke*
- Finish renaming things - (9e8b5d2) - *HaoZeke*
- Saner default settings, switch to C - (c93c562) - *HaoZeke*
- Enhance the cbindgen file - (54d2fcb) - *HaoZeke*
- Pin a rust version - (d7a6c76) - *HaoZeke*
- Silence clippy - (45dbe6c) - *HaoZeke*
- More output from the header - (04f0715) - *HaoZeke*
- Restructure into a helper and use mass - (eb8d91b) - *HaoZeke*
- Add cbindgen as a build dep - (97cb1c9) - *HaoZeke*
- Fixup for subproject usage - (699d8df) - *HaoZeke*
- Rename project - (2ed99c3) - *HaoZeke*
- Actually link up error struct - (94fb2bf) - *HaoZeke*
- Remember that usize is used for len() - (e51e012) - *HaoZeke*
- Start parsing a bit better - (5de8060) - *HaoZeke*
- Start working through lines - (c076bb5) - *HaoZeke*
- Add in a quick file reading CLI sample - (37422d4) - *HaoZeke*
- Add a test helper - (c896963) - *HaoZeke*
- Start with a project configuration - (5730540) - *HaoZeke*
- Initialize with cargo new - (059e4eb) - *HaoZeke*
#### Documentation
- Kang from rgpycrumbs - (07435a7) - *HaoZeke*
- Minor updates - (f46b178) - *HaoZeke*
- Minor updates - (bcd4df7) - *HaoZeke*
- Add some more - (6529b22) - *HaoZeke*
- Add a bunch - (0ba1212) - *HaoZeke*
- Minor note - (1ecc856) - *HaoZeke*
- Minor update - (489e9df) - *HaoZeke*
- Update readme from readCon - (7751124) - *HaoZeke*
#### Buildsystem
- Remove unstable rust module for stable - (bb7a200) - *HaoZeke*
- Let meson run cargo tests too - (99d4362) - *HaoZeke*
- Finalize first pass for readcon core - (ddff2bc) - *HaoZeke*
#### Generated
- Update readme - (6524e55) - *HaoZeke*
- Vendor a copy of the generated header - (127dd98) - *HaoZeke*
#### CI
- Check commits too - (0f636f1) - *HaoZeke*
- Setup a basic build and run workflow - (ff9be41) - *HaoZeke*
- Import lint and coverage - (36a3a54) - *HaoZeke*
#### Chores
- (**version**) v0.1.0 - (fd6972a) - *HaoZeke*


