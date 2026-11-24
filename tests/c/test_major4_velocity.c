/* Write a major-4 frame with a velocity and units.time fs, then read both back. */
#include "readcon-core.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

static void check(int ok, const char *what) {
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", what);
        if (rkr_last_error_message() != NULL) {
            fprintf(stderr, "  %s\n", rkr_last_error_message());
        }
        failures++;
    }
}

int main(int argc, char **argv) {
    double cell[3] = {10.0, 10.0, 10.0};
    double angles[3] = {90.0, 90.0, 90.0};
    double velocity[3] = {1.5, -0.25, 0.0};
    double got[3] = {0.0, 0.0, 0.0};
    const char *units =
        "{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\",\"time\":\"fs\"}";
    struct RKRConFrameBuilder *builder;
    struct RKRConFrame *frame;
    struct RKRConFrameWriter *writer;
    struct RKRConFrame *read_back;
    const struct RKRConFrame *handles[1];
    char *json;
    const char *path;

    if (argc != 2) {
        fprintf(stderr, "usage: %s FILE\n", argv[0]);
        return 2;
    }
    path = argv[1];

    builder = rkr_frame_new(cell, angles, "major4", NULL, "", "");
    check(builder != NULL, "rkr_frame_new");
    check(rkr_frame_builder_set_units(builder, units) == RKR_STATUS_SUCCESS, "set_units");
    check(rkr_frame_add_atom_full(builder, "H", 0.0, 0.0, 0.0, false, false, false, 7, 1.008,
                                  velocity, NULL) == RKR_STATUS_SUCCESS,
          "add_atom_full");
    frame = rkr_frame_builder_build(&builder);
    check(frame != NULL, "build");

    writer = create_writer_from_path_c(path);
    check(writer != NULL, "create_writer");
    handles[0] = frame;
    check(rkr_writer_extend(writer, handles, 1) == RKR_STATUS_SUCCESS, "extend");
    check(rkr_writer_flush(writer) == RKR_STATUS_SUCCESS, "flush");
    free_rkr_writer(writer);
    free_rkr_frame(frame);

    read_back = rkr_read_first_frame(path);
    check(read_back != NULL, "read_first_frame");
    check(rkr_frame_spec_version(read_back) == 4, "spec version 4");
    json = rkr_frame_metadata_json(read_back);
    check(json != NULL, "metadata_json");
    check(strstr(json, "\"time\":\"fs\"") != NULL, json);
    check(strstr(json, "\"con_spec_version\":4") != NULL, json);
    check(rkr_frame_copy_velocities(read_back, got, 3) == RKR_STATUS_SUCCESS, "copy_velocities");
    check(memcmp(got, velocity, sizeof velocity) == 0, "velocity bytes");
    rkr_free_string(json);
    free_rkr_frame(read_back);

    if (failures != 0) {
        fprintf(stderr, "%d C major-4 velocity check(s) failed\n", failures);
        return 1;
    }
    return 0;
}
