/*
 * Rewrite one CON file through the C binding.
 *
 * Read every frame, rebuild it with rkr_frame_binding_rewrite (the builder
 * stamps con_spec_minor), and write those frames.
 */
#include "readcon-core.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s input.con output.con\n", argv[0]);
        return 2;
    }
    size_t n = 0;
    struct RKRConFrame **frames = rkr_read_all_frames(argv[1], &n);
    if (!frames) {
        fprintf(stderr, "read failed: %s\n", argv[1]);
        return 1;
    }
    struct RKRConFrame **rewritten = NULL;
    if (n > 0) {
        rewritten = calloc(n, sizeof(*rewritten));
        if (!rewritten) {
            free_rkr_frame_array(frames, n);
            return 1;
        }
    }
    for (size_t i = 0; i < n; i++) {
        rewritten[i] = rkr_frame_binding_rewrite(frames[i]);
        if (!rewritten[i]) {
            fprintf(stderr, "rewrite failed: %s frame %zu\n", argv[1], i);
            for (size_t j = 0; j < i; j++) {
                free_rkr_frame(rewritten[j]);
            }
            free(rewritten);
            free_rkr_frame_array(frames, n);
            return 1;
        }
    }
    struct RKRConFrameWriter *writer = create_writer_from_path_c(argv[2]);
    if (!writer) {
        fprintf(stderr, "writer failed: %s\n", argv[2]);
        for (size_t i = 0; i < n; i++) {
            free_rkr_frame(rewritten[i]);
        }
        free(rewritten);
        free_rkr_frame_array(frames, n);
        return 1;
    }
    enum RKRStatus status = RKR_STATUS_SUCCESS;
    if (n > 0) {
        status = rkr_writer_extend(writer, (const struct RKRConFrame *const *)rewritten, n);
    }
    free_rkr_writer(writer);
    for (size_t i = 0; i < n; i++) {
        free_rkr_frame(rewritten[i]);
    }
    free(rewritten);
    free_rkr_frame_array(frames, n);
    if (status != RKR_STATUS_SUCCESS) {
        fprintf(stderr, "extend failed: %s\n", argv[2]);
        return 1;
    }
    return 0;
}
