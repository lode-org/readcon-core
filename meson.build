project(
    'readconrs',
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
cbindgen_prog = find_program('cbindgen', version: '>=0.29.0', required: true)
readcon_header_target = custom_target(
    'cbindgen-readcon',
    input: [files('cbindgen.toml'), files('src/lib.rs')],
    output: 'readcon.h',
    command: [
        cbindgen_prog,
        '--config',
        '@INPUT0@',
        '--crate',
        'readcon',
        '--output',
        '@OUTPUT@',
        '--',
        '@INPUT1@',
    ],
)
readcon_lib = static_library(
    'readcon',
    'src/lib.rs',
    'src/error.rs',
    'src/iterators.rs',
    'src/parser.rs',
    'src/types.rs',
    rust_abi: 'c',
)

readcon_dep = declare_dependency(
    link_whole: readcon_lib,
    include_directories: include_directories('.'),
)
