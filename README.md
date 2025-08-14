
# Table of Contents

1.  [About](#org6deaf2b)
    1.  [Usage](#orgd695155)
    2.  [Design Decisions](#org4d1e975)
        1.  [FFI Layer](#orgeebace5)
    3.  [Specification](#org1a693f0)
        1.  [Single Frames](#org426e5e3)
        2.  [Multiple Frames](#org9f85032)
    4.  [Why use this over readCon?](#orgfbf286c)
2.  [License](#orgdac33f0)


<a id="org6deaf2b"></a>

# About

Oxidized rust re-implementation of [readCon](https://github.com/HaoZeke/readCon).


<a id="orgd695155"></a>

## Usage

    cargo run -- resources/test/sulfolene.con


<a id="org4d1e975"></a>

## Design Decisions

The library is designed with the following principles in mind:

-   **Lazy Parsing:** The `ConFrameIterator` allows for lazy parsing of frames, which can be more memory-efficient when dealing with large trajectory files.

-   **Interoperability:** The FFI layer makes the core parsing logic accessible from other programming languages, increasing the library's utility. Currently, a `C` header is auto-generated along with a hand-crafted `C++` interface, following the hourglass design from [Metatensor](https://github.com/metatensor/metatensor).


<a id="orgeebace5"></a>

### FFI Layer

A key challenge in designing an FFI is deciding how data is exposed to the C-compatible world. This library uses a hybrid approach to offer both safety and convenience:

1.  **Opaque Pointers (The Handle Pattern):** The primary way to interact with
    frame data is through an opaque pointer, represented as `RKRConFrame*` in C.
    The C/C++ client holds this "handle" but cannot inspect its contents
    directly. Instead, it must call Rust functions to interact with the data
    (e.g., `rkr_frame_get_header_line(frame_handle, ...`)). This is the safest
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


<a id="org1a693f0"></a>

## Specification

Currently this implements the `con` format specification as written out by eON,
so some assumptions are made about the input files, not all of which are
currently tested / guaranteed to throw (contributions are welcome for additional
sanity checks).


<a id="org426e5e3"></a>

### Single Frames

-   The first 9 lines are the header
-   The remaining lines can be inferred from the header


<a id="org9f85032"></a>

### Multiple Frames

Often, as for example when running a Nudged Elastic Band, `eON` will write out
multiple units of `con` like data into a single file.

-   The `con` like data **have no whitespace between them**!

That is we expect:

    Random Number Seed
    Time
    15.345600	21.702000	100.000000
    90.000000	90.000000	90.000000
    0 0
    218 0 1
    2
    2 2
    63.546000 1.007930
    Cu
    Coordinates of Component 1
       0.63940000000000108    0.90450000000000019    6.97529999999999539 1    0
       3.19699999999999873    0.90450000000000019    6.97529999999999539 1    1
    H
    Coordinates of Component 2
       8.68229999999999968    9.94699999999999740   11.73299999999999343 0  2
       7.94209999999999550    9.94699999999999740   11.73299999999999343 0  3
    Random Number Seed
    Time
    15.345600	21.702000	100.000000
    90.000000	90.000000	90.000000
    0 0
    218 0 1
    2
    2 2
    63.546000 1.007930
    Cu
    Coordinates of Component 1
       0.63940000000000108    0.90450000000000019    6.97529999999999539 1    0
       3.19699999999999873    0.90450000000000019    6.97529999999999539 1    1
    H
    Coordinates of Component 2
       8.85495714285713653    9.94699999999999740   11.16538571428571380 0  2
       7.76944285714285154    9.94699999999999740   11.16538571428571380 0  3

Nothing else. No whitespace or lines between the `con` entries.


<a id="orgfbf286c"></a>

## Why use this over [readCon](https://github.com/HaoZeke/readCon)?

To learn Rust. Maybe speed.


<a id="orgdac33f0"></a>

# License

MIT.

