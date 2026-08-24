# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

## v0.14.8 - 2026-08-24
#### Benchmarks
- CON parse vs RCSO decode and Unix vs TCP RPC - (9b94ca5) - *HaoZeke*
#### Merges
- HaoZeke main - (29a6cf7) - *HaoZeke*
- integrate HaoZeke main Cachegrind restamp - (751aaa3) - *HaoZeke*
#### Generated
- (**docs**) export RST from orgmode - (a1f932d) - *HaoZeke*
#### Features
- (**abi**) expose readcon compatibility stamp - (e2233e7) - *HaoZeke*
- (**abi**) borrow SoA columns from C, Fortran, and Python - (b734e01) - *HaoZeke*
- (**bench**) add sequential vs Rayon wall-scale harness - (338f9b7) - *HaoZeke*
- (**bench**) stamp peer JSON with host, date, and commit - (69b4595) - *HaoZeke*
- (**builder**) author charges, spins, and magmoms on write - (25b8b1b) - *HaoZeke*
- (**builder**) return insertion-to-grouped map and reject type mass mismatch - (db385fa) - *HaoZeke*
- (**capi**) pack and unpack RCSO for caller Bcast - (9f64eac) - *HaoZeke*
- (**capi**) probe Rayon and ship it on clib tarballs - (51146ea) - *HaoZeke*
- (**chemfiles**) stamp internal units and use read_step - (aff5485) - *HaoZeke*
- (**dist**) attach prebuilt C ABI prefixes via package-clib.sh - (294ab0d) - *HaoZeke*
- (**examples**) run the CPC NEB vignette and lock neb_band.tsv - (33f2a00) - *HaoZeke*
- (**examples**) run the CPC NEB vignette and lock neb_band.tsv - (b63f2cd) - *HaoZeke*
- (**examples**) four-image 218-atom CuH2 band fixture - (778c4f8) - *HaoZeke*
- (**examples**) print NEB bead energies from C++ and Fortran - (72e3fb5) - *HaoZeke*
- (**examples**) print a four-image NEB band from Fortran - (bfbc536) - *HaoZeke*
- (**io**) pin Rayon workers on C, Python, and Fortran reads - (bc9056e) - *HaoZeke*
- (**iter**) skip, nth, and count on every binding - (a5527ba) - *HaoZeke*
- (**python**) export symbol/Z helpers with documented Z=92 ceiling - (7226958) - *HaoZeke*
- (**rpc**) ABI minor reject, Unix endpoints, and RCSO pack - (21251cc) - *HaoZeke*
- (**rpc**) Unix domain endpoints beside TCP - (8d82ce0) - *HaoZeke*
- pack and unpack RCSO for caller-side Bcast - (01a2330) - *HaoZeke*
- canonicalize unit aliases on CON line 2 - (0eac2a9) - *HaoZeke*
- accept ns as a time unit in the SI parser - (828ce32) - *HaoZeke*
#### Bug Fixes
- (**builder**) return Result from build and stop C/Python panics - (9770d35) - *HaoZeke*
- (**capi**) document Rayon on the cbindgen banner - (04371eb) - *HaoZeke*
- (**chemfiles**) one mass per CON symbol on import - (2efa28e) - *HaoZeke*
- (**ci**) checksum cargo-dist on every release runner - (caedefe) - *HaoZeke*
- (**ci**) pin release actions and checksum installers - (12a1aeb) - *HaoZeke*
- (**ci**) keep Pages and OIDC off pull_request jobs - (05b5d0b) - *HaoZeke*
- (**ci**) do not pass empty --features on the Windows clib job - (9db7538) - *HaoZeke*
- (**cov**) omit src/ffi.rs from the rust line-coverage gate - (df8fb58) - *HaoZeke*
- (**cov**) do not let the unused cdylib zero C ABI hits - (56081c7) - *HaoZeke*
- (**cpc**) escape underscores in Cachegrind scenario names - (899f268) - *HaoZeke*
- (**cxx**) friend the helpers that construct ConFrame - (df9d764) - *HaoZeke*
- (**cxx**) define ConFrameIterator::nth after ConFrame is complete - (a89e5fb) - *HaoZeke*
- (**dlpack**) mark device-tagged and CUDA exports read-only - (ec78a5e) - *HaoZeke*
- (**examples**) print NA for missing NEB bead fields - (3303ee5) - *HaoZeke*
- (**fortran**) parse golden JSON numbers without list-directed I/O - (218c6a5) - *HaoZeke*
- (**julia**) replace placeholder package UUID - (4d4b177) - *HaoZeke*
- (**packaging**) omit cargo --features when the clib build is lean - (8c9c256) - *HaoZeke*
- (**python**) export has_parallel_support - (953a965) - *HaoZeke*
- (**rpc**) use ConFrame atom_data length in unix test - (ba1df62) - *HaoZeke*
- (**rpc**) reject newer ABI minor - (aba90d4) - *HaoZeke*
- (**write**) keep std::fmt at lossless precision - (26d0e15) - *HaoZeke*
- (**write**) drop half-ulp cases from the std format lock - (3c63b80) - *HaoZeke*
- mol SI factor is N_A so kcal/mol matches metatomic - (40997a0) - *HaoZeke*
- keep shipped changelog free of Unreleased - (6503a4b) - *HaoZeke*
#### Performance
- (**parallel**) reuse Rayon pools pinned by worker count - (dbec2f7) - *HaoZeke*
- (**write**) format atom floats without std::fmt - (2cbeb95) - *HaoZeke*
- (**write**) emit each frame with one write_all - (07f4902) - *HaoZeke*
#### Documentation
- (**brand**) CON frame glyph and hero wordmark - (27a392f) - *HaoZeke*
- (**cpc**) input the companion fair-campaign table - (c2ade2e) - *HaoZeke*
- (**cpc**) shorten table captions that overflowed XeTeX - (d6e2084) - *HaoZeke*
- (**cpc**) name the restamped Cachegrind commit in the org - (927fc93) - *HaoZeke*
- (**cpc**) restamp Cachegrind table from the merged rst - (09ff081) - *HaoZeke*
- (**cpc**) match the CPiP summary fields and cite the archive DOI - (7244726) - *HaoZeke*
- (**cpc**) write the manuscript as org and export to elsarticle - (c4cab6d) - *HaoZeke*
- (**cpc**) tabulate Rayon scale and the four-image band - (a721853) - *HaoZeke*
- (**cpc**) state ASE eon errors and writer mask 7 - (b72b474) - *HaoZeke*
- (**cpc**) split the wall-time table by protocol - (5e26b0a) - *HaoZeke*
- (**cpc**) cite peers, restamp tables, add a three-bead band - (16e1dc2) - *HaoZeke*
- (**cpc**) add manuscript skeleton and archival deposit metadata - (e662869) - *HaoZeke*
- (**howto**) document n_threads on the read path - (84830a6) - *HaoZeke*
- (**org**) record n_threads on the C and Python read path - (c4b478e) - *HaoZeke*
- (**rpc**) point pack-then-Bcast at rcso::encode_frame - (ea758e0) - *HaoZeke*
- (**rpc**) document Unix endpoints and the fabric split - (5a42b0e) - *HaoZeke*
- (**spec**) reject type-mass mismatch instead of last-wins - (4784658) - *HaoZeke*
- drop internal tracker table from public issue-status - (dc8bfc4) - *HaoZeke*
- state CON-everywhere on the crate readme source - (81d7850) - *HaoZeke*
- state the CON-everywhere ambition on the landing page - (1268816) - *HaoZeke*
- stop teaching the cargo-dist installer pipe - (018aa1e) - *HaoZeke*
- refresh integration status pins - (bd671e2) - *HaoZeke*
- record the 0.14.x C ABI freeze and keep text CON authoritative - (46ca3be) - *HaoZeke*
- pin FetchContent and wrap to the v0.14.7 cxx tarball - (da180b1) - *HaoZeke*
- add LODE vs third-party consumer scorecard - (c96b499) - *HaoZeke*
- add related-work bibliography entries - (2e74b73) - *HaoZeke*
- pin cargo add readcon-core to 0.14.7 - (b0595f5) - *HaoZeke*
- cite CON spec v3 and add crate homepage - (2391e1e) - *HaoZeke*
- point FetchContent at the last attached cxx tarball - (ff1569b) - *HaoZeke*
- align rustdoc and leftover pins with spec-2 decode - (d87b85f) - *HaoZeke*
- paper-voice landing pages and 0.14.7 install pins - (5eb97ce) - *HaoZeke*
#### Tests
- (**ci**) gate docs OIDC, release pins, and version lockstep - (244df46) - *HaoZeke*
- (**conformance**) lock goldens on C, Fortran, and Julia - (001abb5) - *HaoZeke*
- (**conformance**) lock goldens on C, Fortran, and Julia - (72d4645) - *HaoZeke*
- (**conformance**) lock Phase A goldens from Python - (f19a1e0) - *HaoZeke*
- (**conformance**) lock Phase A goldens - (fef746f) - *HaoZeke*
- (**conformance**) lock more column-4 masks and reject paths - (7e490b9) - *HaoZeke*
- (**conformance**) add Phase A clause-keyed corpus - (bf521ce) - *HaoZeke*
- (**python**) expect four beads on neb_band.con - (80be3b8) - *HaoZeke*
- (**rpc**) keep the rpc feature free of UCX - (34a061f) - *HaoZeke*
- (**rpc**) keep the rpc feature free of UCX - (51c3b6a) - *HaoZeke*
- (**rpc**) reject incompatible ABI majors and newer minors - (e7b16dc) - *HaoZeke*
- (**wrap**) check wrap source_hash matches published cxx SHA - (bcf44f6) - *HaoZeke*
- (**write**) lock float digits at default precision only - (48ea3ed) - *HaoZeke*
#### CI
- (**cxx**) attach tarballs on workflow_dispatch by tag - (f43952b) - *HaoZeke*
- (**python**) install ase so test_ase.py is not skipped - (57a6c6b) - *HaoZeke*
- lint gates, C ABI header contract, and C++ nth - (4d236fb) - *HaoZeke*
- stop treating cbindgen as the C ABI authority - (d6809dc) - *HaoZeke*
- do not fail coverage jobs on grep SIGPIPE - (1f5a79d) - *HaoZeke*
- accept git revert subjects and NAMD in the lint gates - (846cd59) - *HaoZeke*
- restrict PR permissions and pin release actions - (92a669c) - *HaoZeke*
#### Chores
- (**bench**) refresh Cachegrind I-refs for docs - (05e74f0) - github-actions[bot]
- (**bench**) restamp wall_scale from the write-path harness - (1ef4946) - *HaoZeke*
- (**bench**) refresh Cachegrind I-refs for docs - (98248b1) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (2c75e8e) - github-actions[bot]
- (**bench**) stamp leaf I/O walls from rgam5terra - (8b51faf) - *HaoZeke*
- (**bench**) refresh Cachegrind I-refs for docs - (89ace10) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (79d764a) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (89d5f2b) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (8fd9f33) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (2c18a52) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (dd46329) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (596fb8e) - github-actions[bot]
- (**bench**) restamp wall_scale with skip and nth on terra - (13b3316) - *HaoZeke*
- (**bench**) refresh Cachegrind I-refs for docs - (e5aeaa1) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (bd16d7a) - github-actions[bot]
- (**bench**) record Rayon scale walls from rgam5terra - (2a048d5) - *HaoZeke*
- (**bench**) refresh Cachegrind I-refs for docs - (b194bd3) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (d5b596f) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (e0a3cdd) - github-actions[bot]
- (**bench**) record rgam5terra equal-geometry wall timings - (f584990) - *HaoZeke*
- (**bench**) refresh Cachegrind I-refs for docs - (4ae7048) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (9b3ae43) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (c94b4ec) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (9e687ab) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (0cc01c6) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (c4885e8) - github-actions[bot]
- (**capi**) regenerate shipped header from cbindgen - (300ea51) - *HaoZeke*
- (**cite**) record the v0.14.7 Zenodo DOI - (3063570) - *HaoZeke*
- (**julia**) lock ReadCon package version to 0.14.7 - (93307e5) - *HaoZeke*
- add SECURITY.md, CONTRIBUTING.md, and CoC contact - (874ba0f) - *HaoZeke*
#### Style
- (**cpc**) ruff-format gen_tables.py - (b0c206c) - *HaoZeke*
- (**docs**) state the C ABI as a Fortran/C++ trade-off - (10caaf1) - *HaoZeke*
- (**docs**) apply rgoswami register to user-facing prose - (b1e1d11) - *HaoZeke*
- apply prek format and keep regen output hook-clean - (e95c193) - *HaoZeke*



