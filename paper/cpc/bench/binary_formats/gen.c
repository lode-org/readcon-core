/* Write the source system of system.h once in binary64 and once through the
 * writer of each binary format:
 *
 *   gen OUTDIR
 *
 *   reference.f64      positions, (frames, atoms, 3) little-endian binary64, angstrom
 *   reference_box.f64  box lengths, (frames, 3) binary64, angstrom
 *   traj.xtc           xdrfile write_xtc, nm, precision 1000 (0.001 nm)
 *   traj.trr           xdrfile write_trr, positions and box only, nm, binary32
 *   traj.dcd           molfile write_dcdheader and write_dcdstep, angstrom,
 *                      binary32, CHARMM unit cell (A, gamma, B, beta, alpha, C)
 *   traj.tng           tng_util_pos_write and tng_util_box_shape_write, nm,
 *                      TNG compression at precision 0.001 nm, the default
 *                      frame set of 100 frames, so one frame set holds every
 *                      frame; molecules of one Cu atom and of one H atom,
 *                      BF_NATOMS / 2 of each
 *   traj_two_sets.tng  the same in frame sets of BF_FRAMES / 2 frames
 *
 * The CON files are written from reference.f64 by the readcon-core writer
 * (readcon_read.rs), so every format starts from the same binary64 values.
 * TNG stores the creation time of the file; the build wraps time() to return
 * 0 so that two runs write the same bytes.
 */
#include "system.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "readdcd.h"
#include "tng/tng_io.h"
#include "xdrfile.h"
#include "xdrfile_trr.h"
#include "xdrfile_xtc.h"

#if BF_NATOMS % 2
#error "the Cu and H halves need an even atom count"
#endif
#if BF_FRAMES < 2 || BF_FRAMES % 2 || BF_FRAMES > 100
#error "traj.tng needs one frame set of at most 100 frames and traj_two_sets.tng two equal ones"
#endif

time_t __wrap_time(time_t *out) {
    if (out) *out = 0;
    return 0;
}

static void die(const char *what) {
    fprintf(stderr, "gen: %s\n", what);
    exit(1);
}

static char *join(const char *dir, const char *name) {
    size_t n = strlen(dir) + strlen(name) + 2;
    char *path = (char *)malloc(n);
    if (!path) die("out of memory");
    snprintf(path, n, "%s/%s", dir, name);
    return path;
}

static FILE *open_out(const char *dir, const char *name) {
    char *path = join(dir, name);
    FILE *fp = fopen(path, "wb");
    if (!fp) die(path);
    free(path);
    return fp;
}

/* frames_per_set 0 keeps the library default. */
static tng_trajectory_t open_tng(const char *dir, const char *name, int64_t frames_per_set) {
    char *path = join(dir, name);
    tng_trajectory_t tng = NULL;
    if (tng_util_trajectory_open(path, 'w', &tng) != TNG_SUCCESS) die("tng_util_trajectory_open");
    free(path);
    const char *names[2] = {"Cu", "H"};
    for (int s = 0; s < 2; s++) {
        tng_molecule_t molecule;
        tng_chain_t chain;
        tng_residue_t residue;
        tng_atom_t atom;
        if (tng_molecule_add(tng, names[s], &molecule) != TNG_SUCCESS ||
            tng_molecule_chain_add(tng, molecule, "A", &chain) != TNG_SUCCESS ||
            tng_chain_residue_add(tng, chain, names[s], &residue) != TNG_SUCCESS ||
            tng_residue_atom_add(tng, residue, names[s], names[s], &atom) != TNG_SUCCESS ||
            tng_molecule_cnt_set(tng, molecule, BF_NATOMS / 2) != TNG_SUCCESS) {
            die("tng topology");
        }
    }
    /* The argument is the multiplier, 1 / precision in nm, as tng_io.c uses it;
     * 1000 is its default, whatever the comment in tng_io.h says. */
    if (tng_compression_precision_set(tng, 1000.0) != TNG_SUCCESS ||
        tng_util_pos_write_interval_set(tng, 1) != TNG_SUCCESS ||
        tng_util_box_shape_write_interval_set(tng, 1) != TNG_SUCCESS ||
        (frames_per_set && tng_num_frames_per_frame_set_set(tng, frames_per_set) != TNG_SUCCESS)) {
        die("tng settings");
    }
    return tng;
}

