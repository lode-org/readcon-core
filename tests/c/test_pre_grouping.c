/*
 * pre_grouping_indices: unique ids sort, repeated ids keep input order.
 * The caller owns the returned array and frees it with rkr_free_indices.
 */
#include "readcon-core.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static int expect_eq(const char *name, const size_t *got, const size_t *want, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (got[i] != want[i]) {
            fprintf(stderr, "FAIL %s[%zu]=%zu want %zu\n", name, i, got[i], want[i]);
            return 1;
        }
    }
    return 0;
}

int main(void) {
    int nfail = 0;
    uint64_t unique[] = {2, 0, 1};
    size_t want_unique[] = {1, 2, 0};
    size_t *idx = rkr_pre_grouping_indices(unique, 3);
    if (!idx) {
        fprintf(stderr, "FAIL unique returned NULL\n");
        return 1;
    }
    nfail += expect_eq("unique", idx, want_unique, 3);
    rkr_free_indices(idx, 3);

    uint64_t repeated[] = {1, 1, 0};
    size_t want_repeated[] = {0, 1, 2};
    idx = rkr_pre_grouping_indices(repeated, 3);
    if (!idx) {
        fprintf(stderr, "FAIL repeated returned NULL\n");
        return 1;
    }
    nfail += expect_eq("repeated", idx, want_repeated, 3);
    rkr_free_indices(idx, 3);

    if (rkr_pre_grouping_indices(NULL, 3) != NULL) {
        fprintf(stderr, "FAIL null ids should return NULL\n");
        nfail++;
    }
    if (rkr_pre_grouping_indices(unique, 0) != NULL) {
        fprintf(stderr, "FAIL n=0 should return NULL\n");
        nfail++;
    }
    rkr_free_indices(NULL, 0);
    rkr_free_indices(NULL, 3);

    if (nfail != 0) {
        fprintf(stderr, "c pre_grouping_indices: FAIL %d\n", nfail);
        return 1;
    }
    printf("c pre_grouping_indices: OK\n");
    return 0;
}
