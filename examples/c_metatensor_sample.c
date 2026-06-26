/* Metatensor-sys C ABI consumer (option A: sys on the boundary).
 *
 * After: cargo build --release --features metatensor,chemfiles
 *   source target/release/readcon-metatensor.env   # sets INCLUDE + LIB_DIR
 *   gcc -I include -I "$READCON_METATENSOR_INCLUDE" examples/c_metatensor_sample.c \
 *       -L target/release -L "$READCON_METATENSOR_LIB_DIR" \
 *       -Wl,-rpath,"$READCON_METATENSOR_LIB_DIR" -Wl,-rpath,"$PWD/target/release" \
 *       -lreadcon_core -lmetatensor -o /tmp/c_mts
 *
 * Or include readcon-metatensor.h (defines READCON_CORE_HAS_METATENSOR + metatensor.h).
 */
#include "readcon-metatensor.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static size_t frame_natoms(const RKRConFrame *f) {
    struct CFrame *cf = rkr_frame_to_c_frame(f);
    if (!cf) return 0;
    size_t n = (size_t)cf->num_atoms;
    free_c_frame(cf);
    return n;
}

static int check_block_shape(struct mts_block_t *block, size_t expect_n, size_t expect_props) {
    mts_array_t array;
    memset(&array, 0, sizeof(array));
    if (mts_block_data(block, &array) != MTS_SUCCESS) {
        fprintf(stderr, "mts_block_data failed\n");
        return -1;
    }
    if (!array.shape) {
        fprintf(stderr, "mts_array_t.shape is NULL\n");
        return -1;
    }
    const uintptr_t *shape = NULL;
    uintptr_t shape_count = 0;
    if (array.shape(array.ptr, &shape, &shape_count) != MTS_SUCCESS) {
        fprintf(stderr, "shape callback failed\n");
        return -1;
    }
    if (shape_count != 2 || (size_t)shape[0] != expect_n || (size_t)shape[1] != expect_props) {
        fprintf(stderr, "bad shape count=%zu dims=[%zu,%zu] expect [%zu,%zu]\n",
                (size_t)shape_count,
                shape_count > 0 ? (size_t)shape[0] : 0,
                shape_count > 1 ? (size_t)shape[1] : 0,
                expect_n, expect_props);
        return -1;
    }
    const struct mts_labels_t *samples = mts_block_labels(block, 0);
    const struct mts_labels_t *props = mts_block_labels(block, 1);
    if (samples == NULL || props == NULL) {
        fprintf(stderr, "mts_block_labels axis missing\n");
        return -1;
    }
    printf("block shape=[%zu,%zu] samples_axis=%p props_axis=%p\n",
           (size_t)shape[0], (size_t)shape[1], (const void *)samples, (const void *)props);
    return 0;
}

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "resources/test/tiny_cuh2.con";
    RKRConFrame *f = rkr_read_first_frame(path);
    if (!f) {
        fprintf(stderr, "read failed\n");
        return 1;
    }
    size_t natoms = frame_natoms(f);

    struct mts_block_t *block = NULL;
    enum RKRStatus st = rkr_frame_metatensor_positions_block(f, &block);
    printf("positions block status=%d block=%p natoms=%zu\n", (int)st, (void *)block, natoms);
    if (st != RKR_STATUS_SUCCESS || block == NULL) {
        free_rkr_frame(f);
        return 2;
    }
    if (check_block_shape(block, natoms, 3) != 0) {
        rkr_mts_block_free(block);
        free_rkr_frame(f);
        return 3;
    }
    rkr_mts_block_free(block);

    block = NULL;
    st = rkr_frame_metatensor_velocities_block(f, &block);
    printf("velocities (optional) status=%d\n", (int)st);
    if (st == RKR_STATUS_SUCCESS && block) {
        rkr_mts_block_free(block);
    } else if (st != RKR_STATUS_SECTION_ABSENT) {
        free_rkr_frame(f);
        return 5;
    }

    block = NULL;
    st = rkr_frame_metatensor_forces_block(f, &block);
    printf("forces (optional) status=%d\n", (int)st);
    if (st == RKR_STATUS_SUCCESS && block) {
        rkr_mts_block_free(block);
    } else if (st != RKR_STATUS_SECTION_ABSENT) {
        free_rkr_frame(f);
        return 6;
    }

    block = NULL;
    st = rkr_frame_metatensor_atom_energies_block(f, &block);
    printf("atom_energies (optional) status=%d\n", (int)st);
    if (st == RKR_STATUS_SUCCESS && block) {
        if (check_block_shape(block, natoms, 1) != 0) {
            rkr_mts_block_free(block);
            free_rkr_frame(f);
            return 7;
        }
        rkr_mts_block_free(block);
    } else if (st != RKR_STATUS_SECTION_ABSENT) {
        free_rkr_frame(f);
        return 8;
    }

    free_rkr_frame(f);
    printf("OK metatensor C API consumer (sys boundary)\n");
    return 0;
}
