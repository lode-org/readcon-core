
# Table of Contents

1.  [About](#orgbb292cb)
    1.  [Features](#org5f6d579)
    2.  [Migrate onto CON](#org0592f29)
    3.  [Install](#org02c1b03)
    4.  [Tutorial](#orgb356555)
    5.  [Design Decisions](#orgf115142)
        1.  [FFI Layer](#orgf901853)
    6.  [Specification](#org99c62f5)
        1.  [CON format](#orge4c909f)
        2.  [convel format](#org6d70547)
    7.  [Capabilities](#org200c27b)
    8.  [Citation](#orga644828)
2.  [License](#org06f9b3b)


<a id="orgbb292cb"></a>

# About

`readcon-core` is the reference implementation of versioned `.con` / `.convel`.
This stack **puts CON everywhere**: every optimizer, potential driver, analysis
tool, campaign store, and ML hand-off that needs a durable atomic configuration
with constraints, forces, and identity.

CON is human-readable and complete on one frame: cell, type-grouped
coordinates, per-direction fixed masks, column-5 `atom_id`, optional per-atom
sections (velocities, forces, energies, charges, spins, magmoms), and JSON
metadata (spec v2–v3, [docs/orgmode/spec.org](docs/orgmode/spec.org)).
That payload is why saddle, dimer, and NEB codes already work on CON; the
library exists so the rest of the atomistic stack adopts the same file.

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Layer</th>
<th scope="col" class="org-left">Role in spreading CON</th>
</tr>
</thead>
<tbody>
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
<td class="org-left"><code>index_proj</code> + <a href="https://github.com/lode-org/readcon-db">readcon-db</a> (<code>cargo add readcon-db</code>, <code>pip install readcon-db</code>): corpora still CON text</td>
</tr>
</tbody>
</table>

Already on that path: rare-event clients, rgpot, rgpycrumbs, ASE adapters,
amsel, campaign stores, and anything that takes DLPack or metatensor blocks.

Rust rewrite of [readCon](https://github.com/HaoZeke/readCon). Chemfiles owns
format diversity at the edge; this crate owns CON fidelity on the wire and in
memory.

Measurements: CI Cachegrind (`examples/cachegrind_harness.rs`);
`benches/compare_readers.py`. See
[docs/orgmode/benchmarks.org](docs/orgmode/benchmarks.org).


<a id="org5f6d579"></a>

## Features

-   **CON and convel:** Coordinates; optional sections declared in `sections`
    (velocities, forces, energies, charges, spins, magmoms). Velocities also
    auto-detect on legacy `.convel` without a `sections` key.
-   **Lazy iteration:** `ConFrameIterator`; `next_with_raw_span` keeps the on-disk blob for corpus ingest.
-   **Hot path:** [fast-float2](https://github.com/aldanor/fast-float-rust), [memmap2](https://docs.rs/memmap2), Cachegrind-tracked scenarios.
-   **Parallel frames:** Rayon behind the `parallel` Cargo feature.
-   **Bindings:** Python (PyO3), Julia (ccall), C (cbindgen), C++ (RAII header), Fortran (fpm); hourglass ABI patterned on [metatensor](https://github.com/metatensor/metatensor).
-   **Metadata helpers:** Typed `energy`, `frame_index`, `time`, `timestep`, `neb_bead`, `neb_band` across bindings; raw JSON still available.
-   **Validation:** `validate=true` enforces finiteness, reserved keys, geometry, labels, symbols, section presence, identity columns.
-   **Fidelity:** `atom_id`, per-direction fixed masks, and declared optional sections round-trip through the core reader/writer.
-   **Campaigns:** Pair with [readcon-db](https://github.com/lode-org/readcon-db) (CON-text indexes, dedup, multi-reader).
-   **RPC:** Cap'n Proto behind the `rpc` feature.


<a id="org0592f29"></a>

## Migrate onto CON

Why switch:

-   **Payload:** constraints, `atom_id`, optional sections, versioned JSON on one frame
-   **Languages:** hourglass `rkr_*` in Fortran / C / C++ / Python / Julia / Rust
-   **Selection:** `select_atoms` / `rkr_frame_select` on CON (`name H`, bonds/angles when topology is present)
-   **Campaigns:** [readcon-db](https://github.com/lode-org/readcon-db) indexes CON text (energy / formula / sections, dedup, multi-reader)
-   **Plotting:** [chemparseplot](https://chemparseplot.rgoswami.me) (+ [rgpycrumbs](https://rgpycrumbs.rgoswami.me)) on CON checkpoints / paths — not a per-code export

    # foreign → CON (needs --features chemfiles)
    cargo run --release --features chemfiles -- convert structure.xyz structure.con
    # Python (readcon-chemfiles or maturin --features python,chemfiles)
    # python -c "import readcon; readcon.convert_to_con('structure.xyz','structure.con')"

How-to: [docs/orgmode/migrate.org](docs/orgmode/migrate.org). Chemfiles path (CI-run):
[chemfiles-notebook](docs/orgmode/chemfiles-notebook.org). Campaigns:
[readcon-db docs](https://lode-org.github.io/readcon-db/). Plotting:
[chemparseplot](https://chemparseplot.rgoswami.me).


<a id="org02c1b03"></a>

## Install

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Language</th>
<th scope="col" class="org-left">Install command</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Rust</td>
<td class="org-left"><code>cargo add readcon-core</code></td>
</tr>

<tr>
<td class="org-left">Python</td>
<td class="org-left"><code>pip install readcon</code></td>
</tr>

<tr>
<td class="org-left">Julia</td>
<td class="org-left"><code>julia --project=julia/ReadCon -e 'using Pkg; Pkg.instantiate()'</code></td>
</tr>

<tr>
<td class="org-left">C / C++ system</td>
<td class="org-left"><code>cargo cinstall --release --prefix /usr/local</code> (installs <code>libreadcon_core.{so,a}</code>, <code>readcon-core.h</code>, <code>readcon-core.hpp</code>, and a pkg-config file)</td>
</tr>

<tr>
<td class="org-left">C / C++ via meson subproject</td>
<td class="org-left">drop the repository under <code>subprojects/readcon-core/</code> and link against the <code>readcon_core_dep</code> dependency</td>
</tr>
</tbody>
</table>

The C/C++ headers require a C99 (`readcon-core.h`) or C++17 (`readcon-core.hpp`, for `std::optional` and `std::filesystem`) compiler.


<a id="orgb356555"></a>

## Tutorial

One Good Tutorial (Diátaxis): install, read a multi-frame fixture, inspect
`atom_id`, write a round-trip, build a frame with energy. Full steps:
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


<a id="orgf115142"></a>

## Design Decisions

-   **Lazy parsing:** `ConFrameIterator` parses one frame at a time for large trajectories.
-   **Hourglass FFI:** C header from cbindgen plus a hand-written C++ RAII wrapper, same pattern as [metatensor](https://github.com/metatensor/metatensor).


<a id="orgf901853"></a>

### FFI Layer

Two exposure modes:

1.  **Opaque handles** (`RKRConFrame*`): client calls Rust accessors
    (`rkr_frame_get_header_line`, …). Hides layout; ABI can evolve behind the
    handle.
2.  **Transparent `#[repr(C)]` extract** (`rkr_frame_to_c_frame` → `CFrame`):
    client owns a flat atom table for hot loops and frees it with
    `free_c_frame`.


<a id="org99c62f5"></a>

## Specification

See [docs/orgmode/spec.org](docs/orgmode/spec.org) (or the [published HTML build](https://lode-org.github.io/readcon-core/spec.html)) for the full specification. A summary follows.


<a id="orge4c909f"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Optional spec-v2 `sections` and `validate` metadata for declared per-atom sections and strict validation
-   Multiple frames are concatenated directly with no separator


<a id="org6d70547"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="org200c27b"></a>

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
<td class="org-left">v2–v3, <code>validate=true</code>, declared sections (including optional physics blocks above), units (v3)</td>
</tr>

<tr>
<td class="org-left">Tensors</td>
<td class="org-left">DLPack; optional metatensor <code>TensorBlock</code></td>
</tr>

<tr>
<td class="org-left">Campaigns</td>
<td class="org-left"><code>index_proj</code> + <a href="https://github.com/lode-org/readcon-db">readcon-db</a> (energy/formula/sections indexes, dedup)</td>
</tr>

<tr>
<td class="org-left">Import</td>
<td class="org-left">Optional chemfiles → CON</td>
</tr>

<tr>
<td class="org-left">Measurements</td>
<td class="org-left">Cachegrind I-refs; CON peers (<code>ase.io.eon</code>, eOn-style C sscanf)</td>
</tr>
</tbody>
</table>

Predecessor: [readCon](https://github.com/HaoZeke/readCon).


<a id="orga644828"></a>

## Citation

If you use `readcon-core` in academic work, please cite it via the metadata in [CITATION.cff](CITATION.cff). The Zenodo DOI tracks the latest release.


<a id="org06f9b3b"></a>

# License

MIT.

