# ------------------------ Examples

examples_array = [  #
    ['c_api_sample', 'c_api_sample.c', f'@_msproot@/resources/test/cuh2.con'],
]

if get_option('with_cpp')
    add_languages('cpp', native: false)
    examples_array += [
        [
            'cpp_api_sample',
            'cpp_api_sample.cpp',
            f'@_msproot@/resources/test/sulfolene.con',
        ],
    ]
endif
foreach exmpl : examples_array
    test(
        exmpl.get(0),
        executable(
            exmpl.get(0),
            sources: [exmpl.get(1)],
            dependencies: readcon_dep,
            include_directories: include_directories('../include'),
        ),
        args: exmpl.get(2),
        workdir: _msproot + '/resources/test/',
    )
endforeach
