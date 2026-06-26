/* Build with -DREADCON_CORE_HAS_METATENSOR and link readcon_core + metatensor */
#include "readcon-core.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "resources/test/tiny_cuh2.con";
    RKRConFrame *f = rkr_read_first_frame(path);
    if (!f) {
        fprintf(stderr, "read failed\n");
        return 1;
    }
#if defined(READCON_CORE_HAS_METATENSOR)
    struct mts_block_t *block = NULL;
    enum RKRStatus st = rkr_frame_metatensor_positions_block(f, &block);
    printf("positions block status=%d block=%p\n", (int)st, (void *)block);
    if (block)
        rkr_mts_block_free(block);
#else
    printf("built without READCON_CORE_HAS_METATENSOR\n");
#endif
    free_rkr_frame(f);
    return 0;
}
