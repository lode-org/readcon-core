#include "readcon-core.hpp"
#include <iostream>

// A helper function to print the frame's data
void print_frame_details(int frame_number, const readcon::ConFrame &frame) {
    std::cout << "\n==================== FRAME " << frame_number << " ====================\n";
    // Print cell information
    auto cell = frame.cell();
    auto angles = frame.angles();
    std::cout << "Cell Dimensions: " << cell[0] << ", " << cell[1] << ", "
              << cell[2] << std::endl;
    std::cout << "Cell Angles:     " << angles[0] << ", " << angles[1] << ", "
              << angles[2] << std::endl;

    // Print atom information
    std::cout << "--- Atoms (" << frame.atoms().size() << ") ---\n";
    std::cout << std::boolalpha; // Print booleans as "true"/"false"

    // Print details for the first 5 atoms for brevity
    int atoms_to_print = 0;
    for (const auto &atom : frame.atoms()) {
        if (atoms_to_print >= 5) {
            std::cout << "... and " << frame.atoms().size() - 5 << " more." << std::endl;
            break;
        }
        std::cout << "  ID: " << atom.atom_id << ", Z: " << atom.atomic_number
                  << ", Pos: (" << atom.x << ", " << atom.y << ", " << atom.z
                  << ")"
                  << ", Fixed: " << atom.is_fixed << std::endl;
        atoms_to_print++;
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <path_to_con_file>" << std::endl;
        return 1;
    }

    std::string filename = argv[1];

    try {
        std::cout << "Attempting to iterate through all frames in: " << filename << std::endl;

        // To read all frames, create a ConFrameIterator object.
        // RAII ensures the underlying C iterator is freed when this object
        // goes out of scope.
        readcon::ConFrameIterator frame_iterator(filename);

        int frame_count = 0;
        // Use a modern range-based for loop to process each frame.
        for (const auto& frame : frame_iterator) {
            frame_count++;
            print_frame_details(frame_count, frame);
        }

        std::cout << "\n==================================================\n";
        std::cout << "Iteration complete. Total frames processed: " << frame_count << std::endl;

    } catch (const std::exception &e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
