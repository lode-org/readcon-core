project(
    'readcon-core',
    ['rust', 'c'],
    version: '0.3.2',
    meson_version: '>=1.8.0',
    default_options: [
        'buildtype=debugoptimized',
        'warning_level=3',
        'c_std=c99',
        'rust_std=2024',
        'b_ndebug=if-release',
    ],
)

# Sanity checks
cc = meson.get_compiler('c')
rc = meson.get_compiler('rust')
if rc.version().version_compare('< 1.88.0')
    error('readcon-core requires Rust 1.88.0')
endif

cbindgen_prog = find_program('cbindgen', version: '>=0.29.0', required: true)

# Auxiliary variables
_mbproot = meson.project_build_root()
_msproot = meson.project_source_root()

# C Header
# This is done twice, once for installing things and once to generate the
# "in-tree" copy
readcon_header_build = custom_target(
    'cbindgen_clone',
    input: [files('cbindgen.toml'), files('src/lib.rs')],
    output: ['readcon-core.h'],
    command: [
        cbindgen_prog,
        '-q',
        '--config',
        '@INPUT0@',
        '--crate',
        'readcon',
        '--output',
        '@OUTPUT@',
        '--',
        '@INPUT1@',
    ],
    install: true,
    install_dir: 'include',
    build_by_default: true,
)

readcon_header_intree = custom_target(
    'cbindgen-readcon',
    input: [files('cbindgen.toml'), files('src/lib.rs')],
    output: ['readcon-intree'],
    command: [
        cbindgen_prog,
        '-q',
        '--config',
        '@INPUT0@',
        '--crate',
        'readcon',
        '@INPUT1@',
        '--output',
        f'@_msproot@/include/readcon-core.h',
    ],
    install: false,
    build_by_default: true,
)

readcon_sources = files(
    'src/lib.rs',
    'src/error.rs',
    'src/ffi.rs',
    'src/helpers.rs',
    'src/iterators.rs',
    'src/parser.rs',
    'src/types.rs',
    'src/writer.rs',
)

# Library
# In most cases we'd like the C linkage
readcon_lib = library(
    'readcon-core',
    readcon_sources,
    rust_abi: 'c',
)

# Mostly only for doctests
# gh-14813 is why this is static for now
readcon_rlib = static_library(
    'readcon_core',
    readcon_sources,
    rust_abi: 'rust',
)

if get_option('with_tests')
    rustmod = import('rust')
    rustmod.test('Rust tests', readcon_lib)
    # TODO(rg) :: Open an issue since doctests fail because of "unresolved or
    # unlinked readcon_core", though everything works via cargo --test
    rustmod.doctest('Rust documentation tests', readcon_rlib)
endif

readcon_dep = declare_dependency(
    link_with: readcon_lib,
    include_directories: include_directories('include'),
)

# Examples
if get_option('with_examples')
    subdir('examples')
endif

# Pkgconf generation

pkg = import('pkgconfig')
pkg_ver = meson.project_version()
pkg_install_dir = join_paths(get_option('datadir'), 'pkgconfig')
pkg.generate(
    readcon_lib,
    name: 'readcon-core',
    filebase: 'meson-readcon-core',
    description: 'CON file-reader in Rust',
    version: f'@pkg_ver@_meson',
    install_dir: pkg_install_dir,
)
