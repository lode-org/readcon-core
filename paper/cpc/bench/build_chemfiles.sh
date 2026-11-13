#!/usr/bin/env bash
# chemfiles 0.10.4 shared libraries for the C++ head-to-head cells: one per
# compiler (g++, clang++) and optimisation level (-O2, -O3), the level the
# readcon driver of that cell is compiled with.  The system compilers and
# cmake build them; the conda compilers of the pixi environment stay off PATH,
# so every cell uses one toolchain.  clang++ compiles against the libstdc++ of
# $GXX.
#
#   bash bench/build_chemfiles.sh     # into $CHEMFILES_BUILDS, default bench/work/chemfiles
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=${CHEMFILES_BUILDS:-$here/work/chemfiles}
version=0.10.4
sha256=b8232ddaae2953538274982838aa6c2df87d300f7e2f80e92c171581e06325ba
url=https://github.com/chemfiles/chemfiles/archive/refs/tags/$version.tar.gz
GCC=${GCC:-/usr/bin/gcc}
GXX=${GXX:-/usr/bin/g++}
CLANG=${CLANG:-/usr/bin/clang}
CLANGXX=${CLANGXX:-/usr/bin/clang++}
export PATH=/usr/bin:/bin

mkdir -p "$out"
tarball=$out/chemfiles-$version.tar.gz
[ -f "$tarball" ] || curl -fsSL -o "$tarball" "$url"
echo "$sha256  $tarball" | sha256sum -c -
src=$out/chemfiles-$version
[ -d "$src" ] || tar -C "$out" -xzf "$tarball"
gcc_major=$("$GXX" -dumpversion | cut -d. -f1)

for cell in gcc:-O2 gcc:-O3 clang:-O2 clang:-O3; do
  name=${cell%%:*}
  opt=${cell#*:}
  dir=$out/build-$name-o${opt#-O}
  if [ "$name" = gcc ]; then
    cc=$GCC cxx=$GXX extra=()
  else
    cc=$CLANG cxx=$CLANGXX
    # CMake's compiler check links with the C++ flags but not with the linker flags.
    libstdcxx="-L/usr/lib/gcc/x86_64-linux-gnu/$gcc_major"
    extra=(-DCMAKE_CXX_FLAGS="-I/usr/include/c++/$gcc_major -I/usr/include/x86_64-linux-gnu/c++/$gcc_major $libstdcxx"
           -DCMAKE_SHARED_LINKER_FLAGS="$libstdcxx")
  fi
  if compgen -G "$dir/libchemfiles.so*" > /dev/null; then
    echo "$name $opt: $dir already built"
    continue
  fi
  cmake -S "$src" -B "$dir" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" \
    -DCMAKE_C_FLAGS_RELEASE="$opt" -DCMAKE_CXX_FLAGS_RELEASE="$opt" \
    -DBUILD_SHARED_LIBS=ON -DCHFL_BUILD_TESTS=OFF "${extra[@]}" > "$dir.cmake.log" 2>&1
  cmake --build "$dir" -j"${CHEMFILES_JOBS:-4}" > "$dir.build.log" 2>&1
  echo "$name $opt: $(ls "$dir"/libchemfiles.so* | head -1)"
done
