project(
    'readconrs',
    ['rust', 'cpp'],
    version: '0.1',
    default_options: [
        'buildtype=release',
        'warning_level=3',
        'cpp_std=c++17',
        'rust_std=2024',
        'b_ndebug=if-release',
    ],
)
cppc = meson.get_compiler('cpp')
cbindgen_prog = find_program('cbindgen', required: true)
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
    rust_crate_type: 'staticlib',
)

readcon_dep = declare_dependency(
    link_whole: readcon_lib,
    include_directories: include_directories('.'),
)
