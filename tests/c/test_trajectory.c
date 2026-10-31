/*
 * rkr_trajectory_* against rkr_read_all_frames on an 800-frame file,
 * without a sidecar, while writing one, and while reusing it.
 * Usage: test_trajectory <repo root> <scratch dir>
 */
#include "readcon-core.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;
#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, \
                    #cond);                                                  \
            failures++;                                                      \
        }                                                                    \
    } while (0)

static char *slurp(const char *path, size_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc((size_t)n + 1);
    *len = fread(buf, 1, (size_t)n, f);
    buf[*len] = '\0';
    fclose(f);
    return buf;
}

static int same_frame(const RKRConFrame *a, const RKRConFrame *b) {
    size_t na = 0, nb = 0;
    const double *xa = rkr_frame_xyz_f64(a, &na);
    const double *xb = rkr_frame_xyz_f64(b, &nb);
    char *ma = rkr_frame_metadata_json(a);
    char *mb = rkr_frame_metadata_json(b);
    int same = rkr_frame_atom_count(a) == rkr_frame_atom_count(b) && na == nb &&
               memcmp(xa, xb, na * 3 * sizeof(double)) == 0 && ma && mb &&
               strcmp(ma, mb) == 0;
    rkr_free_string(ma);
    rkr_free_string(mb);
    return same;
}

static void write_frames(const char *path, const RKRConFrame *const *frames, size_t n) {
    RKRConFrameWriter *w = create_writer_from_path_round_trip_c(path);
    CHECK(w != NULL);
    CHECK(rkr_writer_extend(w, frames, n) == RKR_STATUS_SUCCESS);
    CHECK(rkr_writer_flush(w) == RKR_STATUS_SUCCESS);
    free_rkr_writer(w);
}

static int last_error_is(const char *want) {
    const char *msg = rkr_last_error_message();
    return msg != NULL && strcmp(msg, want) == 0;
}

static int out_of_range_is_reported(const RKRTrajectory *t, size_t index) {
    char want[128];
    snprintf(want, sizeof want,
             "frame index %zu is out of range for a trajectory of %zu frames",
             index, rkr_trajectory_len(t));
    RKRConFrame *f = (RKRConFrame *)(uintptr_t)1;
    return rkr_trajectory_read_frame(t, index, &f) ==
               RKR_STATUS_INDEX_OUT_OF_BOUNDS &&
           f == NULL && last_error_is(want);
}

static int file_exists(const char *path) {
    FILE *f = fopen(path, "rb");
    if (f) fclose(f);
    return f != NULL;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <repo root> <scratch dir>\n", argv[0]);
        return 2;
    }
    char src[1024], path[1024], side[1100], ref[1100], got[1100];
    snprintf(src, sizeof src, "%s/resources/test/tiny_multi_cuh2.con", argv[1]);
    snprintf(path, sizeof path, "%s/c_traj_long.con", argv[2]);
    snprintf(side, sizeof side, "%s.rcidx", path);
    snprintf(ref, sizeof ref, "%s.ref", path);
    snprintf(got, sizeof got, "%s.got", path);

    size_t one_len = 0;
    char *one = slurp(src, &one_len);
    CHECK(one != NULL);
    if (!one) return 1;
    FILE *out = fopen(path, "wb");
    CHECK(out != NULL);
    if (!out) return 1;
    for (int k = 0; k < 400; k++) fwrite(one, 1, one_len, out);
    fclose(out);
    free(one);
    remove(side);

    size_t n = 0;
    RKRConFrame **all = rkr_read_all_frames(path, &n);
    CHECK(all != NULL && n == 800);
    write_frames(ref, (const RKRConFrame *const *)all, n);

    for (int pass = 0; pass < 3; pass++) {
        RKRTrajectory *t = rkr_trajectory_open(path, pass > 0);
        CHECK(t != NULL);
        CHECK(rkr_trajectory_len(t) == n);
        CHECK(file_exists(side) == (pass > 0));
        RKRConFrame **mine = calloc(n, sizeof *mine);
        for (size_t i = 0; i < n; i++) {
            CHECK(rkr_trajectory_read_frame(t, i, &mine[i]) == RKR_STATUS_SUCCESS);
            CHECK(mine[i] != NULL && same_frame(mine[i], all[i]));
        }
        size_t bad[3] = {n, n + 1, SIZE_MAX};
        for (int b = 0; b < 3; b++) CHECK(out_of_range_is_reported(t, bad[b]));
        write_frames(got, (const RKRConFrame *const *)mine, n);
        size_t lr = 0, lg = 0;
        char *br = slurp(ref, &lr), *bg = slurp(got, &lg);
        CHECK(br && bg && lr == lg && memcmp(br, bg, lr) == 0);
        free(br);
        free(bg);
        for (size_t i = 0; i < n; i++) free_rkr_frame(mine[i]);
        free(mine);
        rkr_trajectory_free(t);
    }
    free_rkr_frame_array(all, n);

    CHECK(rkr_trajectory_open(NULL, 0) == NULL);
    CHECK(last_error_is("filename is NULL"));
    CHECK(rkr_trajectory_open("/nonexistent/x.con", 0) == NULL);
    CHECK(rkr_last_error_message() != NULL);
    CHECK(rkr_trajectory_len(NULL) == SIZE_MAX);

    /* Each NULL call records its own message over the out-of-range one. */
    RKRTrajectory *t = rkr_trajectory_open(path, 0);
    CHECK(t != NULL && out_of_range_is_reported(t, n));
    RKRConFrame *f = (RKRConFrame *)(uintptr_t)1;
    CHECK(rkr_trajectory_read_frame(NULL, 0, &f) == RKR_STATUS_NULL_POINTER);
    CHECK(f == NULL && last_error_is("null argument"));
    CHECK(out_of_range_is_reported(t, n));
    CHECK(rkr_trajectory_read_frame(t, 0, NULL) == RKR_STATUS_NULL_POINTER);
    CHECK(last_error_is("null argument"));
    CHECK(out_of_range_is_reported(t, n));
    CHECK(rkr_trajectory_read_frame(NULL, 0, NULL) == RKR_STATUS_NULL_POINTER);
    CHECK(last_error_is("null argument"));
    CHECK(out_of_range_is_reported(t, n));
    CHECK(rkr_trajectory_len(NULL) == SIZE_MAX);
    CHECK(last_error_is("null argument"));
    CHECK(rkr_trajectory_len(t) == n && last_error_is("null argument"));
    CHECK(rkr_trajectory_read_frame(t, 0, &f) == RKR_STATUS_SUCCESS);
    CHECK(f != NULL && rkr_last_error_message() == NULL);
    free_rkr_frame(f);
    rkr_trajectory_free(t);
    rkr_trajectory_free(NULL);

    remove(path);
    remove(side);
    remove(ref);
    remove(got);
    if (failures) {
        fprintf(stderr, "test_trajectory: %d failures\n", failures);
        return 1;
    }
    printf("test_trajectory: ok (%zu frames, 3 passes)\n", n);
    return 0;
}
