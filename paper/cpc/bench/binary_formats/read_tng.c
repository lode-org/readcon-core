/* TNG through the utility reader of the TNG library: tng_util_trajectory_open,
 * then, one frame at a time, tng_util_non_particle_data_next_frame_read of the
 * box shape and tng_util_particle_data_next_frame_read of the positions, the
 * calls and the order GROMACS's read_next_tng_frame makes (the library reads
 * the frame set of a frame on its first access and reallocates the caller's
 * buffers), or all frames at once, tng_util_pos_read and
 * tng_util_box_shape_read.  Positions and box are binary32 nm.  The reader
 * takes no thread count.
 */
#include "bf_driver.h"

#include "tng/tng_io.h"

int main(int argc, char **argv) {
    BfRun run;
    bf_args(argc, argv, &run);
    bf_single_thread(&run);

    double t0 = bf_now();
    tng_trajectory_t traj = NULL;
    if (tng_util_trajectory_open(run.path, 'r', &traj) != TNG_SUCCESS) bf_die("tng_util_trajectory_open failed");
    int64_t particles = 0, frames = 0;
    if (tng_num_particles_get(traj, &particles) != TNG_SUCCESS || particles < 1 ||
        tng_num_frames_get(traj, &frames) != TNG_SUCCESS || frames < 1) {
        bf_die("tng_num_particles_get or tng_num_frames_get failed");
    }
    if (run.mode == BF_FRAMES_MODE) {
        float *positions = NULL, *shape = NULL;
        for (int64_t f = 0; f < frames; f++) {
            char type = 0, box_type = 0;
            int64_t number = 0, box_number = 0;
            double time = 0, box_time = 0;
            if (tng_util_non_particle_data_next_frame_read(traj, TNG_TRAJ_BOX_SHAPE, (void **)&shape, &box_type,
                                                           &box_number, &box_time) != TNG_SUCCESS ||
                tng_util_particle_data_next_frame_read(traj, TNG_TRAJ_POSITIONS, (void **)&positions, &type, &number,
                                                       &time) != TNG_SUCCESS) {
                bf_die("tng next frame read failed");
            }
            if (type != TNG_FLOAT_DATA || box_type != TNG_FLOAT_DATA || number != f || box_number != f) {
                bf_die("unexpected TNG frame");
            }
            double lengths[3] = {shape[0], shape[4], shape[8]};
            bf_frame_xyz(&run, positions, particles, lengths, 10.0);
        }
        free(positions);
        free(shape);
    } else {
        float *positions = NULL, *shape = NULL;
        int64_t stride = 0, box_stride = 0;
        if (tng_util_pos_read(traj, &positions, &stride) != TNG_SUCCESS ||
            tng_util_box_shape_read(traj, &shape, &box_stride) != TNG_SUCCESS || stride != 1 || box_stride != 1) {
            bf_die("tng_util_pos_read or tng_util_box_shape_read failed");
        }
        for (int64_t f = 0; f < frames; f++) {
            const float *s = shape + 9 * f;
            double lengths[3] = {s[0], s[4], s[8]};
            bf_frame_xyz(&run, positions + 3 * particles * f, particles, lengths, 10.0);
        }
        free(positions);
        free(shape);
    }
    if (tng_util_trajectory_close(&traj) != TNG_SUCCESS) bf_die("tng_util_trajectory_close failed");
    bf_report(&run, bf_now() - t0);
    return 0;
}
