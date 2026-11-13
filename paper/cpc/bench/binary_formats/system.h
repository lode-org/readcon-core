/* The source system of the binary-format campaign, in angstrom.
 *
 * BF_SIDE^3 atoms on a simple cubic lattice of spacing BF_SPACING in an
 * orthorhombic box whose three lengths grow by different amounts each frame.
 * Every atom sits at the centre of its lattice cell, displaced along each axis
 * by less than 0.15 angstrom, an offset that a splitmix64 hash of the frame,
 * atom and axis picks; so no atom leaves the box and no two frames are alike.
 * The first half of the atoms are Cu and the second half H, so the
 * type-grouped order of a CON frame is the index order of the other formats.
 *
 * Only integer arithmetic and correctly rounded double operations are used,
 * and gen.c is built with -ffp-contract=off, so the values do not depend on
 * the compiler or the libm.
 */
#ifndef BF_SYSTEM_H
#define BF_SYSTEM_H

#include <stdint.h>

#ifndef BF_SIDE
#define BF_SIDE 100
#endif
#define BF_NATOMS (BF_SIDE * BF_SIDE * BF_SIDE)
#ifndef BF_FRAMES
#define BF_FRAMES 10
#endif
#define BF_SPACING 2.55
#define BF_JITTER 0.15

static inline void bf_box(int frame, double box[3]) {
    const double edge = BF_SIDE * BF_SPACING;
    box[0] = edge * (1.0 + 0.0010 * (double)frame);
    box[1] = edge * (1.0 + 0.0015 * (double)frame);
    box[2] = edge * (1.0 + 0.0020 * (double)frame);
}

static inline uint64_t bf_splitmix64(uint64_t x) {
    x += 0x9E3779B97F4A7C15ull;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ull;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBull;
    return x ^ (x >> 31);
}

/* A double in [-BF_JITTER, BF_JITTER) from the top 53 bits of a hash. */
static inline double bf_offset(int frame, int64_t atom, int axis) {
    uint64_t key = ((uint64_t)frame << 40) ^ ((uint64_t)atom << 2) ^ (uint64_t)axis;
    double unit = (double)(bf_splitmix64(key) >> 11) * 0x1.0p-53;
    return BF_JITTER * (2.0 * unit - 1.0);
}

static inline void bf_position(int frame, int64_t atom, const double box[3], double r[3]) {
    const int64_t index[3] = {atom % BF_SIDE, (atom / BF_SIDE) % BF_SIDE, atom / (BF_SIDE * BF_SIDE)};
    for (int k = 0; k < 3; k++) {
        r[k] = ((double)index[k] + 0.5) / BF_SIDE * box[k] + bf_offset(frame, atom, k);
    }
}

static inline const char *bf_species(int64_t atom) {
    return atom < BF_NATOMS / 2 ? "Cu" : "H";
}

#endif
