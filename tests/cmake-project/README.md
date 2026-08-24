# CMake consumer smoke

Exercises the two CMake entry points without cbindgen:

```bash
# FetchContent from a source tree (git checkout or unpacked cxx tarball)
cmake -S tests/cmake-project -B build/cmake-fetch \
  -DREADCON_CORE_SOURCE_DIR=$PWD \
  -DREADCON_CORE_USE_FETCHCONTENT=ON
cmake --build build/cmake-fetch
./build/cmake-fetch/c-main resources/test/tiny_multi_cuh2.con
./build/cmake-fetch/c-conformance $PWD

# find_package after a prefix install
cmake -S . -B build/core-prefix -DCMAKE_INSTALL_PREFIX=$PWD/prefix
cmake --build build/core-prefix
cmake --install build/core-prefix
cmake -S tests/cmake-project -B build/cmake-find \
  -DCMAKE_PREFIX_PATH=$PWD/prefix
cmake --build build/cmake-find
PKG_CONFIG_PATH=$PWD/prefix/lib/pkgconfig pkg-config --exists --print-errors readcon-core
```
