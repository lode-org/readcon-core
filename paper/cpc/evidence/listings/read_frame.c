/* Read one CON file with the C API as it is on main.
 *
 * rkr_read_all_frames returns NULL on failure and does not write an
 * error string. readcon-core issue 51 is the open change that would
 * keep one. This listing does not depend on that change: a null handle
 * is the failure signal, and rkr_status_message is used only for the
 * status codes the other calls return.
 *
 * Ownership: the caller frees the array with free_rkr_frame_array.
 * That call frees each frame. Do not also call free_rkr_frame.
 */

#include <stdio.h>
#include <stdint.h>

#include "readcon-core.h"

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "v31_slab.con";
    uintptr_t nframes = 0;
    struct RKRConFrame **frames = rkr_read_all_frames(path, &nframes);
    if (frames == NULL) {
        fprintf(stderr, "read failed (null handle, no error string): %s\n", path);
        return 1;
    }
    const char *version = rkr_library_version();
    uintptr_t natoms = rkr_frame_atom_count(frames[0]);
    uintptr_t nxyz = 0;
    const double *xyz = rkr_frame_xyz_f64(frames[0], &nxyz);
    double energy = rkr_frame_energy(frames[0]);
    printf("library %s\nframes %zu\natoms %zu\n",
           version != NULL ? version : "?",
           (size_t)nframes,
           (size_t)natoms);
    if (xyz != NULL && nxyz > 0) {
        printf("first_x %.17g\n", xyz[0]);
    }
    if (energy == energy) {
        printf("energy %.17g\n", energy);
    } else {
        printf("energy absent\n");
    }
    printf("status_ok %s\n", rkr_status_message(RKR_STATUS_SUCCESS));
    free_rkr_frame_array(frames, nframes);
    return 0;
}
