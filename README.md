
# Table of Contents

1.  [About](#org99d34ad)
    1.  [Usage](#org64d325a)
    2.  [Design Decisions](#org66293d0)
    3.  [Specification](#orga81e9a8)
        1.  [Single Frames](#org637d081)
        2.  [Multiple Frames](#org5ff08e1)
    4.  [Why use this over readCon?](#org7b419dc)
2.  [License](#org8802432)


<a id="org99d34ad"></a>

# About

Oxidized rust re-implementation of [readCon](https://github.com/HaoZeke/readCon).


<a id="org64d325a"></a>

## Usage

    cargo run -- resources/test/sulfolene.con


<a id="org66293d0"></a>

## Design Decisions

The library is designed with the following principles in mind:

-   **Lazy Parsing:** The `ConFrameIterator` allows for lazy parsing of frames, which can be more memory-efficient when dealing with large trajectory files.

-   **Interoperability:** The FFI layer makes the core parsing logic accessible from other programming languages, increasing the library's utility. Currently, a `C` header is auto-generated along with a hand-crafted `C++` interface, following the hourglass design from [Metatensor](https://github.com/metatensor/metatensor).


<a id="orga81e9a8"></a>

## Specification

Currently this implements the `con` format specification as written out by eON,
so some assumptions are made about the input files, not all of which are
currently tested / guaranteed to throw (contributions are welcome for additional
sanity checks).


<a id="org637d081"></a>

### Single Frames

-   The first 9 lines are the header
-   The remaining lines can be inferred from the header


<a id="org5ff08e1"></a>

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


<a id="org7b419dc"></a>

## Why use this over [readCon](https://github.com/HaoZeke/readCon)?

To learn Rust. Maybe speed.


<a id="org8802432"></a>

# License

MIT.

