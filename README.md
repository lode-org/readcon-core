
# Table of Contents

1.  [About](#orgd736c59)
    1.  [Features](#orge3cd48e)
    2.  [Install](#org7b46c89)
    3.  [Tutorial](#orgaacb7fe)
    4.  [Design Decisions](#org64af52a)
        1.  [FFI Layer](#org057a19f)
    5.  [Specification](#org4cf5d3e)
        1.  [CON format](#org4dd0873)
        2.  [convel format](#orgd466ec6)
    6.  [Capabilities](#org436dcbf)
    7.  [Citation](#org406ce81)
2.  [License](#orgc7db735)


<a id="orgd736c59"></a>

# About

`readcon-core` is the reference implementation of versioned `.con` / `.convel`:
a human-readable atomic configuration format with cell, type-grouped
coordinates, per-direction constraints, stable `atom_id`, optional velocity /
force / energy sections, and JSON metadata (spec v2–v3, see
[docs/orgmode/spec.org](docs/orgmode/spec.md)).

What CON carries is what multi-code rare-event and transition-state pipelines
need on disk: frozen axes for constrained searches, identity through
type-grouping for NEB and dimer modes, forces and energies on the same frame,
and one ABI so Fortran optimizers and Python analysis share a file.

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Layer</th>
<th scope="col" class="org-left">What ships in this repo</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Spec + hot path</td>
<td class="org-left">Spec v3 parse/write, <code>validate</code>, units, <code>sections</code>, SoA storage, Cachegrind CI</td>
</tr>

<tr>
<td class="org-left">Hourglass ABI</td>
<td class="org-left">C (<code>cbindgen</code>), C++ RAII, Python (PyO3), Julia, Fortran (fpm); one <code>rkr_*</code> surface</td>
</tr>

<tr>
<td class="org-left">Device / ML hand-off</td>
<td class="org-left">DLPack export (dlpk SoA; optional CUDA); optional metatensor <code>TensorBlock</code></td>
</tr>

<tr>
<td class="org-left">Ingress</td>
<td class="org-left">Optional chemfiles import/selection into <code>ConFrame</code></td>
</tr>

<tr>
<td class="org-left">Campaigns</td>
<td class="org-left"><code>index_proj</code> screening for <a href="https://github.com/lode-org/readcon-db">readcon-db</a> (<code>cargo add readcon-db</code>, <code>pip install readcon-db</code>)</td>
</tr>
</tbody>
</table>

Consumers of that surface include rare-event clients (eOn lineage and other
saddle stacks), potential drivers (rgpot), analysis (rgpycrumbs), ASE
calculators (`to_ase` / `from_ase`), campaign stores, and ML pipelines that take
DLPack or metatensor blocks.

Rust rewrite of [readCon](https://github.com/HaoZeke/readCon). Chemfiles owns
format diversity at the edge; this crate owns CON fidelity.

Measurements: CI Cachegrind (`examples/cachegrind_harness.rs`);
`benches/compare_readers.py`. See
[docs/orgmode/benchmarks.org](docs/orgmode/benchmarks.org).


<a id="orge3cd48e"></a>

## Features

-   **CON and convel:** Coordinates; velocities auto-detected or declared in `sections`.
-   **Lazy iteration:** `ConFrameIterator`; `next_with_raw_span` keeps the on-disk blob for corpus ingest.
-   **Hot path:** [fast-float2](https://github.com/aldanor/fast-float-rust), [memmap2](https://docs.rs/memmap2), Cachegrind-tracked scenarios.
-   **Parallel frames:** Rayon behind the `parallel` Cargo feature.
-   **Bindings:** Python (PyO3), Julia (ccall), C (cbindgen), C++ (RAII header), Fortran (fpm); hourglass ABI patterned on [metatensor](https://github.com/metatensor/metatensor).
-   **Metadata helpers:** Typed `energy`, `frame_index`, `time`, `timestep`, `neb_bead`, `neb_band` across bindings; raw JSON still available.
-   **Validation:** `validate=true` enforces finiteness, reserved keys, geometry, labels, symbols, section presence, identity columns.
-   **Fidelity:** Velocities, forces, `atom_id`, per-direction fixed masks round-trip on every binding.
-   **Campaigns:** Pair with [readcon-db](https://github.com/lode-org/readcon-db).
-   **RPC:** Cap'n Proto behind the `rpc` feature.


<a id="org7b46c89"></a>

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


<a id="orgaacb7fe"></a>

## Tutorial

A copy-pasteable walkthrough that parses a multi-frame trajectory, inspects metadata, builds a new frame, and writes it back. Run it as-is.

    cargo run --example rust_usage -- resources/test/tiny_multi_cuh2.con

The example above iterates lazily over every frame, prints atom counts plus the per-frame energy if present, and exits. Equivalent flows in the other bindings:

    import readcon
    
    # Read every frame; the iterator yields PyConFrame objects
    for frame in readcon.iter_frames("resources/test/tiny_multi_cuh2.con"):
        print(frame.natms_per_type, frame.energy())  # energy() is None when absent
    
    # Build and write a new frame
    b = readcon.ConFrameBuilder(cell=[10.0, 10.0, 10.0], angles=[90.0, 90.0, 90.0])
    b.set_energy(-42.5).add_atom("Cu", 0.0, 0.0, 0.0, 1, 63.546)
    b.write("out.con")

    using ReadCon
    for frame in iter_frames("resources/test/tiny_multi_cuh2.con")
        println(frame.natms_per_type, " ", energy(frame))
    end

    #include <readcon-core.hpp>
    #include <iostream>
    
    int main() {
        readcon::ConFrameIterator it("resources/test/tiny_multi_cuh2.con");
        for (const auto &frame : it) {
            std::cout << frame.atoms().size() << " atoms";
            if (auto e = frame.energy_opt()) std::cout << " E=" << *e;
            std::cout << "\n";
        }
    }

    #include <readcon-core.h>
    #include <stdio.h>
    
    int main(void) {
        uintptr_t n = 0;
        RKRConFrame **frames = rkr_read_all_frames("resources/test/tiny_multi_cuh2.con", &n);
        for (uintptr_t i = 0; i < n; ++i) {
            printf("frame %zu energy=%f\n", i, rkr_frame_energy(frames[i]));
        }
        free_rkr_frame_array(frames, n);
    }


<a id="org64af52a"></a>

## Design Decisions

-   **Lazy parsing:** `ConFrameIterator` parses one frame at a time for large trajectories.
-   **Hourglass FFI:** C header from cbindgen plus a hand-written C++ RAII wrapper, same pattern as [metatensor](https://github.com/metatensor/metatensor).


<a id="org057a19f"></a>

### FFI Layer

Two exposure modes:

1.  **Opaque handles** (`RKRConFrame*`): client calls Rust accessors
    (`rkr_frame_get_header_line`, …). Hides layout; ABI can evolve behind the
    handle.
2.  **Transparent `#[repr(C)]` extract** (`rkr_frame_to_c_frame` → `CFrame`):
    client owns a flat atom table for hot loops and frees it with
    `free_c_frame`.


<a id="org4cf5d3e"></a>

## Specification

See [docs/orgmode/spec.org](docs/orgmode/spec.md) (or the [published HTML build](https://lode-org.github.io/readcon-core/spec.html)) for the full specification. A summary follows.


<a id="org4dd0873"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Optional spec-v2 `sections` and `validate` metadata for declared per-atom sections and strict validation
-   Multiple frames are concatenated directly with no separator


<a id="orgd466ec6"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="org436dcbf"></a>

## Capabilities

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Area</th>
<th scope="col" class="org-left">What ships</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Payload</td>
<td class="org-left">Velocities, forces, per-direction constraints, <code>atom_id</code>, versioned JSON</td>
</tr>

<tr>
<td class="org-left">Languages</td>
<td class="org-left">One <code>rkr_*</code> surface for Fortran / C / C++ / Python / Julia</td>
</tr>

<tr>
<td class="org-left">Spec</td>
<td class="org-left">v2–v3, <code>validate=true</code>, declared sections, units (v3)</td>
</tr>

<tr>
<td class="org-left">Tensors</td>
<td class="org-left">DLPack; optional metatensor <code>TensorBlock</code></td>
</tr>

<tr>
<td class="org-left">Campaigns</td>
<td class="org-left"><code>index_proj</code> + <a href="https://github.com/lode-org/readcon-db">readcon-db</a></td>
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


<a id="org406ce81"></a>

## Citation

If you use `readcon-core` in academic work, please cite it via the metadata in [CITATION.cff](CITATION.cff). The Zenodo DOI tracks the latest release.


<a id="orgc7db735"></a>

# License

MIT.

