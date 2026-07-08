
# Table of Contents

1.  [About](#org7e4819b)
    1.  [Features](#org8c593a0)
    2.  [Install](#orge691eaa)
    3.  [Tutorial](#org32aeca6)
    4.  [Design Decisions](#org83b45c7)
        1.  [FFI Layer](#orgab2415a)
    5.  [Specification](#org896c195)
        1.  [CON format](#org2c2a019)
        2.  [convel format](#org174fc5e)
    6.  [Why use this over readCon, ASE CON, or format-only tools?](#org6556315)
    7.  [Citation](#org51180b9)
2.  [License](#orgb4a6736)


<a id="org7e4819b"></a>

# About

`readcon-core` is the **definitive CON / convel interchange layer** for eOn,
LODE, and multi-language saddle / NEB pipelines: versioned on-disk fidelity
(constraints, forces, velocities, `atom_id`, JSON metadata), an hourglass
C ABI shared by Rust / C / C++ / Python / Julia / Fortran, optional chemfiles
ingress for XYZ/PDB/GRO → CON, and a companion campaign store that keeps CON
text authoritative.

It is a full Rust rewrite of [readCon](https://github.com/HaoZeke/readCon) (not a thin wrap). Scope is CON
interchange -- not "fastest I/O in all of computational chemistry," and not a
replacement for engine-native binary MD trajectories (XTC/TRR/DCD).

Ecosystem: this crate is the interchange and multi-language ABI. For
campaign-scale corpora (mmap LMDB, indexes on natoms / symbols / energy /
forces / velocities, xxHash3 dedup, multi-reader), use
[readcon-db](https://github.com/lode-org/readcon-db) (`cargo add readcon-db`, `pip install readcon-db`, docs at
<https://lode-org.github.io/readcon-db/>). Corpus blobs stay CON text and are
always decoded with `readcon-core` -- semantics never fork. Foreign formats enter
via the optional chemfiles feature (`read_chemfiles*`), not ASE. ASE
adapters are optional calculator hand-off only.

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
<th scope="col" class="org-left">Responsibility</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Interchange</td>
<td class="org-left"><code>readcon-core</code> / Python <code>readcon</code></td>
<td class="org-left">Parse/write CON &amp; convel, spec v2–v3 metadata, chemfiles ingress, hourglass C/Python/Julia/Fortran FFI</td>
</tr>

<tr>
<td class="org-left">Corpus</td>
<td class="org-left"><a href="https://github.com/lode-org/readcon-db">readcon-db</a> / <code>readcon_db</code></td>
<td class="org-left">Heed/LMDB store, secondary indexes, exact-match dedup, CLI + C/Python/Fortran</td>
</tr>
</tbody>
</table>

Speed (honest): product claims use in-repo harnesses only -- CI Cachegrind
I-refs on `examples/cachegrind_harness.rs` (commit-stable instruction counts)
and equal-geometry multi-frame runs from `benches/multiformat_traj.py` /
`benches/compare_readers.py` (committed under `benches/results/`). See
[docs/orgmode/benchmarks.org](docs/orgmode/benchmarks.org). We do not headline toy 4-atom atoms/s tables or
unmeasured us rankings.


<a id="org8c593a0"></a>

## Features

-   **CON and convel support:** Parses both coordinate-only and velocity-augmented files. Velocity sections are auto-detected without relying on file extensions.
-   **Lazy iteration:** `ConFrameIterator` parses one frame at a time for memory-efficient trajectory processing; `next_with_raw_span` preserves the on-disk blob for corpus ingest without re-serialization.
-   **Performance:** [fast-float2](https://github.com/aldanor/fast-float-rust) on the f64 hot path, [memmap2](https://docs.rs/memmap2) for large files, Cachegrind-tracked parse paths; equal-geometry harnesses vs ASE CON and C sscanf (see benchmarks).
-   **Parallel parsing:** Optional rayon-based parallel frame parsing behind the `parallel` feature gate.
-   **Language bindings:** Python (PyO3), Julia (ccall), C (cbindgen FFI), C++ (RAII header-only), and Fortran (fpm), following the hourglass design from [Metatensor](https://github.com/metatensor/metatensor).
-   **Spec-v2 metadata helpers:** Rust, Python, Julia, C, and C++ bindings all expose typed helpers for common JSON metadata keys like `energy`, `frame_index`, `time`, `timestep`, `neb_bead`, and `neb_band`, while still allowing raw JSON metadata when needed.
-   **Spec-v2 validation:** `validate=true` enforces finite numeric values, reserved metadata schema, physical header geometry, exact component labels, valid symbols, declared section presence, and matching per-atom identity columns.
-   **Force and constraint fidelity:** Writers preserve velocities, forces, original atom ids, and per-axis fixed masks across Rust, Python, Julia, C, and C++.
-   **Campaign corpora:** pair with [readcon-db](https://github.com/lode-org/readcon-db) for indexed multi-trajectory stores (CON text authoritative).
-   **RPC serving:** Optional Cap'n Proto RPC interface (`rpc` feature) for network-accessible parsing.


<a id="orge691eaa"></a>

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


<a id="org32aeca6"></a>

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


<a id="org83b45c7"></a>

## Design Decisions

The library is designed with the following principles in mind:

-   **Lazy Parsing:** The `ConFrameIterator` allows for lazy parsing of frames, which can be more memory-efficient when dealing with large trajectory files.

-   **Interoperability:** The FFI layer makes the core parsing logic accessible from other programming languages, increasing the library's utility. Currently, a `C` header is auto-generated along with a hand-crafted `C++` interface, following the hourglass design from [Metatensor](https://github.com/metatensor/metatensor).


<a id="orgab2415a"></a>

### FFI Layer

A key challenge in designing an FFI is deciding how data is exposed to the C-compatible world. This library uses a hybrid approach to offer both safety and convenience:

1.  **Opaque Pointers (The Handle Pattern):** The primary way to interact with
    frame data is through an opaque pointer, represented as `RKRConFrame*` in C.
    The C/C++ client holds this "handle" but cannot inspect its contents
    directly. Instead, it must call Rust functions to interact with the data
    (e.g., `rkr_frame_get_header_line(frame_handle, ...)`). This is the safest
    and most flexible pattern, as it completely hides Rust's internal data
    structures and memory layout, preventing ABI breakage if the Rust code is
    updated.

2.  **Transparent `#[repr(C)]` Structs (The Data Extraction Pattern):** For
    convenience and performance in cases where only the core atomic data is
    needed, the library provides a function (`rkr_frame_to_c_frame`) to extract a
    "lossy" but transparent `CFrame` struct from an opaque handle. The C/C++
    client can directly read the fields of this struct (e.g.,
    `my_c_frame->num_atoms`). The client takes ownership of this extracted struct
    and is responsible for freeing its memory.

This hybrid model provides the best of both worlds: the safety and
forward-compatibility of opaque handles for general use, and the performance of
direct data access for the most common computational tasks.


<a id="org896c195"></a>

## Specification

See [docs/orgmode/spec.org](docs/orgmode/spec.md) (or the [published HTML build](https://lode-org.github.io/readcon-core/spec.html)) for the full specification. A summary follows.


<a id="org2c2a019"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Optional spec-v2 `sections` and `validate` metadata for declared per-atom sections and strict validation
-   Multiple frames are concatenated directly with no separator


<a id="org174fc5e"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="org6556315"></a>

## Why use this over [readCon](https://github.com/HaoZeke/readCon), ASE CON, or format-only tools?

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Differentiator</th>
<th scope="col" class="org-left">What you get</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Lossless CON round-trip</td>
<td class="org-left">Velocities, forces, per-axis constraints, <code>atom_id</code>, and versioned JSON metadata survive read→write across every supported language</td>
</tr>

<tr>
<td class="org-left">Hourglass multi-language ABI</td>
<td class="org-left">One <code>rkr_*</code> C surface; Fortran / C / C++ / Python / Julia share semantics without embedding a Python interpreter on the I/O path</td>
</tr>

<tr>
<td class="org-left">Measured parse path</td>
<td class="org-left">Equal-geometry harnesses vs ASE CON and C sscanf; CI Cachegrind I-refs for regression—not marketing-only Criterion tables</td>
</tr>

<tr>
<td class="org-left">Spec validation</td>
<td class="org-left"><code>validate=true</code> rejects non-finite numbers, bad geometry, and mismatched section identity columns</td>
</tr>

<tr>
<td class="org-left">Optional chemfiles ingress</td>
<td class="org-left">XYZ / PDB / GRO → <code>ConFrame</code> / CON without inventing a second CON dialect</td>
</tr>

<tr>
<td class="org-left">Campaign companion</td>
<td class="org-left"><a href="https://github.com/lode-org/readcon-db">readcon-db</a> indexes multi-trajectory corpora while CON text remains the durable identity</td>
</tr>
</tbody>
</table>

Legacy readCon lacks the modern bindings matrix, spec-v2 validation, chemfiles
ingress, and Cachegrind discipline. ASE `ase.io.eon` is fine for calculator
hand-off but is not the multi-language interchange contract. Format-only tools
(generic XYZ / chemfiles alone) do not own CON section fidelity or the
hourglass ABI.


<a id="org51180b9"></a>

## Citation

If you use `readcon-core` in academic work, please cite it via the metadata in [CITATION.cff](CITATION.cff). The Zenodo DOI tracks the latest release.


<a id="orgb4a6736"></a>

# License

MIT.

