#include "readcon-core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static long vm_hwm_kib(void) {
    FILE *file = fopen("/proc/self/status", "r");
    char line[256];
    long value = 0;
    if (file == NULL) {
        return 0;
    }
    while (fgets(line, sizeof line, file) != NULL) {
        if (sscanf(line, "VmHWM: %ld", &value) == 1) {
            break;
        }
    }
    fclose(file);
    return value;
}

int main(int argc, char **argv) {
    const char *op;
    const char *path;
    const char *out;
    int repeats;
    int i;
    if (argc != 5) {
        return 2;
    }
    op = argv[1];
    path = argv[2];
    out = argv[3];
    repeats = atoi(argv[4]);
    if (strcmp(op, "read") == 0) {
        for (i = 0; i < repeats + 1; i++) {
            uintptr_t got_frames = 0;
            uintptr_t got_atoms = 0;
            struct RKRPositionBlock *block;
            const double *values;
            double t0 = now_s();
            block = rkr_read_positions(path, &got_frames, &got_atoms);
            values = rkr_position_block_values(block);
            if (block == NULL || (got_frames > 0 && got_atoms > 0 && values == NULL)) {
                fprintf(stderr, "read failed\n");
                return 1;
            }
            if (got_frames > 0 && got_atoms > 0 && values[0] != values[0]) {
                fprintf(stderr, "nan\n");
                return 1;
            }
            rkr_free_position_block(block);
            if (i > 0) {
                printf("read %.9f\n", now_s() - t0);
            }
        }
    } else if (strcmp(op, "frames") == 0) {
        for (i = 0; i < repeats + 1; i++) {
            uintptr_t nframes = 0;
            struct RKRConFrame **frames;
            double t0 = now_s();
            frames = rkr_read_all_frames_n_threads(path, &nframes, 1);
            if (frames == NULL || nframes == 0) {
                fprintf(stderr, "read failed\n");
                return 1;
            }
            free_rkr_frame_array(frames, nframes);
            if (i > 0) {
                printf("read %.9f\n", now_s() - t0);
            }
        }
        printf("hwm_kib %ld\n", vm_hwm_kib());
    } else {
        uintptr_t nframes = 0;
        struct RKRConFrame **frames = rkr_read_all_frames(path, &nframes);
        if (frames == NULL) {
            fprintf(stderr, "read failed\n");
            return 1;
        }
        for (i = 0; i < repeats; i++) {
            struct RKRConFrameWriter *writer;
            double t0 = now_s();
            unlink(out);
            writer = create_writer_from_path_c(out);
            if (rkr_writer_extend(writer, (const struct RKRConFrame *const *)frames, nframes) !=
                RKR_STATUS_SUCCESS) {
                fprintf(stderr, "write failed\n");
                return 1;
            }
            free_rkr_writer(writer);
            printf("write %.9f\n", now_s() - t0);
        }
        free_rkr_frame_array(frames, nframes);
    }
    printf("hwm_kib %ld\n", vm_hwm_kib());
    return 0;
}
