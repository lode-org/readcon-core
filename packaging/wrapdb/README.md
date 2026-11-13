# wrapdb submission for readcon-core

Wrap name is `readcon-core`, matching the pkg-config file and
`meson.override_dependency('readcon-core', ...)`.

The wrap points at the **cxx source tarball** (`readcon-core-cxx-$VERSION.tar.gz`),
not the git tag archive. That tarball already contains `meson.build` and
shipped headers, so wrapdb does **not** need a `packagefiles/` meson patch.

## Produce the wrap

From the repository root, after the version bump:

```bash
# Slim archive only. The vendor tarball is a different file and must
# not be copied into this pin. The script builds once, then writes
# packaging/wrapdb/readcon-core.sha256, the wrap, and the doc snippets.
scripts/record-cxx-wrap.sh
```

`scripts/release-prep.sh` runs that step. The cxx release job builds the
same way and refuses to upload a digest that is not the pin.

Attach the tarball to the GitHub Release for `v$VERSION` so `source_url` resolves.

## wrapdb repository layout

In a wrapdb checkout:

```
subprojects/readcon-core.wrap          # generated file above
releases.json                          # add a readcon-core entry
```

No `subprojects/packagefiles/readcon-core/` overlay: upstream meson is the wrap.

`tools/sanity_checks.py` after `meson subprojects purge --confirm`.
The wrap requires cargo/rustc on the wrapdb CI image (same as other
cargo-backed wraps). It does **not** require cbindgen.

## Local wrap without wrapdb

A consumer project:

```
# subprojects/readcon-core.wrap  (same contents as the generated file)
readcon_dep = dependency('readcon-core')
```

Or, before the first cxx release is published, `meson.override_dependency`
from an `add_subdirectory`-equivalent `subproject()` of a git checkout.
