project(
    'readcon-core',
    ['rust', 'c'],
    version: '0.4.3',
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

cargo_prog = find_program('cargo', required: true)

# Build the Rust library via cargo to ensure all dependencies
# (memmap2, fast_float2, etc.) are properly resolved and linked.
# Meson's native library(rust_abi: 'c') bypasses Cargo, making
# external crates unavailable.
#
# On Windows cargo produces .lib; elsewhere .a.
if host_machine.system() == 'windows'
    _cargo_lib_name = 'readcon_core.lib'
else
    _cargo_lib_name = 'libreadcon_core.a'
endif

_py = find_program('python3', 'python')

readcon_cargo = custom_target(
    'readcon-cargo',
    input: files('Cargo.toml', 'Cargo.lock', 'src/lib.rs'),
    output: _cargo_lib_name,
    command: [
        _py, '-c',
        'import subprocess, shutil, sys; ' +
        'subprocess.check_call([sys.argv[1], "build", "--release", "--manifest-path", sys.argv[2], "--target-dir", sys.argv[3] + "/cargo-target"]); ' +
        'shutil.copy2(sys.argv[3] + "/cargo-target/release/" + sys.argv[4], sys.argv[5])',
        cargo_prog, '@INPUT0@', '@PRIVATE_DIR@', _cargo_lib_name, '@OUTPUT0@',
    ],
    build_by_default: true,
)

# System dependencies required when statically linking a Rust library
_rust_sys_deps = []
if host_machine.system() == 'linux'
    _rust_sys_deps += [
        dependency('threads'),
        cc.find_library('dl', required: true),
        cc.find_library('m', required: true),
    ]
elif host_machine.system() == 'darwin'
    _rust_sys_deps += [dependency('threads')]
elif host_machine.system() == 'windows'
    _rust_sys_deps += [
        cc.find_library('ws2_32', required: true),
        cc.find_library('userenv', required: true),
        cc.find_library('bcrypt', required: true),
        cc.find_library('ntdll', required: true),
    ]
endif

if get_option('with_tests')
    test('cargo-tests', cargo_prog,
        args: ['test', '--manifest-path', _msproot / 'Cargo.toml'],
        timeout: 300,
    )
endif

# Use link_args rather than link_with so that Meson never attempts to
# promote the link to link_whole for installed static library consumers.
# link_whole does not support custom_targets. Passing the archive path
# via link_args sidesteps this entirely while working for both shared
# and static consumers. The custom_target in sources ensures build
# ordering (cargo runs before any consumer links).
readcon_dep = declare_dependency(
    link_args: [readcon_cargo.full_path()],
    sources: readcon_cargo,
    dependencies: _rust_sys_deps,
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
    name: 'readcon-core',
    filebase: 'meson-readcon-core',
    description: 'CON file-reader in Rust',
    version: f'@pkg_ver@_meson',
    install_dir: pkg_install_dir,
)
