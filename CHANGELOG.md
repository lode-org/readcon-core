# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

- - -
## v0.3.2 - 2026-02-24
#### Buildsystem
- add Criterion benchmark regression CI with asv-perch PR commenting
- fix Python wheel builds (macos-15, aarch64 --find-interpreter)
#### Documentation
- regenerate README with current features, installation table, convel spec
- add complete release checklist and CI workflow docs to contributing guide

- - -
## v0.3.1 - 2026-02-24
#### Bug Fixes
- fix all repository URLs from readcon-rs to readcon-core
- update version tracking docs to include pixi.toml and conf.py

- - -
## v0.3.0 - 2026-02-24
#### Features
- add convel format support with optional velocity fields - (d4c699f) - HaoZeke
- add Cap'n Proto RPC schema, server, and client - (f5e01df) - HaoZeke
- add PyO3 Python bindings with read/write functions - (eb2b971) - HaoZeke
- add Julia ccall bindings package - (07e0288) - HaoZeke
- add Rust standalone usage example - (f4d2838) - HaoZeke
#### Enhancements
- integrate fast-float2, memmap2 reader, and parallel parsing - (13dc682) - HaoZeke
- update C/C++ examples with velocity field access - (d37ac52) - HaoZeke
#### Documentation
- add Sphinx docs site with org-mode source and con/convel spec - (e6c8c23) - HaoZeke
- add tutorials page with examples for all languages - (931823a) - HaoZeke
- update README source with convel, bindings, and performance features - (eda3109) - HaoZeke
- add developer workflow, release guidelines, contributing guide - (7792fe3) - HaoZeke
#### Buildsystem
- add CMakeLists.txt and update meson.build for subproject use - (01738af) - HaoZeke
#### Continuous Integration
- add Python wheel CI/CD with PyPI publishing via trusted publisher - (89cd7eb) - HaoZeke
#### Bug Fixes
- bump PyO3 to 0.28 and fix Python build configuration - (13f3837) - HaoZeke
- add readme to pyproject.toml for PyPI long description - (934073e) - HaoZeke

- - -
## v0.2.0 - 2025-08-14
#### Buildsystem
- Bump for doctests - (bfe85e1) - HaoZeke
- Enable doctests - (1d79f3a) - HaoZeke
#### Continuous Integration
- Try to run benchmarks more - (049c077) - HaoZeke
#### Documentation
- Discuss the design.. - (9229f0d) - HaoZeke
#### Enhancements
- Single pass for the writer - (ae39401) - HaoZeke
- More ergonomic without constants for C++ - (7d78227) - HaoZeke
- Add a cache for better performance - (ec8244d) - HaoZeke
- Rework to use a writer object - (7029562) - HaoZeke
- Update to do better on benchmarks - (063a89c) - HaoZeke
- Setup the C++ API - (c54daf7) - HaoZeke
- Rework to use opaque pointers - (736bb71) - HaoZeke
- Rework the FFI for writes - (baae1c8) - HaoZeke
- Update the C API sample - (5854ccc) - HaoZeke
- Rework CLI to test things a bit - (a1177b6) - HaoZeke
- Add a basic writer - (9b825f8) - HaoZeke
#### Generated
- Update generated readme - (0277e8b) - HaoZeke
- Update with a void pointer - (f415740) - HaoZeke
#### Maintenance
- Bump versions - (3619311) - HaoZeke
- Even faster fails - (f729de5) - HaoZeke
- Cleanup and reduce scope - (a734715) - HaoZeke
- Cleanup - (3575fcf) - HaoZeke
- Fail faster for the FFI writer - (a343b86) - HaoZeke
- Nicer documentation - (84b33db) - HaoZeke
- Cleanup with constants - (70cad4f) - HaoZeke
- Minor cleanup - (a9892c6) - HaoZeke
- Remove dup - (dade44d) - HaoZeke
- Update format string - (a874a98) - HaoZeke
- Fix test [BENCH] - (b53fa91) - HaoZeke
- Use more constants - (973f924) - HaoZeke
- Update gitig - (64e9a79) - HaoZeke
- Add an inverse helper for writes - (6170681) - HaoZeke
- Minor documentation update - (b89931a) - HaoZeke
#### Tests
- Add some for writers - (0a59fcd) - HaoZeke

- - -

