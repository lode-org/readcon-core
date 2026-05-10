# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

## v0.10.0 - 2026-05-10
#### Benchmarks
- add trajectory-style write fixture with heavy shared metadata - (71cbbb5) - *HaoZeke*
- write 100-frame trajectory through ConFrameWriter - (4b960b9) - *HaoZeke*
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
#### Generated
- regenerate CHANGELOG.md from cog - (b3caca7) - *HaoZeke*
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
#### Performance Improvements
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
#### Performance Improvements
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
#### Miscellaneous Chores
- (**julia**) ignore local test manifest - (321cd28) - *HaoZeke*
#### Style
- (**lints**) scope clippy allows from crate-level to call sites - (334aaec) - *HaoZeke*
- (**parser**) satisfy strict validation lints - (36dbb89) - *HaoZeke*
- apply rustfmt - (76e4aa8) - *HaoZeke*

- - -

## v0.8.0 - 2026-05-10
#### Maintenance
- bump to v0.8.0 - (f5b14a8) - *HaoZeke*
#### Generated
- regenerate CHANGELOG.md from cog - (4520b3e) - *HaoZeke*
#### Buildsystem
- (**capi**) add cargo-c metadata and compatibility feature - (f776281) - *HaoZeke*
#### Features
- (**ffi**) add builder metadata setters and JSON escape hatch - (75a756e) - *HaoZeke*
- (**python**) add metadata helper parity across bindings - (3d6ca04) - *HaoZeke*
#### Bug Fixes
- (**parallel**) use Arc for shared atom symbols - (5224b02) - *HaoZeke*
#### Documentation
- (**readme**) regenerate from readme_src.org - (ec03eb9) - *HaoZeke*

- - -

## v0.7.3 - 2026-05-10
#### Generated
- regenerate CHANGELOG.md from cog - (0cc3353) - *HaoZeke*
#### Miscellaneous Chores
- bump to v0.7.3 - (180a49d) - *HaoZeke*

- - -

## v0.7.2 - 2026-05-10
#### Features
- pbc + lattice_vectors metadata, changelog catch-up, v0.7.2 - (e2df964) - *HaoZeke*
- pbc and lattice_vectors metadata keys, bump to v0.7.1 - (c370728) - *HaoZeke*

- - -

## v0.7.1 - 2026-05-10
#### Bug Fixes
- use path.string().c_str() for Windows wchar_t compatibility - (ce8f6ba) - *HaoZeke*

- - -

## v0.7.0 - 2026-05-10
#### Documentation
- rewrite spec.org as implementation-neutral format standard - (75f55b6) - *HaoZeke*
- evolution rationale, reference impls, benchmark script, spec bitmask table - (06c26d2) - *HaoZeke*
- spec update for forces/sections/compression, FAQ, benchmarks - (73e4edd) - *HaoZeke*
- add recommended metadata keys to CON spec - (389d16f) - *HaoZeke*
#### Maintenance
- rebuild .gitignore with gibo (Rust, C++, C, Python, CMake, macOS, Linux) - (e4458cb) - *HaoZeke*
#### Benchmarks
- publication-quality plots, feature matrix, Pareto front - (a44e269) - *HaoZeke*
- scaling benchmarks with memory usage across file sizes - (851076a) - *HaoZeke*
- add C sscanf reader, real 4-way comparison - (861191e) - *HaoZeke*
- real cross-implementation numbers (readcon 8-9x faster than ASE) - (3e40cdd) - *HaoZeke*
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
#### Continuous Integration
- add doc preview commenter workflow for PRs - (7de693c) - *HaoZeke*
#### Miscellaneous Chores
- (**docs**) orgmode fixes - (c41f3e9) - *HaoZeke*
- (**docs**) exclude auto-generated binary docs from sphinx build - (8469e90) - *HaoZeke*
- (**docs**) standardize atom_id terminology across all org files - (28d9917) - *HaoZeke*
- (**docs**) fix broken link - (875f4b1) - *HaoZeke*
- (**docs**) rework - (84addba) - *HaoZeke*
- (**org**) format - (cbfb637) - *HaoZeke*
- (**spec**) cleanup - (4787b8f) - *HaoZeke*
- (**title**) no  ~~ - (e699b01) - *HaoZeke*

- - -

## v0.6.0 - 2026-05-10
#### Features
- JSON metadata line on line 2 of CON header (spec v2) - (ac94cd1) - *HaoZeke*

- - -

## v0.5.2 - 2026-05-10
#### Features
- transfer velocities and masses in ASE conversion - (633adfa) - *HaoZeke*
#### Miscellaneous Chores
- bump to v0.5.2 - (9fbae89) - *HaoZeke*