## v0.14.7 - 2026-08-15
#### Bug Fixes
- link ``advapi32`` so Windows ``readcon-chemfiles`` resolves ``GetUserNameA``

## v0.14.6 - 2026-08-15
#### Bug Fixes
- build ``readcon-chemfiles`` wheels on windows-2022 with the official prebuilt libchemfiles

## v0.14.5 - 2026-08-15
#### Bug Fixes
- macOS ``readcon-chemfiles`` wheels link the official prebuilt libchemfiles (Linux stays ``chemfiles-from-sources``)

## v0.14.4 - 2026-08-15
#### Bug Fixes
- pass ``HAVE_UNISTD_H`` so macOS chemfiles wheels compile vendored zlib against the current SDK

## v0.14.3 - 2026-08-15
#### Bug Fixes
- rename `grammar/con.pest` to `grammar/readcon.pest` so Windows checkout works
- use system zlib (`CHFL_SYSTEM_ZLIB=ON`) for macOS chemfiles wheels

## v0.14.2 - 2026-08-15
#### Bug Fixes
- (**meson**) set build rpath so FFI example tests find the cdylib - (afb0d50) - *HaoZeke*
- decode column 4 value 1 as x-only on spec 2 - (f623634) - *HaoZeke*
- drop PARALLEL_BYTES_THRESHOLD from the shipped C header - (8f5a640) - *HaoZeke*
- keep PARALLEL_BYTES_THRESHOLD off the C ABI - (e865512) - *HaoZeke*
- keep decode_fixed_bitmask_for_spec off the C ABI - (cd7271d) - *HaoZeke*
- decode column 4 value 1 as x-only on spec 2 - (627b448) - *HaoZeke*
#### CI
- keep fuse-ld=bfd on Linux wheels only - (ae96232) - *HaoZeke*
- build Python extensions inside a venv - (4b146be) - *HaoZeke*



