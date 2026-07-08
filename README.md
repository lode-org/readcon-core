
# Table of Contents

1.  [About](#org3d3b0cc)
    1.  [Features](#orgd22c762)
    2.  [Install](#orga3d8379)
    3.  [Tutorial](#org85f4df2)
    4.  [Design Decisions](#org1b83265)
        1.  [FFI Layer](#org848bd14)
    5.  [Specification](#orgc360ac4)
        1.  [CON format](#org5ff5d1d)
        2.  [convel format](#orgb460d47)
    6.  [Why use this over readCon, ASE CON, or format-only tools?](#org218eb3b)
    7.  [Citation](#org969494b)
2.  [License](#orgecf5a2f)


<a id="org3d3b0cc"></a>

# About

`readcon-core` reads and writes versioned `.con` / `.convel` for eOn, LODE, and
multi-language saddle / NEB pipelines. Constraints, forces, velocities,
`atom_id`, and JSON metadata round-trip. One hourglass C ABI covers Rust, C,
C++, Python, Julia, and Fortran. Optional chemfiles maps XYZ / PDB / GRO into
CON. Campaign corpora live in [readcon-db](https://github.com/lode-org/readcon-db) with CON text as the durable identity
(`cargo add readcon-db`, `pip install readcon-db`,
<https://lode-org.github.io/readcon-db/>).

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
<th scope="col" class="org-left">Responsibility</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Interchange</td>
<td class="org-left"><code>readcon-core</code> / Python <code>readcon</code></td>
<td class="org-left">CON / convel parse and write, spec v2–v3 metadata, chemfiles ingress, hourglass FFI</td>
</tr>

<tr>
<td class="org-left">Corpus</td>
<td class="org-left"><a href="https://github.com/lode-org/readcon-db">readcon-db</a> / <code>readcon_db</code></td>
<td class="org-left">Heed/LMDB store, secondary indexes, exact-match dedup, CLI + C/Python/Fortran</td>
</tr>
</tbody>
</table>

Foreign formats enter through chemfiles (`read_chemfiles*`). ASE adapters
(`to_ase` / `from_ase`) support calculator hand-off only.

Parse speed: CI Cachegrind I-refs on `examples/cachegrind_harness.rs`; peer
ordering via `benches/multiformat_traj.py` and `benches/compare_readers.py`
(artifacts under `benches/results/`). Methodology:
[docs/orgmode/benchmarks.org](docs/orgmode/benchmarks.org).


<a id="orgd22c762"></a>

## Features

-   **CON and convel support:** Parses both coordinate-only and velocity-augmented files. Velocity sections are auto-detected without relying on file extensions.
-   **Lazy iteration:** `ConFrameIterator` parses one frame at a time for memory-efficient trajectory processing; `next_with_raw_span` preserves the on-disk blob for corpus ingest without re-serialization.
-   **Performance:** [fast-float2](https://github.com/aldanor/fast-float-rust) on the f64 hot path, [memmap2](https://docs.rs/memmap2) for large files, Cachegrind I-refs in CI; equal-geometry peer runs vs ASE CON and C sscanf (see benchmarks).
-   **Parallel parsing:** Optional rayon-based parallel frame parsing behind the `parallel` Cargo feature.
-   **Language bindings:** Python (PyO3), Julia (ccall), C (cbindgen FFI), C++ (RAII header-only), and Fortran (fpm), using the hourglass ABI pattern from [metatensor](https://github.com/metatensor/metatensor).
-   **Spec-v2 metadata helpers:** Rust, Python, Julia, C, and C++ bindings all expose typed helpers for common JSON metadata keys like `energy`, `frame_index`, `time`, `timestep`, `neb_bead`, and `neb_band`, while still allowing raw JSON metadata when needed.
-   **Spec-v2 validation:** `validate=true` enforces finite numeric values, reserved metadata schema, physical header geometry, exact component labels, valid symbols, declared section presence, and matching per-atom identity columns.
-   **Force and constraint fidelity:** Writers preserve velocities, forces, original atom ids, and per-direction fixed masks across Rust, Python, Julia, C, and C++.
-   **Campaign corpora:** pair with [readcon-db](https://github.com/lode-org/readcon-db) for indexed multi-trajectory stores (CON text authoritative).
-   **RPC serving:** Optional Cap'n Proto RPC interface (`rpc` feature) for network-accessible parsing.


<a id="orga3d8379"></a>

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


<a id="org85f4df2"></a>

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


<a id="org1b83265"></a>

## Design Decisions

The library is designed with the following principles in mind:

-   **Lazy Parsing:** The `ConFrameIterator` allows for lazy parsing of frames, which can be more memory-efficient when dealing with large trajectory files.

-   **Interoperability:** The FFI layer exposes the core parser to other languages. A `C` header is auto-generated with a hand-crafted `C++` interface, using the hourglass ABI pattern from [metatensor](https://github.com/metatensor/metatensor).


<a id="org848bd14"></a>

### FFI Layer

FFI data exposure uses a hybrid of safety and convenience:

1.  **Opaque Pointers (The Handle Pattern):** The primary way to interact with
    frame data is through an opaque pointer, represented as `RKRConFrame*` in C.
    The C/C++ client keeps this "handle" but cannot inspect its contents
    directly. Instead, it must call Rust functions to interact with the data
    (e.g., `rkr_frame_get_header_line(frame_handle, ...)`). This pattern hides
    Rust's internal data structures and memory layout, preventing ABI breakage
    if the Rust code is updated.

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


<a id="orgc360ac4"></a>

## Specification

See [docs/orgmode/spec.org](docs/orgmode/spec.md) (or the [published HTML build](https://lode-org.github.io/readcon-core/spec.html)) for the full specification. A summary follows.


<a id="org5ff5d1d"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Optional spec-v2 `sections` and `validate` metadata for declared per-atom sections and strict validation
-   Multiple frames are concatenated directly with no separator


<a id="orgb460d47"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="org218eb3b"></a>

## Why use this over [readCon](https://github.com/HaoZeke/readCon), ASE CON, or format-only tools?

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<thead>
<tr>
<th scope="col" class="org-left">Capability</th>
<th scope="col" class="org-left">readcon-core</th>
</tr>
</thead>
<tbody>
<tr>
<td class="org-left">Round-trip</td>
<td class="org-left">Velocities, forces, per-direction constraints, <code>atom_id</code>, versioned JSON metadata across every binding</td>
</tr>

<tr>
<td class="org-left">Languages</td>
<td class="org-left">One <code>rkr_*</code> C surface for Fortran / C / C++ / Python / Julia (no Python on the optimizer I/O path)</td>
</tr>

<tr>
<td class="org-left">Parse checks</td>
<td class="org-left">Equal-geometry peer runs vs ASE CON and C sscanf; CI Cachegrind I-refs</td>
</tr>

<tr>
<td class="org-left">Validation</td>
<td class="org-left"><code>validate=true</code> rejects non-finite numbers, bad geometry, mismatched section identity</td>
</tr>

<tr>
<td class="org-left">Ingress</td>
<td class="org-left">XYZ / PDB / GRO → <code>ConFrame</code> / CON via optional chemfiles</td>
</tr>

<tr>
<td class="org-left">Campaigns</td>
<td class="org-left"><a href="https://github.com/lode-org/readcon-db">readcon-db</a> indexes multi-trajectory corpora; CON text stays the durable identity</td>
</tr>
</tbody>
</table>

Compared with legacy readCon: multi-language bindings, spec-v2 validation,
chemfiles ingress, and Cachegrind regression tracking. Compared with ASE
`ase.io.eon`: shared CON contract for optimizers outside Python. Compared with
XYZ or chemfiles alone: CON section fidelity on the wire.


<a id="org969494b"></a>

## Citation

If you use `readcon-core` in academic work, please cite it via the metadata in [CITATION.cff](CITATION.cff). The Zenodo DOI tracks the latest release.


<a id="orgecf5a2f"></a>

# License

MIT.