static void write_tng(tng_trajectory_t tng, int frame, const float shape[9], const float *nm) {
    if (tng_util_box_shape_write(tng, frame, shape) != TNG_SUCCESS) die("tng_util_box_shape_write");
    if (tng_util_pos_write(tng, frame, nm) != TNG_SUCCESS) die("tng_util_pos_write");
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s OUTDIR\n", argv[0]);
        return 2;
    }
    const char *dir = argv[1];
    const int64_t n = BF_NATOMS;

    FILE *ref = open_out(dir, "reference.f64");
    FILE *ref_box = open_out(dir, "reference_box.f64");

    char *path = join(dir, "traj.xtc");
    XDRFILE *xtc = xdrfile_open(path, "w");
    free(path);
    path = join(dir, "traj.trr");
    XDRFILE *trr = xdrfile_open(path, "w");
    free(path);
    if (!xtc || !trr) die("xdrfile_open");

    path = join(dir, "traj.dcd");
    fio_fd dcd;
    if (fio_open(path, FIO_WRITE, &dcd) != 0) die("fio_open dcd");
    free(path);
    if (write_dcdheader(dcd, "binary_formats source system", (int)n, 0, 1, 1.0, 1, 1) != DCD_SUCCESS) {
        die("write_dcdheader");
    }

    tng_trajectory_t tng = open_tng(dir, "traj.tng", 0);
    tng_trajectory_t tng_sets = open_tng(dir, "traj_two_sets.tng", BF_FRAMES / 2);

    double *pos = (double *)malloc((size_t)n * 3 * sizeof(double));
    rvec *nm = (rvec *)malloc((size_t)n * sizeof(rvec));
    float *x = (float *)malloc((size_t)n * sizeof(float));
    float *y = (float *)malloc((size_t)n * sizeof(float));
    float *z = (float *)malloc((size_t)n * sizeof(float));
    if (!pos || !nm || !x || !y || !z) die("out of memory");

    for (int f = 0; f < BF_FRAMES; f++) {
        double box[3];
        bf_box(f, box);
        for (int64_t i = 0; i < n; i++) {
            double r[3];
            bf_position(f, i, box, r);
            for (int k = 0; k < 3; k++) {
                pos[3 * i + k] = r[k];
                nm[i][k] = (float)(r[k] / 10.0);
            }
            x[i] = (float)r[0];
            y[i] = (float)r[1];
            z[i] = (float)r[2];
        }
        if (fwrite(pos, sizeof(double), (size_t)(3 * n), ref) != (size_t)(3 * n) ||
            fwrite(box, sizeof(double), 3, ref_box) != 3) {
            die("reference write");
        }

        matrix m;
        memset(m, 0, sizeof m);
        for (int k = 0; k < 3; k++) m[k][k] = (float)(box[k] / 10.0);
        if (write_xtc(xtc, (int)n, f, (float)f, m, nm, 1000.0f) != exdrOK) die("write_xtc");
        if (write_trr(trr, (int)n, f, (float)f, 0.0f, m, nm, NULL, NULL) != exdrOK) die("write_trr");

        double cell[6] = {box[0], 90.0, box[1], 90.0, 90.0, box[2]};
        if (write_dcdstep(dcd, f + 1, f + 1, (int)n, x, y, z, cell, 1) != DCD_SUCCESS) die("write_dcdstep");

        float shape[9] = {0};
        for (int k = 0; k < 3; k++) shape[4 * k] = (float)(box[k] / 10.0);
        write_tng(tng, f, shape, &nm[0][0]);
        write_tng(tng_sets, f, shape, &nm[0][0]);
    }

    if (fclose(ref) != 0 || fclose(ref_box) != 0) die("reference close");
    xdrfile_close(xtc);
    xdrfile_close(trr);
    fio_fclose(dcd);
    if (tng_util_trajectory_close(&tng) != TNG_SUCCESS || tng_util_trajectory_close(&tng_sets) != TNG_SUCCESS) {
        die("tng_util_trajectory_close");
    }
    free(pos);
    free(nm);
    free(x);
    free(y);
    free(z);
    return 0;
}
