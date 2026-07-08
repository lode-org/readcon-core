
# Table of Contents

1.  [About](#orgb2f4773)
    1.  [Features](#orgbdedcad)
    2.  [Install](#orgc709ba8)
    3.  [Tutorial](#orga81d341)
    4.  [Design Decisions](#org4cd74c9)
        1.  [FFI Layer](#org06cfdd3)
    5.  [Specification](#org0a92def)
        1.  [CON format](#org500121e)
        2.  [convel format](#org533d96c)
    6.  [Capabilities](#orga1264fd)
    7.  [Citation](#org6a688da)
2.  [License](#org444deed)


<a id="orgb2f4773"></a>

# About

`readcon-core` is the reference implementation of versioned `.con` / `.convel`.
This stack **puts CON everywhere**: every optimizer, potential driver, analysis
tool, campaign store, and ML hand-off that needs a durable atomic configuration
with constraints, forces, and identity.

CON is human-readable and complete on one frame: cell, type-grouped
coordinates, per-direction fixed masks, column-5 `atom_id`, optional per-atom
sections (velocities, forces, energies, charges, spins, magmoms), and JSON
metadata (spec v2–v3, [docs/orgmode/spec.org](docs/orgmode/spec.md)).
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
[docs/orgmode/benchmarks.org](docs/orgmode/benchmarks.md).


<a id="orgbdedcad"></a>

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
-   **Campaigns:** Pair with [readcon-db](https://github.com/lode-org/readcon-db).
-   **RPC:** Cap'n Proto behind the `rpc` feature.


<a id="orgc709ba8"></a>

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


<a id="orga81d341"></a>

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


<a id="org4cd74c9"></a>

## Design Decisions

-   **Lazy parsing:** `ConFrameIterator` parses one frame at a time for large trajectories.
-   **Hourglass FFI:** C header from cbindgen plus a hand-written C++ RAII wrapper, same pattern as [metatensor](https://github.com/metatensor/metatensor).


<a id="org06cfdd3"></a>

### FFI Layer

Two exposure modes:

1.  **Opaque handles** (`RKRConFrame*`): client calls Rust accessors
    (`rkr_frame_get_header_line`, …). Hides layout; ABI can evolve behind the
    handle.
2.  **Transparent `#[repr(C)]` extract** (`rkr_frame_to_c_frame` → `CFrame`):
    client owns a flat atom table for hot loops and frees it with
    `free_c_frame`.


<a id="org0a92def"></a>

## Specification

See [docs/orgmode/spec.org](docs/orgmode/spec.md) (or the [published HTML build](https://lode-org.github.io/readcon-core/spec.html)) for the full specification. A summary follows.


<a id="org500121e"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Optional spec-v2 `sections` and `validate` metadata for declared per-atom sections and strict validation
-   Multiple frames are concatenated directly with no separator


<a id="org533d96c"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="orga1264fd"></a>

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


<a id="org6a688da"></a>

## Citation

If you use `readcon-core` in academic work, please cite it via the metadata in [CITATION.cff](CITATION.cff). The Zenodo DOI tracks the latest release.


<a id="org444deed"></a>

# License

MIT.