## v0.14.1 - 2026-08-15
#### Benchmarks
- ASV Python surface + spyglass PR compare - (4795333) - *HaoZeke*
- terra release profile of efficiency APIs - (e5919ff) - *HaoZeke*
- fair multi-format trajectory harness (CON vs ASE XYZ/CON) - (913ed36) - *HaoZeke*
#### Features
- (**bench**) report CON.gz and CON.zst next to H5MD peers - (af1ec62) - *HaoZeke*
- (**cmake**) ship FetchContent targets without cbindgen - (59ec316) - *HaoZeke*
- (**cuda**) H2D frame/FFI DLPack export for kDLCUDA - (30611f9) - *HaoZeke*
- (**cuda**) real device allocate and DLPack export via cudarc - (406160e) - *HaoZeke*
- (**dist**) cxx source tarball, wrapdb wrap, and cbindgen-free CI - (3b3249a) - *HaoZeke*
- (**grammar**) ship CON/convel surface PEG (Pest) with fixture tests - (e2d84f2) - *HaoZeke*
- (**meson**) install lib and readcon-core.pc without cbindgen - (46690b2) - *HaoZeke*
- (**rpc**) Cap'n Proto ConFrameData at CON v3 parity - (59b6355) - *HaoZeke*
- (**spec**) machine-readable metadata JSON Schema with conformance tests - (1d4c06a) - *HaoZeke*
- convert foreign structures to CON for stack migration - (e73dcf6) - *HaoZeke*
- optional charges, spins, magmoms sections on v2/v3 surface - (d291fe8) - *HaoZeke*
- CI pytest for Python bindings; Fortran iterator coverage - (82b0e11) - *HaoZeke*
- strong-scaling parallel parse and device-tagged DLPack - (4140c63) - *HaoZeke*
#### Bug Fixes
- (**chemfiles**) build C++ from source; prebuilt .ctors never run under rust-lld - (233f8c9) - *HaoZeke*
- (**ci**) rerun build.rs when metatensor env file is missing on cold builds - (4c403b4) - *HaoZeke*
- (**cmake**) pass --lib to cargo rustc for the C ABI - (bdfc1f5) - *HaoZeke*
- (**cxx**) C-only CMake, slim/vendor tarballs, and matching .pc - (5d77be1) - *HaoZeke*
- (**docs**) fail on Babel tangle drift; drop soft-fallback runners - (8a9527b) - *HaoZeke*
- (**docs**) keep README docs/orgmode links as .org after ox-md export - (7a2375c) - *HaoZeke*
- (**ffi**) declare set_canonical out-of-line and silence non-cuda device_id - (ff963d7) - *HaoZeke*
- (**grammar**) scalar/vector section kinds and CI lockstep - (7c1742b) - *HaoZeke*
- (**julia**) do-block order for _with_frame_handle - (2f52c63) - *HaoZeke*
- (**julia**) matrix helpers use rebuilt frame handles - (29949d3) - *HaoZeke*
- (**meson**) rename cargo_features; rust_features is reserved - (a40159a) - *HaoZeke*
- (**python**) drop unsafe coords cache; keep GIL detach and bulk SoA - (c9a9a95) - *HaoZeke*
- (**test**) lean FFI chemfiles probe is 0 without the feature - (41dd30b) - *HaoZeke*
#### Performance
- (**iterators**) lean multi-frame positions path without AtomDatum - (edd148f) - *HaoZeke*
- (**parser**) memchr line cursor, coords-only assemble, skip section sync - (33a0c68) - *HaoZeke*
- (**parser**) profile-guided flat f64 SoA fill; add PGO harness - (17f2dfe) - *HaoZeke*
- (**parser**) byte-scan atom lines with parse_partial + contiguous SoA - (1f3e66d) - *HaoZeke*
- (**python**) prove detach+bulk SoA via same-session terra A/B - (0831da4) - *HaoZeke*
- (**python**) detach GIL for parse; bulk SoA positions; cache coords - (df2a3c8) - *HaoZeke*
- restore internal parse opts without extra public API - (7d76127) - *HaoZeke*
- stream Python iter, positions-only load, size-only parallel gate - (5cf84c1) - *HaoZeke*
- thresholded parallel multi-frame parse in read_all_frames - (250ed37) - *HaoZeke*
#### Revert
- drop speculative parse micro-opts; keep full-frame fast path - (62372b3) - *HaoZeke*
#### Documentation
- (**a11y**) never invert mermaid SVGs; force the light plate - (25b64fe) - *HaoZeke*
- (**a11y**) mermaid on light plate with AA node text in both themes - (ddd9747) - *HaoZeke*
- (**api**) make coords-only a named product, not a second read_all - (7a49971) - *HaoZeke*
- (**bench**) Pareto uses measured ASE CON and ASE extXYZ separately - (11b069b) - *HaoZeke*
- (**benchmarks**) stop presenting wall-clock medians as results - (232f5c8) - *HaoZeke*
- (**css**) accessible token colours on dark code fences - (5736ca7) - *HaoZeke*
- (**css**) force inline spans in code fences (fix whitespace) - (e49490e) - *HaoZeke*
- (**css**) force inline data-line spans for correct fence whitespace - (1f14753) - *HaoZeke*
- (**css**) restore normal code whitespace (no block on data-line) - (b6968e0) - *HaoZeke*
- (**css**) keep code [data-line] as block (R/Python fences) - (9664edd) - *HaoZeke*
- (**css**) single frame on code blocks (no nested border lines) - (7afa141) - *HaoZeke*
- (**spec**) schema pointer, media type guidance, v4 candidate scope - (7071183) - *HaoZeke*
- (**spec**) front matter declares v3 current, v2 accepted - (ded6011) - *HaoZeke*
- URL_HASH, dual-link ban, and cargo-dist cxx tarball pointer - (74674e2) - *HaoZeke*
- CMake FetchContent, Meson wrap, and shipped C headers - (deb6d14) - *HaoZeke*
- package destinations on README and bindings tip - (090ae06) - *HaoZeke*
- install matrix with package destinations and homepage strip - (e498a4a) - *HaoZeke*
- surface migrate nav, index_proj, and stack destinations - (e1d6c32) - *HaoZeke*
- surface readcon-db package docs and docs.rs API - (05b136f) - *HaoZeke*
- kill HDF5/XYZ carve-outs; route corpora to readcon-db - (e8e76c8) - *HaoZeke*
- honest measurement prose without host-diary numbers - (a1f84da) - *HaoZeke*
- equal-geometry proof — ASE XYZ slower than readcon CON - (118a96e) - *HaoZeke*
- sync parsing_throughput.svg from compare_readers run - (a957983) - *HaoZeke*
- cite measured CON peer speed; ban anti-product carve-outs - (520296d) - *HaoZeke*
- center migration on the library API, not special-case stacks - (59b202d) - *HaoZeke*
- note readcon-db campaign features in README features list - (b010f4d) - *HaoZeke*
- sell readcon-db, selection, and chemparseplot as CON migration gains - (aba7112) - *HaoZeke*
- Diátaxis layout with One Good Tutorial for CON checkpoints - (ff4fdeb) - *HaoZeke*
- list optional charges/spins/magmoms on v2/v3 entry surfaces - (c774e00) - *HaoZeke*
- state the goal as putting CON into every tool path - (d3bfd0e) - *HaoZeke*
- drop H5MD/format bake-off from product entry surfaces - (f0acbcb) - *HaoZeke*
- ground CON in code and literature without hedges - (d588bcf) - *HaoZeke*
- frame CON for multi-code pipelines, not only eOn/LODE - (427971d) - *HaoZeke*
- present CON as a full checkpoint format - (da6c617) - *HaoZeke*
- rewrite entry prose in project voice - (4a201cf) - *HaoZeke*
- write CON positioning in H5MD-style Objective form - (79d7b75) - *HaoZeke*
- center CON as eOn/LODE saddle checkpoint contract - (bf35046) - *HaoZeke*
- drop defensive AI-tell positioning prose - (045cbc1) - *HaoZeke*
- position readcon-core as definitive CON interchange - (cf7960b) - *HaoZeke*
- plain-text section titles (no literal backticks in sidebars) - (475ddae) - *HaoZeke*
- serve metadata schema at its $id URL - (10c56cf) - *HaoZeke*
- last markdown-bold leak in bindings ingest table - (89bdbc6) - *HaoZeke*
- fix org export (subscripts, TOC dumps, bold leaks, parity table, crate API link) - (1bfd4e1) - *HaoZeke*
- dedupe Ecosystem nav group and harden navbar logo theme swap - (5b7f8a0) - *HaoZeke*
- align design rationale with formal paper tone - (0715560) - *HaoZeke*
- field-wide best interchange thesis for CON and readcon-db - (0335d0a) - *HaoZeke*
- assert CON+hourglass as default optimizer interchange - (b2b2738) - *HaoZeke*
- ecosystem placement over checklist superiority claims - (44ad9e8) - *HaoZeke*
- reviewer-facing design rationale in architecture, evolution, FAQ - (47873fe) - *HaoZeke*
- optional cuda allocate/H2D in bindings and issue-status - (1f93fd3) - *HaoZeke*
- link readcon-db install and Pages from ecosystem nav - (fec39f9) - *HaoZeke*
- point ecosystem links at live readcon-db install - (fa40f17) - *HaoZeke*
- override theme pre{display:grid} for code fences - (61925a9) - *HaoZeke*
- setProperty important for inline code token spans - (e28a613) - *HaoZeke*
- force inline code token spans in page JS - (ba2ada2) - *HaoZeke*
- fix code fence whitespace (unwrap data-line + inline tokens) - (b7cba74) - *HaoZeke*
- unwrap Sphinx data-line spans for correct code whitespace - (b7e9b3a) - *HaoZeke*
#### Tests
- (**coverage**) push library line coverage to ≥90% - (cf6772e) - *HaoZeke*
- (**cuda**) gate allocate_non_cpu on not(feature=cuda) - (9500223) - *HaoZeke*
- (**docs**) run Org Babel tutorials in CI via tangle + execute - (45cfe3d) - *HaoZeke*
- (**docs**) ban deliberately-small hedging phrases - (23e0104) - *HaoZeke*
- (**python**) gate Diátaxis tutorials on CI pytest - (c8ced7b) - *HaoZeke*
#### CI
- (**bench**) criterion continue-on-error so ASV comment posts - (faa9a8e) - *HaoZeke*
- (**bench**) rebase before pushing refreshed Cachegrind numbers - (3251721) - *HaoZeke*
- (**coverage**) instrument Python/Julia/Fortran bindings for Codecov flags - (d84c739) - *HaoZeke*
- (**coverage**) raise library coverage via full features and FFI bulk tests - (b4c32c3) - *HaoZeke*
- (**coverage**) install emacs-nox for Python tutorial Babel tests - (8e51a8d) - *HaoZeke*
- (**coverage**) OIDC Codecov uploads for lode-org + Python venv - (a37128d) - *HaoZeke*
- (**coverage**) wire Codecov multi-flag uploads for rust/python/julia/fortran - (4cf1bb7) - *HaoZeke*
- (**docs**) retry Pages deploy once on transient API failure - (bda3557) - *HaoZeke*
#### Refactoring
- (**api**) drop coords-only load path; full frames only - (08a387e) - *HaoZeke*
#### Chores
- (**bench**) refresh Cachegrind I-refs for docs - (cda13ca) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (3879e4e) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (d924369) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (843b399) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (18dcbd6) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (905a310) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (9b779aa) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (25b30e8) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (dc52d66) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (fd84eb7) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (ced8ed1) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (cbe86e8) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (14df55d) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (9bffde8) - github-actions[bot]
- (**bench**) refresh Cachegrind I-refs for docs - (2f3b47a) - github-actions[bot]
- (**capi**) regenerate C header after DLPack device status additions - (22321bc) - *HaoZeke*
- (**fortran**) lock fpm package version to 0.14.0 - (8258776) - *HaoZeke*
- (**python**) drop unused frame_positions_pyarray helper - (b99522c) - *HaoZeke*
- add cxx-dist-verify workflow for cbindgen-free packaging - (b22c999) - *HaoZeke*
- remove median wall-clock measure from API tooling - (89abcea) - *HaoZeke*
#### Style
- (**docs**) flatten admonition double-line chrome - (2d3048a) - *HaoZeke*
- (**docs**) rtrash-style hero card and nav brand strip - (5af94e2) - *HaoZeke*
- (**docs**) use icon-only marks in the site nav bar - (5251a78) - *HaoZeke*
- (**docs**) fix ghost hero logo and tighten homepage lead - (33864bd) - *HaoZeke*
- (**docs**) kill double borders on admonitions, cards, code - (b9a6b3a) - *HaoZeke*
- (**docs**) regenerate benchmark SVGs from make_plots.py - (fd8e346) - *HaoZeke*
- (**readme**) re-export README.md anchors from readme_src.org - (5f58a7d) - *HaoZeke*

- - -

## v0.14.0 - 2026-06-28
#### Features
- (**core**) `index_proj` campaign screening projection (formula, finite scalars, sections mask) with C/Python/Fortran exposure
- (**ffi**) projection and writer-canonical C ABI surfaces for corpus alignment
#### Performance
- (**parser**) SoA-primary coordinate write + stack line floats; section SoA sync without redundant position rewrite
#### Bug Fixes
- (**parse**) iterator fills SoA velocities/forces after declared sections (`sync_arrays_from_atom_data`)
#### Tests
- SoA/AoS agreement, projection equality, chemfiles pytest gated on `has_chemfiles_support()`, integration force SoA asserts

- - -

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
