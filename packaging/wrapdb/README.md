# wrapdb submission for readcon-core

Wrap name is `readcon-core`, matching the pkg-config file and
`meson.override_dependency('readcon-core', ...)`.

The wrap points at the **cxx source tarball** (`readcon-core-cxx-$VERSION.tar.gz`),
not the git tag archive. That tarball already contains `meson.build` and
shipped headers, so wrapdb does **not** need a `packagefiles/` meson patch.

## Produce the wrap

From the repository root, after `scripts/package-cxx.sh /tmp/cxx --vendor`:

```bash
VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' Cargo.toml | head -1)
SHA=$(cut -d' ' -f1 /tmp/cxx/readcon-core-cxx-${VERSION}.tar.gz.sha256)
sed -e "s/@VERSION@/${VERSION}/g" -e "s/@SHA256@/${SHA}/g" \
  packaging/wrapdb/readcon-core.wrap.in > packaging/wrapdb/readcon-core.wrap
```

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
