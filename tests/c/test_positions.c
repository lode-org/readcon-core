/*
 * Column-walker coordinates against rkr_read_all_frames.
 * Usage: test_positions <repo root>
 *
 * Files larger than 256 KiB are left to the Rust corpus test. Valgrind
 * runs this binary.
 */
#include "readcon-core.h"

#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static int failures = 0;
#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, \
                    #cond);                                                  \
            failures++;                                                      \
        }                                                                    \
    } while (0)

static char *copy_error(void) {
    const char *msg = rkr_last_error_message();
    return msg == NULL ? NULL : strdup(msg);
}

static int uniform_atoms(struct RKRConFrame **frames, uintptr_t nframes, uintptr_t *n_atoms) {
    uintptr_t i;
    uintptr_t first = 0;
    for (i = 0; i < nframes; i++) {
        uintptr_t n = 0;
        const double *xyz = rkr_frame_xyz_f64(frames[i], &n);
        if (n > 0 && xyz == NULL) {
            return -1;
        }
        if (i == 0) {
            first = n;
        } else if (n != first) {
            return 0;
        }
    }
    *n_atoms = first;
    return 1;
}

static void check_file(const char *path) {
    uintptr_t nframes = 0;
    uintptr_t natoms = 0;
    uintptr_t got_frames = 0;
    uintptr_t got_atoms = 0;
    struct RKRConFrame **frames = rkr_read_all_frames(path, &nframes);
    if (frames == NULL) {
        char *want = copy_error();
        struct RKRPositionBlock *block = rkr_read_positions(path, &got_frames, &got_atoms);
        const char *got = rkr_last_error_message();
        CHECK(block == NULL);
        CHECK(want != NULL && got != NULL && strcmp(want, got) == 0);
        free(want);
        return;
    }
    int shape = uniform_atoms(frames, nframes, &natoms);
    if (shape < 0) {
        CHECK(0);
        free_rkr_frame_array(frames, nframes);
        return;
    }
    if (shape == 0) {
        struct RKRPositionBlock *block = rkr_read_positions(path, &got_frames, &got_atoms);
        const char *got = rkr_last_error_message();
        CHECK(block == NULL);
        CHECK(got != NULL && strstr(got, "frame atom count does not match") != NULL);
        free_rkr_frame_array(frames, nframes);
        return;
    }
    struct RKRPositionBlock *block = rkr_read_positions(path, &got_frames, &got_atoms);
    if (block == NULL) {
        CHECK(0);
        free_rkr_frame_array(frames, nframes);
        return;
    }
    CHECK(got_frames == nframes);
    CHECK(got_atoms == natoms);
    const double *vals = rkr_position_block_values(block);
    uintptr_t i;
    uintptr_t at = 0;
    for (i = 0; i < nframes; i++) {
        uintptr_t n = 0;
        const double *xyz = rkr_frame_xyz_f64(frames[i], &n);
        if (n == 0) {
            continue;
        }
        CHECK(xyz != NULL);
        CHECK(memcmp(vals + at, xyz, n * 3 * sizeof(double)) == 0);
        at += n * 3;
    }
    CHECK(at == got_frames * got_atoms * 3);
    rkr_free_position_block(block);
    free_rkr_frame_array(frames, nframes);
}

static int ends_with(const char *name, const char *suffix) {
    size_t n = strlen(name);
    size_t s = strlen(suffix);
    return n >= s && strcmp(name + n - s, suffix) == 0;
}

static void walk(const char *dir) {
    DIR *handle = opendir(dir);
    struct dirent *entry;
    if (handle == NULL) {
        return;
    }
    while ((entry = readdir(handle)) != NULL) {
        char path[4096];
        struct stat st;
        if (entry->d_name[0] == '.') {
            continue;
        }
        snprintf(path, sizeof path, "%s/%s", dir, entry->d_name);
        if (stat(path, &st) != 0) {
            continue;
        }
        if (S_ISDIR(st.st_mode)) {
            walk(path);
            continue;
        }
        if (!S_ISREG(st.st_mode)) {
            continue;
        }
        if (st.st_size > 256 * 1024) {
            continue;
        }
        if (ends_with(entry->d_name, ".con") || ends_with(entry->d_name, ".convel")) {
            check_file(path);
        }
    }
    closedir(handle);
}

int main(int argc, char **argv) {
    char valid[4096];
    char invalid[4096];
    char test_dir[4096];
    if (argc != 2) {
        return 2;
    }
    snprintf(valid, sizeof valid, "%s/resources/conformance/valid", argv[1]);
    snprintf(invalid, sizeof invalid, "%s/resources/conformance/invalid", argv[1]);
    snprintf(test_dir, sizeof test_dir, "%s/resources/test", argv[1]);
    walk(valid);
    walk(invalid);
    walk(test_dir);
    if (failures != 0) {
        fprintf(stderr, "%d checks failed\n", failures);
        return 1;
    }
    return 0;
}
