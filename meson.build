project(
    'readcon-core',
    ['rust', 'c'],
    version: '0.1',
    meson_version: '>=1.3.0',
    default_options: [
        'buildtype=debugoptimized',
        'warning_level=3',
        'c_std=c99',
        'rust_std=2024',
        'b_ndebug=if-release',
    ],
)
cc = meson.get_compiler('c')
rc = meson.get_compiler('rust')
if rc.version().version_compare('< 1.88.0')
    error('readcon-rs requires Rust 1.88.0')
endif

# C Header
cbindgen_prog = find_program('cbindgen', version: '>=0.29.0', required: true)
readcon_header_target = custom_target(
    'cbindgen-readcon',
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
)

# Library
# In most cases we'd like the C linkage
readcon_lib = library(
    'readcon-core',
    'src/lib.rs',
    'src/error.rs',
    'src/iterators.rs',
    'src/parser.rs',
    'src/types.rs',
    rust_abi: 'c',  # Can be 'C' or 'Rust'
)

readcon_dep = declare_dependency(
    link_with: readcon_lib,
    include_directories: include_directories('.'),
)


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