## v0.1.1 - 2025-07-19
#### Benchmarks
- Add iterator validation - (9c49c86) - HaoZeke
#### Bugfixes
- Fixup a misunderstanding of lifetimes - (038cc5c) - HaoZeke
#### Buildsystem
- Use the multi con for examples - (cbdfd6a) - HaoZeke
#### Continuous Integration
- Only run benchmarks on request - (222d727) - HaoZeke
- Kill useless release thing - (96aa79a) - HaoZeke
- Run benchmarks - (f60a32a) - HaoZeke
- Use valgrind for gha - (0b2179e) - HaoZeke
#### Enhancements
- Demonstrate more of the C++ usage - (f9f838c) - HaoZeke
- Setup the iterator usage in the C example - (596f65a) - HaoZeke
- Add a more elegant iterator interface to C++ - (706f14b) - HaoZeke
- Expose iterators through C interface - (aad794a) - HaoZeke
- Implement a basic forward skipper - (6e2c8a4) - HaoZeke
#### Generated
- Update for criterion - (f1fcfa2) - HaoZeke
#### Maintenance
- Fix category tags - (19b7499) - HaoZeke
- Bump version - (09ae400) - HaoZeke
- Stop hardcoding paths - (7dbb381) - HaoZeke
- More sane returns - (66fed6a) - HaoZeke
- Add a valgrind suppression file - (9ea9c89) - HaoZeke
- Rework to better explain behavior - (d65634a) - HaoZeke
- Try to use cargo-dist for generating things - (2ff5ce6) - HaoZeke
- Fix license and keywords - (aa016b2) - HaoZeke
#### Tests
- Add a test for the forward iterator - (0917875) - HaoZeke

- - -

## v0.1.0 - 2025-07-19
#### Buildsystem
- Remove unstable rust module for stable - (bb7a200) - HaoZeke
- Let meson run cargo tests too - (99d4362) - HaoZeke
- Finalize first pass for readcon core - (ddff2bc) - HaoZeke
#### Continuous Integration
- Check commits too - (0f636f1) - HaoZeke
- Setup a basic build and run workflow - (ff9be41) - HaoZeke
- Import lint and coverage - (36a3a54) - HaoZeke
#### Data
- Import test data from readCon - (c5cf85e) - HaoZeke
#### Documentation
- Kang from rgpycrumbs - (07435a7) - HaoZeke
- Minor updates - (f46b178) - HaoZeke
- Minor updates - (bcd4df7) - HaoZeke
- Add some more - (6529b22) - HaoZeke
- Add a bunch - (0ba1212) - HaoZeke
- Minor note - (1ecc856) - HaoZeke
- Minor update - (489e9df) - HaoZeke
- Update readme from readCon - (7751124) - HaoZeke
#### Enhancements
- Add and check a C++ interface - (b713997) - HaoZeke
- Add an example for the C API usage - (94cd71d) - HaoZeke
- First pass at a baseline C FFI - (577d185) - HaoZeke
- Start wiring up C connections for readcon - (5f35e54) - HaoZeke
- Add in first working CLI - (74c25fb) - HaoZeke
- Add in an iterator - (f7a618d) - HaoZeke
- Parse a single frame - (d79938a) - HaoZeke
- Setup the parse header function - (4491175) - HaoZeke
- Start with error types and a parser - (817e8a8) - HaoZeke
- Setup some nicer error handling - (f054edd) - HaoZeke
- Use cog - (7d09a68) - HaoZeke
#### Generated
- Update readme - (6524e55) - HaoZeke
- Vendor a copy of the generated header - (127dd98) - HaoZeke
#### Maintenance
- Use a tag prefix - (f1f68af) - HaoZeke
- Minor renaming - (a871512) - HaoZeke
- Be safer to ensure null termination - (ca239bc) - HaoZeke
- Update cog setup - (96cbe69) - HaoZeke
- Cleanup build for release details - (9af5629) - HaoZeke
- Additions for coverage - (3d985ee) - HaoZeke
- Stop using designated initializers for hpp - (9bab1f9) - HaoZeke
- Finish renaming things - (9e8b5d2) - HaoZeke
- Saner default settings, switch to C - (c93c562) - HaoZeke
- Enhance the cbindgen file - (54d2fcb) - HaoZeke
- Pin a rust version - (d7a6c76) - HaoZeke
- Silence clippy - (45dbe6c) - HaoZeke
- More output from the header - (04f0715) - HaoZeke
- Restructure into a helper and use mass - (eb8d91b) - HaoZeke
- Add cbindgen as a build dep - (97cb1c9) - HaoZeke
- Fixup for subproject usage - (699d8df) - HaoZeke
- Rename project - (2ed99c3) - HaoZeke
- Actually link up error struct - (94fb2bf) - HaoZeke
- Remember that usize is used for len() - (e51e012) - HaoZeke
- Start parsing a bit better - (5de8060) - HaoZeke
- Start working through lines - (c076bb5) - HaoZeke
- Add in a quick file reading CLI sample - (37422d4) - HaoZeke
- Add a test helper - (c896963) - HaoZeke
- Start with a project configuration - (5730540) - HaoZeke
- Initialize with cargo new - (059e4eb) - HaoZeke
#### Tests
- Update for multi con reads - (6590e83) - HaoZeke
- Add more unit tests - (7cd595d) - HaoZeke
- Add a more interesting test - (b4c0049) - HaoZeke
- Start with a simple test - (fbd71c7) - HaoZeke

- - -

Changelog generated by [cocogitto](https://github.com/cocogitto/cocogitto).