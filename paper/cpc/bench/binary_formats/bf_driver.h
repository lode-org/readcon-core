/* Command line, clock and output of the native read drivers.
 *
 *   DRIVER time MODE THREADS PATH
 *   DRIVER dump MODE THREADS PATH POSITIONS BOX
 *
 * MODE is "frames" (one frame at a time, the buffer reused for the next one)
 * or "all" (every frame in its own buffer, all held until the read ends).
 * "time" prints the seconds from open to release, the frame and atom counts
 * and a checksum: per frame, the first and last x coordinate and the first
 * box length the reader returned, in the units of the file.  "dump" does the
 * same read untimed and writes every position and the three box lengths of
 * every frame as little-endian binary64 in angstrom, for the check of
 * binary_formats.py.
 */
#ifndef BF_DRIVER_H
#define BF_DRIVER_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { BF_FRAMES_MODE = 0, BF_ALL_MODE = 1 };

typedef struct {
    int dump;
    int mode;
    int threads;
    const char *path;
    FILE *positions;
    FILE *box;
    int frames;
    int64_t atoms;
    double checksum;
    double *scratch;
} BfRun;

static void bf_die(const char *what) {
    fprintf(stderr, "%s\n", what);
    exit(1);
}

static double bf_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
}

static void bf_args(int argc, char **argv, BfRun *run) {
    memset(run, 0, sizeof *run);
    if (argc < 5) {
        fprintf(stderr, "usage: %s time|dump frames|all THREADS PATH [POSITIONS BOX]\n", argv[0]);
        exit(2);
    }
    run->dump = strcmp(argv[1], "dump") == 0;
    if (!run->dump && strcmp(argv[1], "time") != 0) bf_die("command is time or dump");
    if (strcmp(argv[2], "frames") == 0) {
        run->mode = BF_FRAMES_MODE;
    } else if (strcmp(argv[2], "all") == 0) {
        run->mode = BF_ALL_MODE;
    } else {
        bf_die("mode is frames or all");
    }
    run->threads = atoi(argv[3]);
    if (run->threads < 1) bf_die("threads must be at least 1");
    run->path = argv[4];
    if (run->dump) {
        if (argc != 7) bf_die("dump takes POSITIONS and BOX paths");
        run->positions = fopen(argv[5], "wb");
        run->box = fopen(argv[6], "wb");
        if (!run->positions || !run->box) bf_die("cannot open the dump files");
    } else if (argc != 5) {
        bf_die("time takes no output paths");
    }
}

/* A reader without a thread argument refuses any other count. */
static void bf_single_thread(const BfRun *run) {
    if (run->threads != 1) bf_die("this reader takes no thread count");
}

/* Interleaved xyz with `scale` angstrom per file unit; box lengths in file units. */
static void bf_frame_xyz(BfRun *run, const float *xyz, int64_t atoms, const double box[3], double scale) {
    if (run->frames == 0) run->atoms = atoms;
    if (atoms != run->atoms) bf_die("the atom count changed between frames");
    run->checksum += (double)xyz[0] + (double)xyz[3 * (atoms - 1)] + box[0];
    run->frames++;
    if (!run->dump) return;
    if (!run->scratch) run->scratch = (double *)malloc((size_t)atoms * 3 * sizeof(double));
    if (!run->scratch) bf_die("out of memory");
    for (int64_t i = 0; i < 3 * atoms; i++) run->scratch[i] = scale * (double)xyz[i];
    double lengths[3] = {scale * box[0], scale * box[1], scale * box[2]};
    if (fwrite(run->scratch, sizeof(double), (size_t)(3 * atoms), run->positions) != (size_t)(3 * atoms) ||
        fwrite(lengths, sizeof(double), 3, run->box) != 3) {
        bf_die("dump write failed");
    }
}

/* Separate x, y and z arrays, as DCD stores them. */
static void bf_frame_split(BfRun *run, const float *x, const float *y, const float *z, int64_t atoms,
                           const double box[3], double scale) {
    if (run->frames == 0) run->atoms = atoms;
    if (atoms != run->atoms) bf_die("the atom count changed between frames");
    run->checksum += (double)x[0] + (double)x[atoms - 1] + box[0];
    run->frames++;
    if (!run->dump) return;
    if (!run->scratch) run->scratch = (double *)malloc((size_t)atoms * 3 * sizeof(double));
    if (!run->scratch) bf_die("out of memory");
    for (int64_t i = 0; i < atoms; i++) {
        run->scratch[3 * i] = scale * (double)x[i];
        run->scratch[3 * i + 1] = scale * (double)y[i];
        run->scratch[3 * i + 2] = scale * (double)z[i];
    }
    double lengths[3] = {scale * box[0], scale * box[1], scale * box[2]};
    if (fwrite(run->scratch, sizeof(double), (size_t)(3 * atoms), run->positions) != (size_t)(3 * atoms) ||
        fwrite(lengths, sizeof(double), 3, run->box) != 3) {
        bf_die("dump write failed");
    }
}

static void bf_report(BfRun *run, double seconds) {
    if (run->dump) {
        if (fclose(run->positions) != 0 || fclose(run->box) != 0) bf_die("dump close failed");
        free(run->scratch);
    }
    printf("seconds %.9f\nframes %d\natoms %lld\nchecksum %.17g\n", seconds, run->frames,
           (long long)run->atoms, run->checksum);
}

#endif
