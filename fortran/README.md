# Fortran bindings

ISO_C_BINDING module `readcon` in `ReadCon/src/readcon.f90` over `include/readcon-core.h`.

Build the C library first (`cargo build --release`, Meson, or CMake), then compile the module with your Fortran compiler and link `readcon_core`.

Example (gfortran, after `cargo build --release`):

```bash
gfortran -c fortran/ReadCon/src/readcon.f90 -o readcon.o
# link your program with: readcon.o -L target/release -lreadcon_core -ldl -lpthread -lm
```

See docs bindings page (Fortran section) and issue #6.
