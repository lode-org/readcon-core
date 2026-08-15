project('readcon-core-wrap-test', 'c', meson_version: '>=1.3.0')

# Prefer an installed prefix (PKG_CONFIG_PATH). Fall back to the parent
# source tree as a meson subproject so the wrap contract can be tested
# before a tarball is published.
readcon_dep = dependency('readcon-core', required: false)
if not readcon_dep.found()
    readcon_proj = subproject('readcon-core')
    readcon_dep = readcon_proj.get_variable('readcon_dep')
endif

executable(
    'c-main',
    'main.c',
    dependencies: readcon_dep,
)
