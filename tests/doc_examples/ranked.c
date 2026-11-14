/* A finished publish leaves the path and no scratch name.

   Ranked writes are fresh-file by default. One MPI_Allgather shares each
   rank's byte length and frame count. Rank 0 renames the finished file
   onto the path. One gather then writes the .rcidx sidecar. The call is
   rkr_mpi_write_block. Spare reuse is not the default.
*/
#include "readcon-core.h"

#include <dirent.h>
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
    snprintf(path, sizeof path, "%s/ranked.con", dir);
    double cell[3] = {8.0, 8.0, 8.0};
    double angles[3] = {90.0, 90.0, 90.0};
    struct RKRConFrameBuilder *builder =
        rkr_frame_new(cell, angles, NULL, NULL, NULL, NULL);
    if (builder == NULL) {
        die("builder");
    }
    if (rkr_frame_add_atom_with_fixed_mask(builder, "Cu", 1.25, 0.0, 0.0, true, false,
                                           false, 7, 63.546) != RKR_STATUS_SUCCESS) {
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
    DIR *listing = opendir(dir);
    if (listing == NULL) {
        die("directory");
    }
    struct dirent *entry;
    while ((entry = readdir(listing)) != NULL) {
        if (strncmp(entry->d_name, ".readcon-write-", 15) == 0) {
            die("publish left a scratch name");
        }
    }
    closedir(listing);
    struct RKRConFrame *back = rkr_read_first_frame(path);
    if (back == NULL) {
        die("read");
    }
    uintptr_t n = 0;
    const double *xyz = rkr_frame_xyz_f64(back, &n);
    if (xyz == NULL || n < 1 || xyz[0] != 1.25) {
        die("published file is not the finished frame");
    }
    free_rkr_frame(back);
    _Exit(0);
}
