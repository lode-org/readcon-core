/*
 * Minimal standalone CON file reader for benchmarking.
 * Replicates the parsing logic from eOn's ConFileIO.cpp without
 * depending on Matter, Eigen, or any eOn infrastructure.
 *
 * Build: cc -O2 -o bench_con_reader bench_con_reader.c -lm
 * Usage: ./bench_con_reader <file.con> [repeat]
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAXC 100
#define MAX_LINE 512

typedef struct {
    double x, y, z;
    int fixed;
    long atom_id;
    double mass;
    char symbol[4];
} Atom;

typedef struct {
    double cell[3];
    double angles[3];
    Atom *atoms;
    int n_atoms;
    int n_types;
} Frame;

static int read_frame(FILE *f, Frame *frame) {
    char line[MAX_LINE];

    /* Line 1: comment */
    if (!fgets(line, sizeof(line), f)) return 0;
    /* Line 2: comment/JSON */
    if (!fgets(line, sizeof(line), f)) return 0;
    /* Line 3: cell */
    if (!fgets(line, sizeof(line), f)) return 0;
    sscanf(line, "%lf %lf %lf", &frame->cell[0], &frame->cell[1], &frame->cell[2]);
    /* Line 4: angles */
    if (!fgets(line, sizeof(line), f)) return 0;
    sscanf(line, "%lf %lf %lf", &frame->angles[0], &frame->angles[1], &frame->angles[2]);
    /* Line 5-6: comments */
    if (!fgets(line, sizeof(line), f)) return 0;
    if (!fgets(line, sizeof(line), f)) return 0;
    /* Line 7: n_types */
    if (!fgets(line, sizeof(line), f)) return 0;
    sscanf(line, "%d", &frame->n_types);
    if (frame->n_types > MAXC || frame->n_types < 1) return 0;

    /* Line 8: atoms per type */
    int counts[MAXC];
    int total = 0;
    if (!fgets(line, sizeof(line), f)) return 0;
    char *tok = strtok(line, " \t\n");
    for (int i = 0; i < frame->n_types; i++) {
        if (!tok) return 0;
        counts[i] = atoi(tok);
        total += counts[i];
        tok = strtok(NULL, " \t\n");
    }

    /* Line 9: masses per type */
    double masses[MAXC];
    if (!fgets(line, sizeof(line), f)) return 0;
    tok = strtok(line, " \t\n");
    for (int i = 0; i < frame->n_types; i++) {
        if (!tok) return 0;
        masses[i] = atof(tok);
        tok = strtok(NULL, " \t\n");
    }

    /* Allocate atoms */
    frame->n_atoms = total;
    frame->atoms = (Atom *)malloc(total * sizeof(Atom));
    if (!frame->atoms) return 0;

    /* Read coordinate blocks */
    int idx = 0;
    for (int t = 0; t < frame->n_types; t++) {
        /* Symbol line */
        if (!fgets(line, sizeof(line), f)) { free(frame->atoms); return 0; }
        char sym[4];
        sscanf(line, "%3s", sym);
        /* Component header */
        if (!fgets(line, sizeof(line), f)) { free(frame->atoms); return 0; }
        /* Atom lines */
        for (int a = 0; a < counts[t]; a++) {
            if (!fgets(line, sizeof(line), f)) { free(frame->atoms); return 0; }
            Atom *at = &frame->atoms[idx];
            at->atom_id = idx;
            sscanf(line, "%lf %lf %lf %d %ld",
                   &at->x, &at->y, &at->z, &at->fixed, &at->atom_id);
            at->mass = masses[t];
            strncpy(at->symbol, sym, 3);
            at->symbol[3] = '\0';
            idx++;
        }
    }

    return 1;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <file.con> [repeat]\n", argv[0]);
        return 1;
    }

    int repeat = 5;
    if (argc > 2) repeat = atoi(argv[2]);

    /* Warm-up: read once */
    {
        FILE *f = fopen(argv[1], "r");
        if (!f) { perror("fopen"); return 1; }
        Frame frame;
        int count = 0;
        while (read_frame(f, &frame)) {
            free(frame.atoms);
            count++;
        }
        fclose(f);
        fprintf(stderr, "Frames: %d\n", count);
    }

    /* Timed runs */
    double best = 1e9;
    for (int r = 0; r < repeat; r++) {
        FILE *f = fopen(argv[1], "r");
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);

        Frame frame;
        int count = 0;
        while (read_frame(f, &frame)) {
            free(frame.atoms);
            count++;
        }

        clock_gettime(CLOCK_MONOTONIC, &t1);
        fclose(f);

        double ms = (t1.tv_sec - t0.tv_sec) * 1000.0
                   + (t1.tv_nsec - t0.tv_nsec) / 1e6;
        if (ms < best) best = ms;
    }

    printf("%.2f ms (best of %d runs)\n", best, repeat);
    return 0;
}
