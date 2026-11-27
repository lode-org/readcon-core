Zstd and chemfiles builds name libstdc++ on Linux and libc++ on macOS.
clang does not search GCC's libstdc++ directory, so the link used to
fail with "cannot find -lstdc++". scripts/libstdcxx.cmake adds the
directory g++ reports before chemfiles-sys reaches project(). The
host g++ is not forced onto a cross compile.