- - -

## v0.5.1 - 2026-05-10
#### Features
- transfer atom_id to/from ASE Atoms via tags and custom array - (75fc1ef) - *HaoZeke*
#### Bug Fixes
- do not overwrite ASE tags in to_ase(), use only atom_id array - (3f99f49) - *HaoZeke*

- - -

## v0.5.0 - 2026-05-10
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

## v0.4.4 - 2026-05-10
#### Documentation
- add v0.4.0-v0.4.3 changelog, update tutorials and bindings - (3eed202) - *HaoZeke*
#### Features
- (**docs**) add Umami analytics and TurtleTech footer - (9f5606b) - *HaoZeke*
#### Bug Fixes
- (**bld**) use link_args instead of link_with in declare_dependency - (261aa19) - *HaoZeke*
- (**bld**) do not install cargo custom_target - (a861711) - *HaoZeke*
- Windows support for meson build - (3b80468) - *HaoZeke*
#### Miscellaneous Chores
- bump to v0.4.4 - (ec241bc) - *HaoZeke*

- - -

## v0.4.3 - 2026-05-10
#### Bug Fixes
- (**ci**) set PYO3_PYTHON for coverage with --all-features - (7ebbd3c) - *HaoZeke*
#### Performance Improvements
- use read_to_string for small files, add read_first_frame - (fc1b0d6) - *HaoZeke*
#### Miscellaneous Chores
- bump to v0.4.3 - (d797dc3) - *HaoZeke*

- - -

## v0.4.2 - 2026-05-10
#### Tests
- add coverage for precision, constructors, mass roundtrip - (ebc3873) - *HaoZeke*
#### Features
- (**py**) expose per-atom mass in Python bindings, bump v0.4.2 - (0c08b7f) - *HaoZeke*
#### Bug Fixes
- (**ci**) add cargo bin to PATH for sphinx-rustdocgen - (e36eabb) - *HaoZeke*

- - -

## v0.4.1 - 2026-05-10
#### Bug Fixes
- (**docs**) toctree rendering, add sphinxcontrib-rust for Rust API docs - (1f5aa2b) - *HaoZeke*
#### Continuous Integration
- add release workflow for native library artifacts - (dfdc873) - *HaoZeke*
#### Miscellaneous Chores
- (**version**) v0.4.1 - (a37ef79) - *HaoZeke*

- - -

## v0.4.0 - 2026-05-10
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
#### Miscellaneous Chores
- (**version**) v0.4.0 - (16d9d01) - *HaoZeke*

- - -

## v0.3.2 - 2026-05-10
#### Buildsystem
- add benchmark regression CI, fix wheel builds, update README - (317258f) - *HaoZeke*
#### Miscellaneous Chores
- (**version**) v0.3.2 - (bf38176) - *HaoZeke*

- - -

## v0.3.1 - 2026-05-10
#### Miscellaneous Chores
- (**version**) v0.3.1 - (46d9b38) - *HaoZeke*

- - -

## v0.3.0 - 2026-05-10
#### Enhancements
- update C/C++ examples with velocity field access - (d37ac52) - *HaoZeke*
- integrate fast-float2, memmap2 reader, and parallel parsing - (13dc682) - *HaoZeke*
#### Buildsystem
- add CMakeLists.txt and update meson.build for subproject use - (01738af) - *HaoZeke*
#### Documentation
- add developer workflow, release guidelines, contributing guide - (7792fe3) - *HaoZeke*
- update README source with convel, bindings, and performance features - (eda3109) - *HaoZeke*
- add tutorials page with examples for all languages - (931823a) - *HaoZeke*
- add Sphinx docs site with org-mode source and con/convel spec - (e6c8c23) - *HaoZeke*
#### Features
- add Rust standalone usage example - (f4d2838) - *HaoZeke*
- add Julia ccall bindings package - (07e0288) - *HaoZeke*
- add PyO3 Python bindings with read/write functions - (eb2b971) - *HaoZeke*
- add Cap'n Proto RPC schema, server, and client - (f5e01df) - *HaoZeke*
- add convel format support with optional velocity fields - (d4c699f) - *HaoZeke*
#### Bug Fixes
- add readme to pyproject.toml for PyPI long description - (934073e) - *HaoZeke*
- bump PyO3 to 0.28 and fix Python build configuration - (13f3837) - *HaoZeke*
#### Continuous Integration
- add Python wheel CI/CD with PyPI publishing via trusted publisher - (89cd7eb) - *HaoZeke*
#### Miscellaneous Chores
- (**version**) v0.3.0 - (55838f6) - *HaoZeke*

- - -

