#include "readcon-core.h"

#include <stdio.h>
#include <string.h>

int main(void) {
    const char *version = rkr_library_version();
    if (version == NULL || strlen(version) == 0) {
        fprintf(stderr, "rkr_library_version returned empty\n");
        return 1;
    }
    printf("readcon-core %s\n", version);
    return 0;
}
