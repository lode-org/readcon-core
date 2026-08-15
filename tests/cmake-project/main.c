#include "readcon-core.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "tiny_multi_cuh2.con";
    const char *version = rkr_library_version();
    if (version == NULL || strlen(version) == 0) {
        fprintf(stderr, "rkr_library_version returned empty\n");
        return 1;
    }
    printf("readcon-core %s\n", version);

    uintptr_t nframes = 0;
    struct RKRConFrame **frames = rkr_read_all_frames(path, &nframes);
    if (frames == NULL || nframes == 0) {
        fprintf(stderr, "failed to read %s\n", path);
        return 1;
    }
    printf("frames %zu\n", (size_t)nframes);
    free_rkr_frame_array(frames, nframes);
    return 0;
}
