project(
    'readcon-core',
    'c',
    # One line of text. https://mesonbuild.com/Reference-manual_functions.html#project
    version: files('VERSION'),
    meson_version: '>=1.3.0',
    default_options: [
        'buildtype=debugoptimized',
        'warning_level=3',
        'c_std=c99',
        'b_ndebug=if-release',
    ],
    license: 'MIT',
)

# Shipped C/C++ headers. cbindgen is maintainer-only
# (scripts/regen-capi-headers.sh); wrap and FetchContent consumers never run it.
fs = import('fs')
_msproot = meson.project_source_root()
_mbproot = meson.project_build_root()
_incdir = include_directories('include')

if not fs.is_file(_msproot / 'include' / 'readcon-core.h')
    error(
        'missing shipped header include/readcon-core.h; maintainers run scripts/regen-capi-headers.sh',
    )
endif

cc = meson.get_compiler('c')
cargo_prog = find_program('cargo', required: true)
rustc_prog = find_program('rustc', required: true)
_py = find_program('python3', 'python')
_rv = run_command(rustc_prog, '--version', check: false)
if _rv.returncode() != 0
    # wrapdb qemu Alpine loongarch64/riscv64: rustc --version SIGABRT (scudo).
    # wrapdb treats this exact phrase as an architecture skip.
    error('unsupported architecture')
endif
_rv_bits = _rv.stdout().strip().split()
if _rv_bits.length() < 2 or not _rv_bits[1].version_compare('>= 1.88.0')
    error('readcon-core requires rustc >= 1.88.0')
endif

# Ninja rejects a newline in a rule, so the compiler argv is a build-dir
# file. The cargo script strips a ccache prefix and, only when the
# remaining command is not plain cc, passes that full command as CC and
# as the linker for the cargo target (CARGO_BUILD_TARGET, else the host).
_cc_list = _mbproot / 'readcon-meson-cc.txt'
_write_cc = [
    _py,
    '-c',
    'import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(chr(10).join(sys.argv[2:]) + chr(10))',
    _cc_list,
]
foreach _cc_part : cc.cmd_array()
    _write_cc += [_cc_part]
endforeach
run_command(_write_cc, check: true)
_cargo_env = {'READCON_MESON_CC_FILE': _cc_list}
_meson_c_args = get_option('c_args')
if _meson_c_args.length() > 0
    _cargo_env += {'CFLAGS': ' '.join(_meson_c_args)}
endif
_meson_link_args = get_option('c_link_args')
if _meson_link_args.length() > 0
    # Ninja rejects a newline in a rule, same as the compiler argv.
    _link_list = _mbproot / 'readcon-meson-link-args.txt'
    _write_link = [
        _py,
        '-c',
        'import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(chr(10).join(sys.argv[2:]) + chr(10))',
        _link_list,
    ]
    foreach _link_part : _meson_link_args
        _write_link += [_link_part]
    endforeach
    run_command(_write_link, check: true)
    _cargo_env += {'READCON_MESON_LINK_ARGS_FILE': _link_list}
endif

_rust_sys_deps = []
_needs_cxx = false
foreach _part : get_option('cargo_features').split(',')
    _name = _part.strip()
    if _name == 'zstd' or _name == 'chemfiles' or _name.startswith('chemfiles')
        _needs_cxx = true
    endif
endforeach
_cxx_libdir = ''
if _needs_cxx and host_machine.system() == 'linux'
    _stdcxx_probe = run_command('g++', '-print-file-name=libstdc++.so', check: false)
    if _stdcxx_probe.returncode() == 0
        _stdcxx_file = _stdcxx_probe.stdout().strip()
        if _stdcxx_file != '' and _stdcxx_file != 'libstdc++.so'
            _cxx_libdir = fs.parent(_stdcxx_file)
        endif
    endif
endif
if host_machine.system() == 'linux'
    _rust_sys_deps += [
        dependency('threads'),
        cc.find_library('dl', required: true),
        cc.find_library('m', required: true),
    ]
    if _needs_cxx
        _stdcxx_dirs = _cxx_libdir != '' ? [_cxx_libdir] : []
        _rust_sys_deps += cc.find_library('stdc++', dirs: _stdcxx_dirs, required: true)
    endif
elif host_machine.system() == 'darwin'
    _rust_sys_deps += [dependency('threads')]
    if _needs_cxx
        _rust_sys_deps += cc.find_library('c++', required: true)
    endif
elif host_machine.system() == 'android'
    if _needs_cxx
        _rust_sys_deps += cc.find_library('c++', required: true)
    endif
elif host_machine.system() == 'windows'
    _rust_sys_deps += [
        cc.find_library('ws2_32', required: true),
        cc.find_library('userenv', required: true),
        cc.find_library('bcrypt', required: true),
        cc.find_library('ntdll', required: true),
    ]
endif

if host_machine.system() == 'windows'
    _cargo_shared = 'readcon_core.dll'
    if cc.get_argument_syntax() == 'msvc'
        _cargo_static = 'readcon_core.lib'
    else
        _cargo_static = 'libreadcon_core.a'
    endif
else
    _so = host_machine.system() == 'darwin' ? '.dylib' : '.so'
    _cargo_shared = 'libreadcon_core' + _so
    _cargo_static = 'libreadcon_core.a'
endif

_profile = get_option('buildtype') == 'debug' ? 'debug' : 'release'

_src_rs = run_command(
    _py,
    '-c',
    'from pathlib import Path; print("\\n".join(str(p) for p in sorted(Path("src").rglob("*.rs"))))',
    check: true,
).stdout().strip().split('\n')

