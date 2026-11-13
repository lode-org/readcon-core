/* DCD through the VMD molfile reader that MDAnalysis vendors as readdcd.h:
 * read_dcdheader, then read_dcdstep for each of the NSET frames the header
 * stores, into binary32 X, Y and Z arrays in angstrom and the six CHARMM
 * unit-cell doubles A, gamma, B, beta, alpha, C.
 */
#include "bf_driver.h"

#include "readdcd.h"

typedef struct {
    float *x, *y, *z;
} Coords;

static Coords coords_new(int natoms) {
    Coords c = {(float *)malloc((size_t)natoms * sizeof(float)), (float *)malloc((size_t)natoms * sizeof(float)),
                (float *)malloc((size_t)natoms * sizeof(float))};
    if (!c.x || !c.y || !c.z) bf_die("out of memory");
    return c;
}

static void coords_free(Coords *c) {
    free(c->x);
    free(c->y);
    free(c->z);
}

int main(int argc, char **argv) {
    BfRun run;
    bf_args(argc, argv, &run);
    bf_single_thread(&run);

    double t0 = bf_now();
    fio_fd fd;
    if (fio_open(run.path, FIO_READ, &fd) != 0) bf_die("fio_open failed");
    int natoms = 0, nsets = 0, istart = 0, nsavc = 0, nfixed = 0, reverse = 0, charmm = 0, remarks_len = 0;
    int *freeind = NULL;
    float *fixedcoords = NULL;
    double delta = 0;
    char *remarks = NULL;
    if (read_dcdheader(fd, &natoms, &nsets, &istart, &nsavc, &delta, &nfixed, &freeind, &fixedcoords, &reverse,
                       &charmm, &remarks, &remarks_len) != DCD_SUCCESS || natoms < 1 || nsets < 1) {
        bf_die("read_dcdheader failed");
    }
    double cell[6];
    if (run.mode == BF_FRAMES_MODE) {
        Coords c = coords_new(natoms);
        for (int f = 0; f < nsets; f++) {
            if (read_dcdstep(fd, natoms, c.x, c.y, c.z, cell, nfixed, f == 0, freeind, fixedcoords, reverse,
                             charmm) != DCD_SUCCESS) {
                bf_die("read_dcdstep failed");
            }
            double lengths[3] = {cell[0], cell[2], cell[5]};
            bf_frame_split(&run, c.x, c.y, c.z, natoms, lengths, 1.0);
        }
        coords_free(&c);
    } else {
        Coords *frames = (Coords *)malloc((size_t)nsets * sizeof *frames);
        double *lengths = (double *)malloc((size_t)nsets * 3 * sizeof *lengths);
        if (!frames || !lengths) bf_die("out of memory");
        for (int f = 0; f < nsets; f++) {
            frames[f] = coords_new(natoms);
            if (read_dcdstep(fd, natoms, frames[f].x, frames[f].y, frames[f].z, cell, nfixed, f == 0, freeind,
                             fixedcoords, reverse, charmm) != DCD_SUCCESS) {
                bf_die("read_dcdstep failed");
            }
            lengths[3 * f] = cell[0];
            lengths[3 * f + 1] = cell[2];
            lengths[3 * f + 2] = cell[5];
        }
        for (int f = 0; f < nsets; f++) {
            bf_frame_split(&run, frames[f].x, frames[f].y, frames[f].z, natoms, &lengths[3 * f], 1.0);
        }
        for (int f = 0; f < nsets; f++) coords_free(&frames[f]);
        free(frames);
        free(lengths);
    }
    close_dcd_read(freeind, fixedcoords);
    free(remarks);
    fio_fclose(fd);
    bf_report(&run, bf_now() - t0);
    return 0;
}
