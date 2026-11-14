/* The published path is the previous file or the finished rewrite. */
#include "readcon-core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void die(const char *what) {
    const char *detail = rkr_last_error_message();
    fprintf(stderr, "%s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
    exit(1);
}

static struct RKRConFrame *one_atom(double x) {
    double cell[3] = {10.0, 10.0, 10.0};
    double angles[3] = {90.0, 90.0, 90.0};
    struct RKRConFrameBuilder *builder =
        rkr_frame_new(cell, angles, NULL, NULL, NULL, NULL);
    if (builder == NULL) {
        die("builder");
    }
    if (rkr_frame_add_atom(builder, "Cu", x, 0.0, 0.0, false, 1, 63.546) !=
        RKR_STATUS_SUCCESS) {
        die("add atom");
    }
    struct RKRConFrame *frame = rkr_frame_builder_build(builder);
    free_rkr_frame_builder(builder);
    if (frame == NULL) {
        die("build");
    }
    return frame;
}

static void write_fresh(const char *path, struct RKRConFrame *frame) {
    struct RKRConFrameWriter *writer = create_writer_from_path_round_trip_c(path);
    if (writer == NULL) {
        die("writer");
    }
    const struct RKRConFrame *handles[1] = {frame};
    if (rkr_writer_extend(writer, handles, 1) != RKR_STATUS_SUCCESS) {
        die("write");
    }
    free_rkr_writer(writer);
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[512];
    char spare[520];
    snprintf(path, sizeof path, "%s/traj.con", dir);
    snprintf(spare, sizeof spare, "%s.rewrite", path);
    struct RKRConFrame *first = one_atom(1.0);
    write_fresh(path, first);
    free_rkr_frame(first);
    struct RKRConFrame *next = one_atom(3.5);
    const struct RKRConFrame *handles[1] = {next};
    if (rkr_rewrite_path(path, handles, 1, 1, 0) != RKR_STATUS_SUCCESS) {
        die("rewrite");
    }
    free_rkr_frame(next);
    if (access(spare, F_OK) == 0) {
        die("keep_spare 0 left the spare");
    }
    FILE *file = fopen(path, "r");
    if (file == NULL) {
        die("open");
    }
    char text[4096];
    size_t n = fread(text, 1, sizeof text - 1, file);
    text[n] = '\0';
    fclose(file);
    if (strstr(text, "3.5") == NULL) {
        die("published path is not the finished rewrite");
    }
    _Exit(0);
}