readcon_cargo = custom_target(
    'readcon-cargo',
    input: files('Cargo.toml', 'src/lib.rs'),
    depend_files: files('Cargo.lock', 'build.rs', 'support/chemfiles_link.rs') + files(_src_rs),
    output: [_cargo_shared, _cargo_static],
    command: [
        _py,
        files('scripts/meson_cargo_build.py'),
        cargo_prog.full_path(),
        _msproot,
        _mbproot / 'cargo-target',
        _profile,
        _cargo_shared,
        _cargo_static,
        '@OUTPUT0@',
        '@OUTPUT1@',
        get_option('cargo_features'),
    ],
    env: _cargo_env,
    build_by_default: true,
    install: true,
    install_dir: [get_option('libdir'), get_option('libdir')],
)

install_headers(
    'include/readcon-core.h',
    'include/readcon-core.hpp',
    'include/readcon-metatensor.h',
    'include/readcon-core-version.h',
)

# link_args carries the cargo archive; Meson must not
# promote an installed static consumer to link_whole (custom_target is not
# a library target). The cargo outputs themselves cannot be consumer
# sources: a static consumer would hand the archive to ar as an input.
# A generated header that depends on the cargo target gives every
# consumer the build ordering instead; a header needs no compiler in the
# consumer, so C and C++ projects both take it.
_readcon_link_args = []
_readcon_link_with = []
if get_option('default_library') == 'static'
    _readcon_link_args = [readcon_cargo[1].full_path()]
else
    # The shared target carries its runtime search directory to consumers.
    _readcon_link_with = [readcon_cargo[0]]
endif
readcon_link_stub = custom_target(
    'readcon-link-order',
    input: readcon_cargo,
    output: 'readcon_core_link_order.h',
    command: [
        _py,
        '-c',
        'import os, sys; os.makedirs(os.path.dirname(os.path.abspath(sys.argv[1])), exist_ok=True); open(sys.argv[1], "w").write("/* orders the readcon-core cargo build before its consumers link */" + chr(10))',
        '@OUTPUT@',
    ],
)
readcon_dep = declare_dependency(
    link_args: _readcon_link_args,
    link_with: _readcon_link_with,
    sources: readcon_link_stub,
    dependencies: _rust_sys_deps,
    include_directories: _incdir,
    version: meson.project_version(),
)
meson.override_dependency('readcon-core', readcon_dep)

if get_option('with_tests')
    runtime_consumer = executable(
        'test_runtime_dependency',
        files('tests/meson-wrap/main.c'),
        dependencies: readcon_dep,
    )
    test('runtime-dependency', runtime_consumer, env: {'LD_LIBRARY_PATH': ''})
    if host_machine.system() == 'linux'
        test(
            'shared-library-identity',
            _py,
            args: [files('scripts/check_shared_library_identity.py'), readcon_cargo[0]],
            depends: readcon_cargo,
        )
    endif
    test(
        'cargo-tests',
        cargo_prog,
        args: ['test', '--manifest-path', _msproot / 'Cargo.toml', '--locked'],
        timeout: 300,
    )
    c_golden = executable(
        'test_conformance_goldens',
        files('tests/c/test_conformance_goldens.c'),
        dependencies: readcon_dep,
        include_directories: _incdir,
        build_rpath: meson.project_build_root(),
    )
    test(
        'c-conformance-goldens',
        c_golden,
        args: [_msproot],
        env: {
            'READCON_CORE_ROOT': _msproot,
            'LD_LIBRARY_PATH': meson.project_build_root(),
        },
        timeout: 120,
    )
    c_trajectory = executable(
        'test_trajectory',
        files('tests/c/test_trajectory.c'),
        dependencies: readcon_dep,
        include_directories: _incdir,
        build_rpath: meson.project_build_root(),
    )
    test(
        'c-trajectory',
        c_trajectory,
        args: [_msproot, meson.current_build_dir()],
        env: {'LD_LIBRARY_PATH': meson.project_build_root()},
        timeout: 120,
    )
    c_positions = executable(
        'test_positions',
        files('tests/c/test_positions.c'),
        dependencies: readcon_dep,
        include_directories: _incdir,
        build_rpath: meson.project_build_root(),
    )
    test(
        'c-positions',
        c_positions,
        args: [_msproot],
        env: {'LD_LIBRARY_PATH': meson.project_build_root()},
        timeout: 180,
    )
    if add_languages('cpp', required: false)
        cpp_positions = executable(
            'test_cpp_positions',
            files('tests/c/test_cpp_positions.cpp'),
            dependencies: readcon_dep,
            include_directories: _incdir,
            build_rpath: meson.project_build_root(),
        )
        test(
            'cpp-positions',
            cpp_positions,
            args: [_msproot],
            env: {'LD_LIBRARY_PATH': meson.project_build_root()},
            timeout: 180,
        )
        cpp_cell_finite = executable(
            'test_cell_finite',
            files('tests/c/test_cell_finite.cpp'),
            dependencies: readcon_dep,
            include_directories: _incdir,
            build_rpath: meson.project_build_root(),
        )
        test(
            'cpp-cell-finite',
            cpp_cell_finite,
            args: [meson.current_build_dir() / 'cell_finite_scratch'],
            env: {'LD_LIBRARY_PATH': meson.project_build_root()},
            timeout: 120,
        )
    endif
endif

if get_option('with_examples')
    subdir('examples')
endif

pkg = import('pkgconfig')
pkg.generate(
    name: 'readcon-core',
    filebase: 'readcon-core',
    description: 'CON/convel file reader and writer with FFI, Python, Julia bindings',
    version: meson.project_version(),
    # Raw `-lfoo` strings do not get `-L${libdir}`; wrap consumers then
    # fail at link with "cannot find -lreadcon_core".
    libraries: ['-L${libdir}', '-lreadcon_core'],
    url: 'https://github.com/lode-org/readcon-core',
)
