
# Table of Contents

1.  [About](#orge287174)
    1.  [Features](#orgf6dccfc)
    2.  [Quick start](#org2330582)
    3.  [Design Decisions](#org53f108b)
        1.  [FFI Layer](#orgc5e5085)
    4.  [Specification](#orgbaeb465)
        1.  [CON format](#org3dbc655)
        2.  [convel format](#org09c8cc4)
    5.  [Why use this over readCon?](#org15ab7f7)
2.  [License](#org608925e)


<a id="orge287174"></a>

# About

Oxidized rust re-implementation of [readCon](https://github.com/HaoZeke/readCon).

Reads and writes both `.con` (coordinate-only) and `.convel` (coordinates
plus velocities) simulation configuration files used by [eOn](https://theory.cm.utexas.edu/eon/).


<a id="orgf6dccfc"></a>

## Features

-   **CON and convel support:** Parses both coordinate-only and velocity-augmented files. Velocity sections are auto-detected without relying on file extensions.
-   **Lazy iteration:** `ConFrameIterator` parses one frame at a time for memory-efficient trajectory processing.
-   **Performance:** Uses [fast-float2](https://github.com/aldanor/fast-float-rust) (Eisel-Lemire algorithm) for the f64 parsing hot path and [memmap2](https://docs.rs/memmap2) for large trajectory files.
-   **Parallel parsing:** Optional rayon-based parallel frame parsing behind the `parallel` feature gate.
-   **Language bindings:** Python (PyO3), Julia (ccall), C (cbindgen FFI), and C++ (RAII header-only wrapper), following the hourglass design from [Metatensor](https://github.com/metatensor/metatensor).
-   **Spec-v2 metadata helpers:** Rust, Python, C, and C++ bindings all expose typed helpers for common JSON metadata keys like `energy`, `frame_index`, `time`, `timestep`, `neb_bead`, and `neb_band`, while still allowing raw JSON metadata when needed.
-   **RPC serving:** Optional Cap'n Proto RPC interface (`rpc` feature) for network-accessible parsing.


<a id="org2330582"></a>

## Quick start

    # Rust
    cargo run --example rust_usage -- resources/test/tiny_cuh2.con
    
    # Python
    pip install readcon
    python -c "import readcon; print(readcon.read_con('file.con'))"
    
    # C/C++ (via meson subproject or cmake)
    meson setup builddir -Dwith_examples=True && meson test -C builddir
    
    # cargo-c install layout
    cargo cinstall --prefix /tmp/readcon-install


<a id="org53f108b"></a>

## Design Decisions

The library is designed with the following principles in mind:

-   **Lazy Parsing:** The `ConFrameIterator` allows for lazy parsing of frames, which can be more memory-efficient when dealing with large trajectory files.

-   **Interoperability:** The FFI layer makes the core parsing logic accessible from other programming languages, increasing the library's utility. Currently, a `C` header is auto-generated along with a hand-crafted `C++` interface, following the hourglass design from [Metatensor](https://github.com/metatensor/metatensor).


<a id="orgc5e5085"></a>

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


<a id="orgbaeb465"></a>

## Specification

See the [formal specification](https://lode-org.github.io/readcon-core/spec.html) for full details. A summary follows.


<a id="org3dbc655"></a>

### CON format

-   A 9-line header (comments, cell dimensions, cell angles, atom type/count/mass metadata)
-   Line 2 is reserved for spec-v2 JSON metadata
-   Per-type coordinate blocks (symbol, label, atom lines with x y z fixed atomID)
-   Multiple frames are concatenated directly with no separator


<a id="org09c8cc4"></a>

### convel format

Same as CON, with an additional velocity section after each frame's coordinates:

-   A blank separator line
-   Per-type velocity blocks (symbol, label, atom lines with vx vy vz fixed atomID)


<a id="org15ab7f7"></a>

## Why use this over [readCon](https://github.com/HaoZeke/readCon)?

Speed, correctness, and multi-language bindings.


<a id="org608925e"></a>

# License

MIT.
