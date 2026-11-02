# wrapdb submission for readcon-core

Wrap name is `readcon-core`, matching the pkg-config file and
`meson.override_dependency('readcon-core', ...)`.

The wrap points at the **cxx source tarball** (`readcon-core-cxx-$VERSION.tar.gz`),
not the git tag archive. That tarball already contains `meson.build` and
shipped headers, so wrapdb does **not** need a `packagefiles/` meson patch.

## Produce the wrap

From the repository root, after `scripts/package-cxx.sh /tmp/cxx --vendor`:

```bash
# Record the tarball digest, then restamp. VERSION supplies the release.
printf '%s\n' "$SHA" > packaging/wrapdb/readcon-core.sha256
scripts/stamp-version.sh
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
