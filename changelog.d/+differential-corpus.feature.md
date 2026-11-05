`tests/python/test_differential_corpus.py` reads four files of `resources/test` with `readcon.read_con`.
It compares the frames with ASE and with `bench_con_reader --dump`.
Symbols, positions, flags and ids must match exactly.
Without ASE or a C compiler the test skips.
In CI it fails instead.
