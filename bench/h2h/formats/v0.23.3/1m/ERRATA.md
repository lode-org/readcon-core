# Errata: 1M cross-format record

- Record: `bench/h2h/formats/v0.23.3/1m/cross-format.json`
- Measured commit: `e938ccf4fae892302ffe0b3a72a0361233b05970`

One sentence in the `notes` block of `cross-format.json` (`cross-format.json:133`) reads:

> 1M readcon-con serial fresh-process read 0.1223 s, default threads
> 0.1251 s. The table row is the interleaved serial measurement. Default
> threads is one worker per core, same warmup and sample count (6).

The two medians it quotes — the serial `0.1223` s and the default-threads
`0.1251` s — have **no recorded samples**. Neither number appears in
`by-arm/`, in any row's `samples_s`, or in `cross-format.tsv`. The harness
that wrote this record (`bench/h2h/cross_format.py`) returned only the
median of each of those two extra fresh-process read passes and never
stored their raw samples. **Do not cite either number:** it cannot be
checked against the samples behind it.

Every other cell in this directory is backed by its recorded samples.
Each row's median and IQR are the type-7 statistics of that row's
`samples_s`, and each of those samples is also appended under `by-arm/`.

This record is kept exactly as measured and is not edited or regenerated.
The harness has been fixed for future runs so that these fresh-process
passes record their raw samples — `samples_s` and the matching `by-arm/`
rows — like every other arm.
