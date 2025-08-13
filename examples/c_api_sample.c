#include "readcon-core.h"
#include <stdio.h>

int main(int argc, char *argv[]) {
    if (argc < 2 || argc > 3) {
        fprintf(stderr, "Usage: %s <input.con> [output.con]\n", argv[0]);
        return 1;
    }

    const char *input_filename = argv[1];

    // To read multiple frames, we must use the iterator API.
    // First, create the iterator from the file path.
    CConFrameIterator *iterator = read_con_file_iterator(input_filename);
    if (!iterator) {
        fprintf(stderr, "Failed to open file or create iterator.\n");
        return 1;
    }

    printf("Successfully created iterator. Reading all frames...\n");

    if (argc == 2) {

        int frame_count = 0;
        CFrame *current_frame = NULL;

        // Loop by calling con_frame_iterator_next() until it returns NULL.
        while ((current_frame = con_frame_iterator_next(iterator)) != NULL) {
            frame_count++;
            printf("  - Loaded frame %d with %zu atoms.\n", frame_count,
                   current_frame->num_atoms);

            // It is crucial to free each frame after you are done with it
            // to prevent memory leaks inside the loop.
            free_con_frame(current_frame);
        }

        printf("Finished reading. Total frames found: %d\n", frame_count);

        // Finally, free the iterator itself.
        free_con_frame_iterator(iterator);
    }

    if (argc == 3) {
        size_t frame_capacity = 10;
        size_t frame_count = 0;
        CFrame **frames_array = malloc(frame_capacity * sizeof(CFrame *));
        if (!frames_array) {
            fprintf(stderr, "Failed to allocate memory for frame pointers.\n");
            free_con_frame_iterator(iterator);
            return 1;
        }

        CFrame *current_frame = NULL;

        while ((current_frame = con_frame_iterator_next(iterator)) != NULL) {
            if (frame_count >= frame_capacity) {
                frame_capacity *= 2;
                CFrame **new_array =
                    realloc(frames_array, frame_capacity * sizeof(CFrame *));
                if (!new_array) {
                    fprintf(
                        stderr,
                        "Failed to reallocate memory for frame pointers.\n");
                    for (size_t i = 0; i < frame_count; ++i) {
                        free_con_frame(frames_array[i]);
                    }
                    free(frames_array);
                    free_con_frame_iterator(iterator);
                    return 1;
                }
                frames_array = new_array;
            }
            frames_array[frame_count] = current_frame;
            frame_count++;
        }

        printf("Finished reading. Total frames found: %zu\n", frame_count);
        free_con_frame_iterator(iterator);

        const char *output_filename = argv[2];
        if (frame_count > 0) {
            printf("\nWriting %zu frames to '%s'...\n", frame_count,
                   output_filename);

            int result = write_con_file_from_c((const CFrame **)frames_array,
                                               frame_count, output_filename);

            if (result == 0) {
                printf("Successfully wrote frames.\n");
            } else {
                fprintf(stderr, "An error occurred while writing the file.\n");
            }
        }
        printf("\nCleaning up allocated memory...\n");
        for (size_t i = 0; i < frame_count; ++i) {
            free_con_frame(frames_array[i]);
        }
        free(frames_array);
        printf("Done.\n");
    }

    return 0;
}
