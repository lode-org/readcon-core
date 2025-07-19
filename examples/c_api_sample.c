#include "readcon-core.h"
#include <stdio.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <path_to_con_file>\n", argv[0]);
        return 1;
    }

    // To read multiple frames, we must use the iterator API.
    // First, create the iterator from the file path.
    CConFrameIterator* iterator = read_con_file_iterator(argv[1]);
    if (!iterator) {
        fprintf(stderr, "Failed to open file or create iterator.\n");
        return 1;
    }

    printf("Successfully created iterator. Reading all frames...\n");

    int frame_count = 0;
    CFrame* current_frame = NULL;

    // Loop by calling con_frame_iterator_next() until it returns NULL.
    while ((current_frame = con_frame_iterator_next(iterator)) != NULL) {
        frame_count++;
        printf("  - Loaded frame %d with %zu atoms.\n", frame_count, current_frame->num_atoms);

        // It is crucial to free each frame after you are done with it
        // to prevent memory leaks inside the loop.
        free_con_frame(current_frame);
    }

    printf("Finished reading. Total frames found: %d\n", frame_count);

    // Finally, free the iterator itself.
    free_con_frame_iterator(iterator);

    return 0;
}
