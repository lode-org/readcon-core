# Writer v3r paired benchmark

This directory records the fork-safe packed-cache rebase against the
pre-regression baseline `e8849a86` and the fuzz-leak-v3 base whose commit is
`8ddd2006` and whose tree is `6244ed42`.

The wrapper runs the unchanged writer-v3 paired harness: 21 fresh-process
AB/BA pairs per operation on one pinned CPU, a current/current A/A control,
and a 50,000-draw paired bootstrap interval. The raw JSON files contain every
observation and complete protocol metadata; the Markdown tables are generated
by the harness.

The initial e884 run retained a `-2.09%` extxyz A/A median whose bootstrap
interval excluded zero. Its raw data remains here. A second, immediately
following 21-pair confirmation put all A/A intervals across zero and retained
the same performance conclusion; it is recorded with the `-confirmation`
suffix rather than replacing the initial run.
