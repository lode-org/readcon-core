/* Copyright (c) readcon developers */
#define _POSIX_C_SOURCE 199309L

/*
 * eOn-style coordinate reader.
 *
 * The line loop follows client/ConFileIO.cpp as exercised by
 * addl/referenceImpls/eon_cpp/bench_con_reader.c: nine header lines, then
 * one symbol line, one component line, and one coordinate line per atom.
 * It does not read a velocity block. One sample is one pass over the file
 * on this thread. The clock wraps that pass and a mix of every stored
 * coordinate, mass, and cell number.
 *
 * Build: cc -O3 -std=c11 -o eon_style_read eon_style_read.c -lm
 * Usage: eon_style_read PATH REPEATS
 */

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_TYPES 64
#define MAX_LINE 8192

static uint64_t mix(uint64_t acc, uint64_t bits) {
    return acc * 0x9E3779B97F4A7C15ull + bits;
}

static uint64_t bits_of(double value) {
    uint64_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static int read_line(FILE *file, char *line) {
    if (!fgets(line, MAX_LINE, file)) {
        return 0;
    }
    if (strchr(line, '\n') == NULL && !feof(file)) {
        fprintf(stderr, "line longer than %d\n", MAX_LINE);
        return -1;
    }
    return 1;
}

typedef struct {
    double *xyz;
    double *mass;
    double *cell;
    size_t xyz_n, xyz_cap;
    size_t mass_n, mass_cap;
    size_t cell_n, cell_cap;
} Store;

static int push(double **data, size_t *n, size_t *cap, double value) {
    if (*n == *cap) {
        size_t next = *cap ? *cap * 2 : 64;
        double *grown = realloc(*data, next * sizeof(double));
        if (!grown) {
            return -1;
        }
        *data = grown;
        *cap = next;
    }
    (*data)[*n] = value;
    *n += 1;
    return 0;
}

/* Returns 1 on a frame, 0 on a clean end, -1 on a short or rejected frame.
 * Coordinates, masses, and the cell are stored, then mixed from that store
 * so the timed work keeps the frame. */
static int read_frame(FILE *file, Store *store, uint64_t *pos, uint64_t *mass,
                      uint64_t *cell, int *atoms) {
    char line[MAX_LINE];
    int status;
    double box[3], angles[3], masses[MAX_TYPES];
    int counts[MAX_TYPES];
    int n_types, total, type, atom;

    /* Lines 1 and 2 are comments. Line 7 is the type count. */
    status = read_line(file, line);
    if (status == 0) {
        return 0;
    }
    if (status < 0 || read_line(file, line) != 1) {
        return -1;
    }
    if (read_line(file, line) != 1 ||
        sscanf(line, "%lf %lf %lf", &box[0], &box[1], &box[2]) != 3) {
        return -1;
    }
    if (read_line(file, line) != 1 ||
        sscanf(line, "%lf %lf %lf", &angles[0], &angles[1], &angles[2]) != 3) {
        return -1;
    }
    if (read_line(file, line) != 1 || read_line(file, line) != 1) {
        return -1;
    }
    if (read_line(file, line) != 1 ||
        sscanf(line, "%d", &n_types) != 1 || n_types < 1 || n_types > MAX_TYPES) {
        return -1;
    }
    if (read_line(file, line) != 1) {
        return -1;
    }
    {
        char *tok = strtok(line, " \t\r\n");
        total = 0;
        for (type = 0; type < n_types; type++) {
            if (!tok) {
                return -1;
            }
            counts[type] = atoi(tok);
            if (counts[type] < 1) {
                return -1;
            }
            total += counts[type];
            tok = strtok(NULL, " \t\r\n");
        }
    }
    if (read_line(file, line) != 1) {
        return -1;
    }
    {
        char *tok = strtok(line, " \t\r\n");
        for (type = 0; type < n_types; type++) {
            if (!tok) {
                return -1;
            }
            masses[type] = atof(tok);
            tok = strtok(NULL, " \t\r\n");
        }
    }
    for (type = 0; type < n_types; type++) {
        if (read_line(file, line) != 1 || read_line(file, line) != 1) {
            return -1;
        }
        for (atom = 0; atom < counts[type]; atom++) {
            double x, y, z;
            if (read_line(file, line) != 1) {
                return -1;
            }
            if (sscanf(line, "%lf %lf %lf", &x, &y, &z) != 3) {
                return -1;
            }
            if (push(&store->xyz, &store->xyz_n, &store->xyz_cap, x) ||
                push(&store->xyz, &store->xyz_n, &store->xyz_cap, y) ||
                push(&store->xyz, &store->xyz_n, &store->xyz_cap, z)) {
                return -1;
            }
        }
        if (push(&store->mass, &store->mass_n, &store->mass_cap, masses[type])) {
            return -1;
        }
    }
    for (int i = 0; i < 3; i++) {
        if (push(&store->cell, &store->cell_n, &store->cell_cap, box[i])) {
            return -1;
        }
    }
    for (int i = 0; i < 3; i++) {
        if (push(&store->cell, &store->cell_n, &store->cell_cap, angles[i])) {
            return -1;
        }
    }
    {
        size_t xyz_begin = store->xyz_n - (size_t)total * 3;
        size_t mass_begin = store->mass_n - (size_t)n_types;
        size_t cell_begin = store->cell_n - 6;
        for (size_t i = xyz_begin; i < store->xyz_n; i++) {
            *pos = mix(*pos, bits_of(store->xyz[i]));
        }
        for (size_t i = mass_begin; i < store->mass_n; i++) {
            *mass = mix(*mass, bits_of(store->mass[i]));
        }
        for (size_t i = cell_begin; i < store->cell_n; i++) {
            *cell = mix(*cell, bits_of(store->cell[i]));
        }
    }
    *atoms += total;
    return 1;
}

static int pass(const char *path, double *seconds, int *frames, int *atoms,
                uint64_t *pos, uint64_t *mass, uint64_t *cell) {
    struct timespec start, stop;
    FILE *file = fopen(path, "r");
    Store store;
    int count = 0;
    memset(&store, 0, sizeof(store));
    if (!file) {
        perror("fopen");
        return -1;
    }
    *pos = 0;
    *mass = 0;
    *cell = 0;
    *atoms = 0;
    clock_gettime(CLOCK_MONOTONIC, &start);
    for (;;) {
        int status = read_frame(file, &store, pos, mass, cell, atoms);
        if (status == 0) {
            break;
        }
        if (status < 0) {
            clock_gettime(CLOCK_MONOTONIC, &stop);
            free(store.xyz);
            free(store.mass);
            free(store.cell);
            fclose(file);
            return -1;
        }
        count++;
    }
    clock_gettime(CLOCK_MONOTONIC, &stop);
    free(store.xyz);
    free(store.mass);
    free(store.cell);
    fclose(file);
    *seconds = (double)(stop.tv_sec - start.tv_sec) +
               (double)(stop.tv_nsec - start.tv_nsec) / 1e9;
    *frames = count;
    return 0;
}

int main(int argc, char **argv) {
    int repeats, sample, frames, atoms;
    double seconds;
    uint64_t pos, mass, cell;
    if (argc != 3) {
        fprintf(stderr, "usage: %s PATH REPEATS\n", argv[0]);
        return 2;
    }
    repeats = atoi(argv[2]);
    if (repeats < 1) {
        fprintf(stderr, "repeats\n");
        return 2;
    }
    if (pass(argv[1], &seconds, &frames, &atoms, &pos, &mass, &cell) != 0) {
        fprintf(stderr, "warm read failed\n");
        return 1;
    }
    for (sample = 0; sample < repeats; sample++) {
        if (pass(argv[1], &seconds, &frames, &atoms, &pos, &mass, &cell) != 0) {
            fprintf(stderr, "read failed\n");
            return 1;
        }
        printf(
            "sample kind=eon-c seconds=%.9f frames=%d atoms=%d pos=%llu vel=0 mass=%llu cell=%llu\n",
            seconds, frames, atoms, (unsigned long long)pos,
            (unsigned long long)mass, (unsigned long long)cell);
    }
    return 0;
}
