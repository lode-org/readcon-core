
# Table of Contents

1.  [About](#org529f77c)
    1.  [Features](#org4fab142)
    2.  [Install](#org0d92a6e)
    3.  [Tutorial](#orgf07a6af)
    4.  [Design Decisions](#orgbd0dcb3)
        1.  [FFI Layer](#orgbb2e35b)
    5.  [Specification](#orga22dd8f)
        1.  [CON format](#org70817f7)
        2.  [convel format](#orga0fef18)
    6.  [Capabilities](#orgc49126b)
    7.  [Citation](#orgf448a08)
2.  [License](#org0af9947)


<a id="org529f77c"></a>

# About

`readcon-core` is the reference library for versioned `.con` / `.convel`: a
full atomic-configuration checkpoint for saddle, dimer, and NEB work and any
pipeline that needs the same fields on disk.

CON carries cell and angles, type-grouped coordinates, per-direction fixed
masks, column-5 `atom_id` (pre-group index), optional velocity / force /
energy sections, and versioned JSON on line 2. One hourglass C ABI (`rkr_*`)
gives Rust, C, C++, Python, Julia, and Fortran identical semantics so an
optimizer in Fortran and analysis in Python share one file. Multi-trajectory
campaigns use [readcon-db](https://github.com/lode-org/readcon-db)
(`cargo add readcon-db`, `pip install readcon-db`,
<https://lode-org.github.io/readcon-db/>); blobs stay CON text and always decode
through this crate. eOn, LODE, amsel, ASE adapters, and other CON-native tools
are consumers of that contract.

Rust rewrite of [readCon](https://github.com/HaoZeke/readCon).

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Layer</th>
<th scope="col" class="org-left">Crate</th>
<th scope="col" class="org-left">Owns</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Format I/O</td>
<td class="org-left"><code>readcon-core</code> / Python <code>readcon</code></td>
<td class="org-left">CON parse/write, spec v2–v3, hourglass FFI, optional chemfiles import</td>
</tr>

<tr>
<td class="org-left">Corpus</td>
<td class="org-left"><a href="https://github.com/lode-org/readcon-db">readcon-db</a></td>
<td class="org-left">LMDB indexes, dedup, multi-reader campaigns</td>
</tr>
</tbody>
</table>

Chemfiles owns format diversity at the edge; readcon-core owns CON fidelity
(`read_chemfiles*`). ASE `to_ase` / `from_ase` is calculator hand-off only.

Parse path: CI Cachegrind I-refs (`examples/cachegrind_harness.rs`); CON peers
via `benches/compare_readers.py`. Methodology:
[docs/orgmode/benchmarks.org](docs/orgmode/benchmarks.org). Spec:
[docs/orgmode/spec.org](docs/orgmode/spec.md).


<a id="org4fab142"></a>

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


<a id="org0d92a6e"></a>

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


<a id="orgf07a6af"></a>

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


<a id="orgbd0dcb3"></a>

## Design Decisions

-   **Lazy parsing:** `ConFrameIterator` parses one frame at a time for large trajectories.
-   **Hourglass FFI:** C header from cbindgen plus a hand-written C++ RAII wrapper, same pattern as [metatensor](https://github.com/metatensor/metatensor).


<a id="orgbb2e35b"></a>

### FFI Layer

Two exposure modes:

1.  **Opaque handles** (`RKRConFrame*`): client calls Rust accessors
    (`rkr_frame_get_header_line`, …). Hides layout; ABI can evolve behind the
    handle.
2.  **Transparent `#[repr(C)]` extract** (`rkr_frame_to_c_frame` → `CFrame`):
    client owns a flat atom table for hot loops and frees it with
    `free_c_frame`.


<a id="orga22dd8f"></a>

## Specification

See [docs/orgmode/spec.org](docs/orgmode/spec.md) (or the [published HTML build](https://lode-org.github.io/readcon-core/spec.html)) for the full specification. A summary follows.


<a id="org70817f7"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Optional spec-v2 `sections` and `validate` metadata for declared per-atom sections and strict validation
-   Multiple frames are concatenated directly with no separator


<a id="orga0fef18"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="orgc49126b"></a>

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
<td class="org-left">Velocities, forces, per-direction constraints, <code>atom_id</code>, versioned JSON on every binding</td>
</tr>

<tr>
<td class="org-left">Languages</td>
<td class="org-left">One <code>rkr_*</code> surface for Fortran / C / C++ / Python / Julia</td>
</tr>

<tr>
<td class="org-left">Spec</td>
<td class="org-left">v2–v3, <code>validate=true</code>, declared sections, typed metadata helpers</td>
</tr>

<tr>
<td class="org-left">Measurements</td>
<td class="org-left">Cachegrind I-refs; CON peers (<code>ase.io.eon</code>, eOn-style C sscanf)</td>
</tr>

<tr>
<td class="org-left">Campaigns</td>
<td class="org-left"><a href="https://github.com/lode-org/readcon-db">readcon-db</a> with CON text as durable identity</td>
</tr>

<tr>
<td class="org-left">Import</td>
<td class="org-left">Optional chemfiles → CON</td>
</tr>
</tbody>
</table>

Predecessor: [readCon](https://github.com/HaoZeke/readCon). ASE may use `ase.io.eon` or the optional adapters.


<a id="orgf448a08"></a>

## Citation

If you use `readcon-core` in academic work, please cite it via the metadata in [CITATION.cff](CITATION.cff). The Zenodo DOI tracks the latest release.


<a id="org0af9947"></a>

# License

MIT.

