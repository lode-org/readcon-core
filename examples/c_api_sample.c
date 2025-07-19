#include "readcon-core.h"
#include <stdio.h>

int main(int argc, char *argv[]) {
    // Load the .con file
    CFrame* frame = read_con_file(argv[1]);

    if (frame) {
        printf("Successfully loaded a frame with %zu atoms.\n", frame->num_atoms);

        // Don't forget to free the memory!
        free_con_frame(frame);
    } else {
        printf("Failed to load the .con file.\n");
    }

    return 0;
}
