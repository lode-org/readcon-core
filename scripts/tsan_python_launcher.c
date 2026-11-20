/* Process entry that carries the rustc ThreadSanitizer runtime.
 *
 * That runtime archive uses local-exec TLS, so it cannot be linked into
 * a shared object and cannot be preloaded. This executable is linked
 * with the archive from the same rustc that built the extension, and
 * with --export-dynamic. It dlopens libpython and calls Py_BytesMain.
 * A cdylib loaded later resolves __tsan_* against the symbols this
 * executable exports.
 *
 * Dynamic mode (default):
 *   argv: tsan_python_launcher LIBPYTHON PROGRAM ARG...
 *   PROGRAM is the interpreter path Python uses to find its prefix.
 *
 * Static mode (TSAN_PY_STATIC):
 *   argv: tsan_python_launcher PROGRAM ARG...
 *   The launcher links libpython.a and calls Py_BytesMain directly.
 */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef TSAN_PY_STATIC
extern int Py_BytesMain(int argc, char **argv);
#endif

int main(int argc, char **argv) {
    int (*bytes_main)(int, char **);
#ifdef TSAN_PY_STATIC
    (void)bytes_main;
#else
    void *lib;
    void *symbol;
#endif

#ifdef TSAN_PY_STATIC
    if (argc < 2) {
        fprintf(stderr, "usage: tsan_python_launcher PROGRAM ARG...\n");
        return 2;
    }
#else
    if (argc < 3) {
        fprintf(stderr,
                "usage: tsan_python_launcher LIBPYTHON PROGRAM ARG...\n");
        return 2;
    }
#endif
    /* The control link has no TSan archive, so this symbol is absent.
     * Exit 2 before Python starts. The instrumented link exports it. */
    if (dlsym(RTLD_DEFAULT, "__tsan_func_entry") == NULL) {
        fprintf(stderr, "tsan runtime is not linked into this executable\n");
        return 2;
    }
#ifdef TSAN_PY_STATIC
    return Py_BytesMain(argc - 1, argv + 1);
#else
    lib = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
    if (lib == NULL) {
        fprintf(stderr, "dlopen %s: %s\n", argv[1], dlerror());
        return 2;
    }
    symbol = dlsym(lib, "Py_BytesMain");
    if (symbol == NULL) {
        fprintf(stderr, "dlsym Py_BytesMain: %s\n", dlerror());
        return 2;
    }
    memcpy(&bytes_main, &symbol, sizeof(symbol));
    return bytes_main(argc - 2, argv + 2);
#endif
}
