#include "readcon-core.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

#define CHECK(condition)                                                        \
    do {                                                                        \
        if (!(condition)) {                                                     \
            fprintf(stderr, "check failed at %s:%d: %s\n", __FILE__, __LINE__, \
                    #condition);                                                \
            return 1;                                                           \
        }                                                                       \
    } while (0)

static RKRConFrameBuilder *builder(void) {
    const double cell[3] = {10.0, 10.0, 10.0};
    const double angles[3] = {90.0, 90.0, 90.0};
    return rkr_frame_new(cell, angles, NULL, NULL, NULL, NULL);
}

int main(void) {
    RKRConFrameBuilder *ok = builder();
    CHECK(ok != NULL);
    CHECK(rkr_frame_add_atom(ok, "H", 0.0, 0.0, 0.0, false, 0, 1.0) ==
          RKR_STATUS_SUCCESS);
    RKRConFrame *frame = rkr_frame_builder_build(&ok);
    CHECK(frame != NULL);
    CHECK(ok == NULL);
    free_rkr_frame_builder(ok);
    free_rkr_frame(frame);

    RKRConFrameBuilder *bad = builder();
    CHECK(bad != NULL);
    CHECK(rkr_frame_add_atom(bad, "H", 0.0, 0.0, 0.0, false, 0, 1.0) ==
          RKR_STATUS_SUCCESS);
    CHECK(rkr_frame_add_atom(bad, "H", 1.0, 0.0, 0.0, false, 1, 2.0) ==
          RKR_STATUS_SUCCESS);
    CHECK(rkr_frame_builder_build(&bad) == NULL);
    CHECK(bad == NULL);
    free_rkr_frame_builder(bad);
    return 0;
}
