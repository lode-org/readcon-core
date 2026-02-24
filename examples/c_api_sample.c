#include "readcon-core.h"
#include <stdio.h>
#include <stdlib.h>

const size_t MAX_HEADER_LENGTH = 256;

// A helper function to print the summary using the new FFI.
void print_frame_summary(const RKRConFrame *frame_handle) {
    if (!frame_handle)
        return;

    // To inspect the data, extract a temporary, transparent CFrame.
    CFrame *c_frame = rkr_frame_to_c_frame(frame_handle);
    if (!c_frame) {
        fprintf(stderr, "Failed to extract CFrame from handle.\n");
        return;
    }

    char header_buffer[MAX_HEADER_LENGTH];
    printf("\n-> Summary of last valid frame:\n");

    rkr_frame_get_header_line(frame_handle, 1, 0, header_buffer,
                              MAX_HEADER_LENGTH);
    printf("  - Pre-box header 1: \"%s\"\n", header_buffer);
    rkr_frame_get_header_line(frame_handle, 1, 1, header_buffer,
                              MAX_HEADER_LENGTH);
    printf("  - Pre-box header 2: \"%s\"\n", header_buffer);

    printf("  - Cell vectors:     [%.4f, %.4f, %.4f]\n", c_frame->cell[0],
           c_frame->cell[1], c_frame->cell[2]);
    printf("  - Cell angles:      [%.4f, %.4f, %.4f]\n", c_frame->angles[0],
           c_frame->angles[1], c_frame->angles[2]);

    rkr_frame_get_header_line(frame_handle, 0, 0, header_buffer,
                              MAX_HEADER_LENGTH);
    printf("  - Post-box header 1:\"%s\"\n", header_buffer);
    rkr_frame_get_header_line(frame_handle, 0, 1, header_buffer,
                              MAX_HEADER_LENGTH);
    printf("  - Post-box header 2:\"%s\"\n", header_buffer);

    printf("  - Total atoms:      %zu\n", c_frame->num_atoms);
    printf("  - Has velocities:   %s\n",
           c_frame->has_velocities ? "yes" : "no");
    if (c_frame->num_atoms > 0) {
        const CAtom *last_atom = &c_frame->atoms[c_frame->num_atoms - 1];
        printf(
            "  - Last atom:        ID=%llu, Z=%llu, Pos=[%.4f, %.4f, %.4f]\n",
            (unsigned long long)last_atom->atom_id,
            (unsigned long long)last_atom->atomic_number, last_atom->x,
            last_atom->y, last_atom->z);
        if (last_atom->has_velocity) {
            printf("    Vel=[%.6f, %.6f, %.6f]\n", last_atom->vx,
                   last_atom->vy, last_atom->vz);
        }
    }

    // CRUCIAL: Free the temporary CFrame struct after we're done with it.
    free_c_frame(c_frame);
}

int main(int argc, char *argv[]) {
    if (argc < 2 || argc > 3) {
        fprintf(stderr, "Usage: %s <input.con> [output.con]\n", argv[0]);
        return 1;
    }

    const char *input_filename = argv[1];
    const int is_write_mode = (argc == 3);

    CConFrameIterator *iterator = read_con_file_iterator(input_filename);
    if (!iterator) {
        fprintf(stderr, "Failed to open file or create iterator for '%s'.\n",
                input_filename);
        return 1;
    }
    printf("Successfully created iterator. Reading all frames from '%s'...\n",
           input_filename);

    // --- Unified Reading Loop ---
    size_t frame_count = 0;
    RKRConFrame *last_handle = NULL;
    RKRConFrame **handles_array = NULL;
    size_t frame_capacity = 0;

    if (is_write_mode) {
        frame_capacity = 10;
        handles_array = malloc(frame_capacity * sizeof(RKRConFrame *));
        if (!handles_array) {
            fprintf(stderr, "Failed to allocate memory for frame handles.\n");
            free_con_frame_iterator(iterator);
            return 1;
        }
    }

    RKRConFrame *current_handle = NULL;
    while ((current_handle = con_frame_iterator_next(iterator)) != NULL) {
        frame_count++;
        if (is_write_mode) {
            if (frame_count >= frame_capacity) {
                frame_capacity *= 2;
                RKRConFrame **new_array = realloc(
                    handles_array, frame_capacity * sizeof(RKRConFrame *));
                if (!new_array) {
                    fprintf(stderr, "Failed to reallocate memory.\n");
                    for (size_t i = 0; i < frame_count - 1; ++i)
                        free_rkr_frame(handles_array[i]);
                    free(handles_array);
                    free_rkr_frame(
                        current_handle); // Free the one that didn't fit
                    free_con_frame_iterator(iterator);
                    return 1;
                }
                handles_array = new_array;
            }
            handles_array[frame_count - 1] = current_handle;
        } else {
            if (last_handle) {
                free_rkr_frame(last_handle);
            }
            last_handle = current_handle;
        }
    }
    printf("Finished reading. Total frames found: %zu\n", frame_count);
    free_con_frame_iterator(iterator);

    // --- Summary ---
    if (frame_count > 0) {
        RKRConFrame *summary_handle =
            is_write_mode ? handles_array[frame_count - 1] : last_handle;
        print_frame_summary(summary_handle);
    }

    // --- Optional Writing ---
    if (is_write_mode && frame_count > 0) {
        const char *output_filename = argv[2];
        printf("\nWriting %zu frames to '%s'...\n", frame_count,
               output_filename);

        // Use the new object-oriented writer API
        RKRConFrameWriter *writer = create_writer_from_path_c(output_filename);
        if (!writer) {
            fprintf(stderr, "Failed to create writer for file '%s'.\n",
                    output_filename);
        } else {
            int result = rkr_writer_extend(
                writer, (const RKRConFrame **)handles_array, frame_count);
            if (result == 0) {
                printf("Successfully wrote all frames.\n");
            } else {
                fprintf(stderr, "An error occurred while writing the file.\n");
            }
            // Free the writer to close the file and release resources.
            free_rkr_writer(writer);
        }
    }

    // --- Cleanup ---
    printf("\nCleaning up allocated memory...\n");
    if (is_write_mode) {
        for (size_t i = 0; i < frame_count; ++i) {
            free_rkr_frame(handles_array[i]);
        }
        free(handles_array);
    } else {
        if (last_handle) {
            free_rkr_frame(last_handle);
        }
    }

    printf("Done.\n");
    return 0;
}
