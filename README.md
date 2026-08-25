
# Table of Contents

1.  [About](#orgebfa45e)
    1.  [Features](#orge8fcd79)
    2.  [Migrate onto CON](#org14b0a24)
    3.  [Install](#orgec613e1)
    4.  [Tutorial](#org745ed6c)
    5.  [Design Decisions](#org66baa52)
        1.  [FFI Layer](#org4cf6a2a)
    6.  [Specification](#org55a9f19)
        1.  [CON format](#org60042df)
        2.  [convel format](#orgae4b5fb)
    7.  [Capabilities](#org1bbff09)
    8.  [Citation](#org7028075)
2.  [License](#org8b8a84b)


<a id="orgebfa45e"></a>

# About

`readcon-core` is the reference implementation of versioned `.con` / `.convel`.
Rare-event codes already checkpoint on CON. This library is the spec and
the hourglass API so the rest of the atomistic stack reads the same file:
optimizers, potential drivers, analysis tools, campaign stores, and ML
hand-off.

One frame is complete: cell, type-grouped coordinates, per-direction
fixed masks, column-5 `atom_id`, optional per-atom sections (velocities,
forces, energies, charges, spins, magmoms), and JSON metadata (spec
v2-v3, [docs/orgmode/spec.org](docs/orgmode/spec.org)).
Saddle, dimer, and NEB codes already depend on that payload.

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<tbody>
<tr>
<td class="org-left">Layer</td>
<td class="org-left">Role</td>
</tr>

<tr>
<td class="org-left">Spec + hot path</td>
<td class="org-left">Spec v3 parse/write, <code>validate</code>, units, <code>sections</code>, SoA, Cachegrind CI</td>
</tr>

<tr>
<td class="org-left">Hourglass ABI</td>
<td class="org-left">C / C++ / Python / Julia / Fortran (<code>rkr_*</code>): link CON into any language</td>
</tr>

<tr>
<td class="org-left">Device / ML hand-off</td>
<td class="org-left">DLPack (optional CUDA); optional metatensor <code>TensorBlock</code> without leaving CON authority</td>
</tr>

<tr>
<td class="org-left">Ingress</td>
<td class="org-left">Chemfiles import/selection: foreign structures <b>into</b> CON</td>
</tr>

<tr>
<td class="org-left">Campaigns</td>
<td class="org-left"><code>index_proj</code> + <a href="https://github.com/lode-org/readcon-db">readcon-db</a> (<code>cargo add</code> / <code>pip install</code>; <a href="https://lode-org.github.io/readcon-db/">docs</a> · <a href="https://docs.rs/readcon-db">docs.rs</a>)</td>
</tr>
</tbody>
</table>

Already on that path: rare-event clients, rgpot, rgpycrumbs, ASE adapters,
amsel, campaign stores, and anything that takes DLPack or metatensor blocks.

Rust rewrite of [readCon](https://github.com/HaoZeke/readCon). Chemfiles owns
format diversity at the edge; this crate owns CON fidelity on the wire and in
memory.

Measurements: Cachegrind I-refs (`examples/cachegrind_harness.rs`);
Python ASV + spyglass on PRs (`benchmarks/`); CON peers via
`benches/compare_readers.py` (and other scripts under `benches/`).
See [docs/orgmode/benchmarks.org](docs/orgmode/benchmarks.org).


<a id="orge8fcd79"></a>

## Features

-   **CON and convel:** Coordinates; optional sections declared in `sections`
    (velocities, forces, energies, charges, spins, magmoms). Velocities also
    auto-detect on legacy `.convel` without a `sections` key.
-   **Lazy iteration:** `ConFrameIterator`; `next_with_raw_span` keeps the on-disk blob for corpus ingest.
-   **Hot path:** [fast-float2](https://github.com/aldanor/fast-float-rust), [memmap2](https://docs.rs/memmap2), Cachegrind-tracked scenarios.
-   **Parallel frames:** Rayon behind the `parallel` Cargo feature.
-   **Bindings:** Python (PyO3), Julia (ccall), C (shipped header), C++ (RAII header), Fortran (fpm); hourglass ABI patterned on [metatensor](https://github.com/metatensor/metatensor).
-   **Metadata helpers:** Typed `energy`, `frame_index`, `time`, `timestep`, `neb_bead`, `neb_band` across bindings; raw JSON still available.
-   **Validation:** `validate=true` enforces finiteness, reserved keys, geometry, labels, symbols, section presence, identity columns.
-   **Fidelity:** `atom_id`, per-direction fixed masks, and declared optional sections round-trip through the core reader/writer.
-   **Campaigns:** Pair with [readcon-db](https://github.com/lode-org/readcon-db) (CON-text indexes, dedup, multi-reader; [docs](https://lode-org.github.io/readcon-db/) · [docs.rs](https://docs.rs/readcon-db)).
-   **RPC:** Cap'n Proto behind the `rpc` feature.


<a id="org14b0a24"></a>

## Migrate onto CON

Why switch: use a real frame API and multi-language library instead of
hand-rolling XYZ and a private atoms object.

-   **API:** parse/write, builders, metadata, validation, compression, lazy multi-frame iteration
-   **Payload:** constraints, `atom_id`, optional sections, versioned JSON on one frame
-   **Selection:** `select_atoms` / `rkr_frame_select` (`name H`, bonds/angles when topology is present)
-   **Languages:** hourglass `rkr_*` in Fortran / C / C++ / Python / Julia / Rust (same semantics when you add a language)
-   **Campaigns:** [readcon-db](https://github.com/lode-org/readcon-db) on CON text (energy / formula / sections, dedup, multi-reader; [docs](https://lode-org.github.io/readcon-db/) · [docs.rs](https://docs.rs/readcon-db))
-   **Plotting:** [chemparseplot](https://chemparseplot.rgoswami.me) (+ [rgpycrumbs](https://rgpycrumbs.rgoswami.me)) on the same files
-   **Measurements:** Cachegrind I-refs; PR ASV + spyglass; peer scripts in `benches/`. [benchmarks.org](docs/orgmode/benchmarks.org)

    # foreign → CON (needs --features chemfiles)
    cargo run --release --features chemfiles -- convert structure.xyz structure.con
    # Python (readcon-chemfiles or maturin --features python,chemfiles)
    # python -c "import readcon; readcon.convert_to_con('structure.xyz','structure.con')"

How-to: [docs/orgmode/migrate.org](docs/orgmode/migrate.org). Chemfiles path (CI-run):
[chemfiles-notebook](docs/orgmode/chemfiles-notebook.org). Campaigns:
[readcon-db docs](https://lode-org.github.io/readcon-db/) ·
[docs.rs/readcon-db](https://docs.rs/readcon-db). Plotting:
[chemparseplot](https://chemparseplot.rgoswami.me).


<a id="orgec613e1"></a>

## Install

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Language</th>
<th scope="col" class="org-left">Install</th>
<th scope="col" class="org-left">Destination</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Rust</td>
<td class="org-left"><code>cargo add readcon-core</code></td>
<td class="org-left"><a href="https://docs.rs/readcon-core">docs.rs</a></td>
</tr>

<tr>
<td class="org-left">Python</td>
<td class="org-left"><code>pip install readcon</code></td>
<td class="org-left"><a href="https://pypi.org/project/readcon/">PyPI</a></td>
</tr>

<tr>
<td class="org-left">Python + chemfiles</td>
<td class="org-left"><code>pip install readcon-chemfiles</code></td>
<td class="org-left"><a href="https://pypi.org/project/readcon-chemfiles/">PyPI</a></td>
</tr>

<tr>
<td class="org-left">Campaign store</td>
<td class="org-left"><code>cargo add readcon-db</code> / <code>pip install readcon-db</code></td>
<td class="org-left"><a href="https://lode-org.github.io/readcon-db/">docs</a> · <a href="https://docs.rs/readcon-db">docs.rs</a></td>
</tr>

<tr>
<td class="org-left">Julia</td>
<td class="org-left"><code>julia --project=julia/ReadCon -e 'using Pkg; Pkg.instantiate()'</code></td>
<td class="org-left"><a href="docs/orgmode/bindings.html">bindings</a></td>
</tr>

<tr>
<td class="org-left">C / C++ CMake</td>
<td class="org-left"><code>FetchContent</code> / <code>find_package(readcon-core)</code> (cxx tarball)</td>
<td class="org-left">headers + <code>libreadcon_core</code> + <code>readcon-core.pc</code></td>
</tr>

<tr>
<td class="org-left">C / C++ Meson</td>
<td class="org-left"><code>dependency('readcon-core')</code> (in-tree wrap-file)</td>
<td class="org-left">same</td>
</tr>

<tr>
<td class="org-left">C / C++ cargo-c</td>
<td class="org-left"><code>cargo cinstall --release --prefix /usr/local</code></td>
<td class="org-left">same</td>
</tr>
</tbody>
</table>

The C/C++ headers are **shipped** (`include/readcon-core.h`). cbindgen is a maintainer tool, not a consumer dependency. C99 (`readcon-core.h`) or C++17 (`readcon-core.hpp`) compiler. FetchContent URL: `readcon-core-cxx-$VERSION.tar.gz` on the GitHub Release.
Full matrix: [getting-started](docs/orgmode/getting-started.org).


<a id="org745ed6c"></a>

## Tutorial

Install, read a multi-frame fixture, inspect `atom_id`, write a
round-trip, build a frame with energy. Full steps:
[docs/orgmode/tutorial.org](docs/orgmode/tutorial.org) (or the published HTML `tutorial` page).

Short Python path from the repository root:

    import readcon

    for frame in readcon.iter_con("resources/test/tiny_multi_cuh2.con"):
        print(frame.cell, len(frame), frame.energy)

    frames = readcon.read_con("resources/test/tiny_multi_cuh2.con")
    readcon.write_con("out.con", frames)

    atoms = [readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546)]
    frame = readcon.ConFrame(cell=[10.0, 10.0, 10.0], angles=[90.0, 90.0, 90.0], atoms=atoms)
    frame.set_energy(-42.5)
    frame.write_con("built.con")

Rust smoke (same fixture):

    cargo run --example rust_usage -- resources/test/tiny_multi_cuh2.con

Other languages and task recipes: [docs/orgmode/howto.org](docs/orgmode/howto.org).
Conversion from XYZ/PDB/GRO: [chemfiles-tutorial](docs/orgmode/chemfiles-tutorial.org).


<a id="org66baa52"></a>

## Design Decisions

-   **Lazy parsing:** `ConFrameIterator` parses one frame at a time for large trajectories.
-   **Hourglass FFI:** shipped C header plus a hand-written C++ RAII wrapper, same pattern as [metatensor](https://github.com/metatensor/metatensor). CMake FetchContent, Meson wrap, and `readcon-core.pc` do not run cbindgen.


<a id="org4cf6a2a"></a>

### FFI Layer

Two exposure modes:

1.  **Opaque handles** (`RKRConFrame*`): client calls Rust accessors
    (`rkr_frame_get_header_line`, …). Hides layout; ABI can evolve behind the
    handle.
2.  **Transparent `#[repr(C)]` extract** (`rkr_frame_to_c_frame` → `CFrame`):
    client owns a flat atom table for hot loops and frees it with
    `free_c_frame`.


<a id="org55a9f19"></a>

## Specification

See [docs/orgmode/spec.org](docs/orgmode/spec.org) (or the [published HTML build](https://lode-org.github.io/readcon-core/spec.html)) for the full specification. A summary follows.


<a id="org60042df"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Optional spec-v2 `sections` and `validate` metadata for declared per-atom sections and strict validation
-   Multiple frames are concatenated directly with no separator


<a id="orgae4b5fb"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="org1bbff09"></a>

## Capabilities

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Area</th>
<th scope="col" class="org-left">Surface</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Payload</td>
<td class="org-left">Constraints, <code>atom_id</code>; optional velocities / forces / energies / charges / spins / magmoms; versioned JSON</td>
</tr>

<tr>
<td class="org-left">Languages</td>
<td class="org-left">One <code>rkr_*</code> surface for Fortran / C / C++ / Python / Julia</td>
</tr>

<tr>
<td class="org-left">Spec</td>
<td class="org-left">v2-v3, <code>validate=true</code>, declared sections (including optional physics blocks above), units (v3)</td>
</tr>

<tr>
<td class="org-left">Tensors</td>
<td class="org-left">DLPack; optional metatensor <code>TensorBlock</code></td>
</tr>

<tr>
<td class="org-left">Campaigns</td>
<td class="org-left"><code>index_proj</code> + <a href="https://github.com/lode-org/readcon-db">readcon-db</a> (<a href="https://lode-org.github.io/readcon-db/">docs</a> · <a href="https://docs.rs/readcon-db">docs.rs</a>)</td>
</tr>

<tr>
<td class="org-left">Import</td>
<td class="org-left">Optional chemfiles → CON</td>
</tr>

<tr>
<td class="org-left">Measurements</td>
<td class="org-left">Cachegrind I-refs; PR ASV + spyglass; <code>benches/compare_readers.py</code></td>
</tr>
</tbody>
</table>

Predecessor: [readCon](https://github.com/HaoZeke/readCon).


<a id="org7028075"></a>

## Citation

If you use `readcon-core` in academic work, please cite it via the metadata in [CITATION.cff](CITATION.cff). A Zenodo DOI is minted on a freeze tag and recorded in `CITATION.cff` identifiers; this tree does not invent one.


<a id="org8b8a84b"></a>

# License

MIT.
