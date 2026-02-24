#include "readcon-core.hpp"
#include <iostream>
#include <vector>

// A helper function to print the frame's data in detail.
void print_frame_details(int frame_number, const readcon::ConFrame &frame) {
    std::cout << "\n==================== FRAME " << frame_number
              << " ====================\n";

    // Print header information using the accessor methods
    auto pre_headers = frame.prebox_header();
    std::cout << "Pre-box Header 1: \"" << pre_headers[0] << "\"\n";
    std::cout << "Pre-box Header 2: \"" << pre_headers[1] << "\"\n";

    // Print cell information
    auto cell = frame.cell();
    auto angles = frame.angles();
    std::cout << "Cell Dimensions:  " << cell[0] << ", " << cell[1] << ", "
              << cell[2] << std::endl;
    std::cout << "Cell Angles:      " << angles[0] << ", " << angles[1] << ", "
              << angles[2] << std::endl;

    auto post_headers = frame.postbox_header();
    std::cout << "Post-box Header 1:\"" << post_headers[0] << "\"\n";
    std::cout << "Post-box Header 2:\"" << post_headers[1] << "\"\n";

    // Print velocity status
    std::cout << "Has Velocities:   " << std::boolalpha << frame.has_velocities()
              << std::endl;

    // Print atom information
    auto atoms = frame.atoms(); // Call once to avoid repeated conversions
    std::cout << "--- Atoms (" << atoms.size() << ") ---\n";

    // Print details for the first 5 atoms for brevity
    int atoms_to_print = 0;
    for (const auto &atom : atoms) {
        if (atoms_to_print >= 5) {
            std::cout << "... and " << atoms.size() - 5 << " more."
                      << std::endl;
            break;
        }
        std::cout << "  ID: " << atom.atom_id << ", Z: " << atom.atomic_number
                  << ", Pos: (" << atom.x << ", " << atom.y << ", " << atom.z
                  << ")"
                  << ", Fixed: " << atom.is_fixed;
        if (atom.has_velocity) {
            std::cout << ", Vel: (" << atom.vx << ", " << atom.vy << ", "
                      << atom.vz << ")";
        }
        std::cout << std::endl;
        atoms_to_print++;
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2 || argc > 3) {
        std::cerr << "Usage: " << argv[0] << " <input.con> [output.con]"
                  << std::endl;
        return 1;
    }

    std::string input_filename = argv[1];

    try {
        // --- Read-only and Summarize Mode (Memory-Efficient) ---
        if (argc == 2) {
            std::cout << "Mode: Read-only. Iterating lazily through frames in: "
                      << input_filename << std::endl;
            readcon::ConFrameIterator frame_iterator(input_filename);

            int frame_count = 0;
            // This loop is memory-efficient. It processes one frame at a time
            // without storing them all in memory.
            for (const auto &frame : frame_iterator) {
                frame_count++;
                print_frame_details(frame_count, frame);
            }
            std::cout
                << "\n==================================================\n";
            std::cout << "Iteration complete. Total frames processed: "
                      << frame_count << std::endl;
        }
        // --- Read and Write Mode ---
        else { // argc == 3
            std::string output_filename = argv[2];
            std::cout << "Mode: Read-Write. Reading from '" << input_filename
                      << "' and writing to '" << output_filename << "'."
                      << std::endl;

            readcon::ConFrameIterator frame_iterator(input_filename);

            // In write mode, we must collect all frames first.
            std::vector<readcon::ConFrame> all_frames;
            // Use 'auto &&frame' to enable move semantics: ConFrameIterator
            // yields rvalue references, so moves are without copy
            for (auto &&frame : frame_iterator) {
                // We must move the frame from the iterator into our vector.
                all_frames.push_back(std::move(frame));
            }

            if (all_frames.empty()) {
                std::cout << "No valid frames found to write." << std::endl;
            } else {
                print_frame_details(all_frames.size(), all_frames.back());
                std::cout << "\nWriting " << all_frames.size()
                          << " frames...\n";

                // Use the new, ergonomic ConFrameWriter object.
                // RAII ensures the file is properly closed when the writer goes
                // out of scope.
                readcon::ConFrameWriter writer(output_filename);
                writer.extend(all_frames);

                std::cout << "Successfully wrote all frames." << std::endl;
            }
        }

    } catch (const std::exception &e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
