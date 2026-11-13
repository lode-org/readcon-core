/* XTC or TRR, by the file suffix, through xdrfile 1.1.4: read_xtc_natoms or
 * read_trr_natoms, then read_xtc or read_trr for every frame into binary32
 * positions and box in nm.  TRR files hold positions and box only, so the
 * velocity and force pointers are NULL.  At the end of the file read_xtc
 * returns exdrENDOFFILE and read_trr exdrINT; any other code is an error.
 */
#include "bf_driver.h"

#include "xdrfile.h"
#include "xdrfile_trr.h"
#include "xdrfile_xtc.h"

static int read_frame(XDRFILE *xd, int trr, int natoms, matrix box, rvec *x) {
    int step;
    float time, lambda, precision;
    int rc = trr ? read_trr(xd, natoms, &step, &time, &lambda, box, x, NULL, NULL)
                 : read_xtc(xd, natoms, &step, &time, box, x, &precision);
    if (rc == exdrOK) return 1;
    if (rc != (trr ? exdrINT : exdrENDOFFILE)) bf_die("read_xtc or read_trr failed");
    return 0;
}

int main(int argc, char **argv) {
    BfRun run;
    bf_args(argc, argv, &run);
    bf_single_thread(&run);
    size_t len = strlen(run.path);
    int trr = len > 4 && strcmp(run.path + len - 4, ".trr") == 0;

    double t0 = bf_now();
    char *name = strdup(run.path);
    int natoms = 0;
    if ((trr ? read_trr_natoms(name, &natoms) : read_xtc_natoms(name, &natoms)) != exdrOK || natoms < 1) {
        bf_die("read_xtc_natoms or read_trr_natoms failed");
    }
    XDRFILE *xd = xdrfile_open(name, "r");
    if (!xd) bf_die("xdrfile_open failed");
    matrix box;
    if (run.mode == BF_FRAMES_MODE) {
        rvec *x = (rvec *)malloc((size_t)natoms * sizeof(rvec));
        if (!x) bf_die("out of memory");
        while (read_frame(xd, trr, natoms, box, x)) {
            double lengths[3] = {box[0][0], box[1][1], box[2][2]};
            bf_frame_xyz(&run, &x[0][0], natoms, lengths, 10.0);
        }
        free(x);
    } else {
        size_t held = 0, cap = 16;
        rvec **frames = (rvec **)malloc(cap * sizeof *frames);
        double *lengths = (double *)malloc(cap * 3 * sizeof *lengths);
        for (;;) {
            rvec *x = (rvec *)malloc((size_t)natoms * sizeof(rvec));
            if (!x || !frames || !lengths) bf_die("out of memory");
            if (!read_frame(xd, trr, natoms, box, x)) {
                free(x);
                break;
            }
            if (held == cap) {
                cap *= 2;
                frames = (rvec **)realloc(frames, cap * sizeof *frames);
                lengths = (double *)realloc(lengths, cap * 3 * sizeof *lengths);
                if (!frames || !lengths) bf_die("out of memory");
            }
            frames[held] = x;
            for (int k = 0; k < 3; k++) lengths[3 * held + k] = box[k][k];
            held++;
        }
        for (size_t f = 0; f < held; f++) bf_frame_xyz(&run, &frames[f][0][0], natoms, &lengths[3 * f], 10.0);
        for (size_t f = 0; f < held; f++) free(frames[f]);
        free(frames);
        free(lengths);
    }
    xdrfile_close(xd);
    free(name);
    bf_report(&run, bf_now() - t0);
    return 0;
}
