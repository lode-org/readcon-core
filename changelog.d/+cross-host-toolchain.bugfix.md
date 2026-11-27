The libstdc++ cmake toolchain file is set for the host build only.
A cross build keeps the target C and C++ compilers. MSVC still links
with link.exe; cl.exe is not passed as the linker.
