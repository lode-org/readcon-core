/* Short decimals of at most six places are spelled directly. */
#include "readcon-core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void die(const char *what) {
    const char *detail = rkr_last_error_message();
    fprintf(stderr, "%s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
    exit(1);
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[512];
    snprintf(path, sizeof path, "%s/short.con", dir);
    double cell[3] = {10.0, 10.0, 10.0};
    double angles[3] = {90.0, 90.0, 90.0};
    struct RKRConFrameBuilder *builder =
        rkr_frame_new(cell, angles, NULL, NULL, NULL, NULL);
    if (builder == NULL) {
        die("builder");
    }
    if (rkr_frame_add_atom(builder, "Cu", 1.5, 0.25, 2.0, false, 1, 63.546) !=
        RKR_STATUS_SUCCESS) {
        die("add atom");
    }
    struct RKRConFrame *frame = rkr_frame_builder_build(builder);
    free_rkr_frame_builder(builder);
    if (frame == NULL) {
        die("build");
    }
    struct RKRConFrameWriter *writer = create_writer_from_path_round_trip_c(path);
    if (writer == NULL) {
        die("writer");
    }
    const struct RKRConFrame *handles[1] = {frame};
    if (rkr_writer_extend(writer, handles, 1) != RKR_STATUS_SUCCESS) {
        die("write");
    }
    free_rkr_writer(writer);
    free_rkr_frame(frame);
    FILE *file = fopen(path, "r");
    if (file == NULL) {
        die("open");
    }
    char text[4096];
    size_t n = fread(text, 1, sizeof text - 1, file);
    text[n] = '\0';
    fclose(file);
    if (strstr(text, "1.5") == NULL || strstr(text, "0.25") == NULL ||
        strstr(text, "2.0") == NULL) {
        die("short decimal spelling");
    }
    /* The cdylib's process teardown can stall after a successful check. */
    _Exit(0);
}