## v0.2.0 - 2026-05-10
#### Documentation
- Discuss the design.. - (9229f0d) - *HaoZeke*
#### Buildsystem
- Bump for doctests - (bfe85e1) - *HaoZeke*
- Enable doctests - (1d79f3a) - *HaoZeke*
#### Generated
- Update generated readme - (0277e8b) - *HaoZeke*
- Update with a void pointer - (f415740) - *HaoZeke*
#### Tests
- Add some for writers - (0a59fcd) - *HaoZeke*
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
- Fix test [BENCH] - (b53fa91) - *HaoZeke*
- Use more constants - (973f924) - *HaoZeke*
- Update gitig - (64e9a79) - *HaoZeke*
- Add an inverse helper for writes - (6170681) - *HaoZeke*
- Minor documentation update - (b89931a) - *HaoZeke*
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
#### Continuous Integration
- Try to run benchmarks more - (049c077) - *HaoZeke*
#### Miscellaneous Chores
- (**version**) v0.2.0 - (6b762d9) - *HaoZeke*

- - -

## v0.1.1 - 2026-05-10
#### Bugfixes
- Fixup a misunderstanding of lifetimes - (038cc5c) - *HaoZeke*
#### Generated
- Update for criterion - (f1fcfa2) - *HaoZeke*
#### Buildsystem
- Use the multi con for examples - (cbdfd6a) - *HaoZeke*
#### Maintenance
- Fix category tags - (19b7499) - *HaoZeke*
- Bump version - (09ae400) - *HaoZeke*
- Stop hardcoding paths - (7dbb381) - *HaoZeke*
- More sane returns - (66fed6a) - *HaoZeke*
- Add a valgrind suppression file - (9ea9c89) - *HaoZeke*
- Rework to better explain behavior - (d65634a) - *HaoZeke*
- Try to use cargo-dist for generating things - (2ff5ce6) - *HaoZeke*
- Fix license and keywords - (aa016b2) - *HaoZeke*
#### Benchmarks
- Add iterator validation - (9c49c86) - *HaoZeke*
#### Enhancements
- Demonstrate more of the C++ usage - (f9f838c) - *HaoZeke*
- Setup the iterator usage in the C example - (596f65a) - *HaoZeke*
- Add a more elegant iterator interface to C++ - (706f14b) - *HaoZeke*
- Expose iterators through C interface - (aad794a) - *HaoZeke*
- Implement a basic forward skipper - (6e2c8a4) - *HaoZeke*
#### Tests
- Add a test for the forward iterator - (0917875) - *HaoZeke*
#### Continuous Integration
- Only run benchmarks on request - (222d727) - *HaoZeke*
- Kill useless release thing - (96aa79a) - *HaoZeke*
- Run benchmarks - (f60a32a) - *HaoZeke*
- Use valgrind for gha - (0b2179e) - *HaoZeke*
#### Miscellaneous Chores
- (**version**) v0.1.1 - (17cb3b0) - *HaoZeke*

- - -

## v0.1.0 - 2026-05-10
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
#### Generated
- Update readme - (6524e55) - *HaoZeke*
- Vendor a copy of the generated header - (127dd98) - *HaoZeke*
#### Data
- Import test data from readCon - (c5cf85e) - *HaoZeke*
#### Buildsystem
- Remove unstable rust module for stable - (bb7a200) - *HaoZeke*
- Let meson run cargo tests too - (99d4362) - *HaoZeke*
- Finalize first pass for readcon core - (ddff2bc) - *HaoZeke*
#### Tests
- Update for multi con reads - (6590e83) - *HaoZeke*
- Add more unit tests - (7cd595d) - *HaoZeke*
- Add a more interesting test - (b4c0049) - *HaoZeke*
- Start with a simple test - (fbd71c7) - *HaoZeke*
#### Documentation
- Kang from rgpycrumbs - (07435a7) - *HaoZeke*
- Minor updates - (f46b178) - *HaoZeke*
- Minor updates - (bcd4df7) - *HaoZeke*
- Add some more - (6529b22) - *HaoZeke*
- Add a bunch - (0ba1212) - *HaoZeke*
- Minor note - (1ecc856) - *HaoZeke*
- Minor update - (489e9df) - *HaoZeke*
- Update readme from readCon - (7751124) - *HaoZeke*
#### Continuous Integration
- Check commits too - (0f636f1) - *HaoZeke*
- Setup a basic build and run workflow - (ff9be41) - *HaoZeke*
- Import lint and coverage - (36a3a54) - *HaoZeke*
#### Miscellaneous Chores
- (**version**) v0.1.0 - (fd6972a) - *HaoZeke*


