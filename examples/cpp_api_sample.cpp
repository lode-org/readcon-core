#include "readcon-core.hpp"
#include <iostream>
#include <vector>

// A helper function to print the frame's data
void print_frame_details(const readcon::ConFrame &frame) {
    // Print cell information
    auto cell = frame.cell();
    auto angles = frame.angles();
    std::cout << "Cell Dimensions: " << cell[0] << ", " << cell[1] << ", "
              << cell[2] << std::endl;
    std::cout << "Cell Angles:     " << angles[0] << ", " << angles[1] << ", "
              << angles[2] << std::endl;

    // Print atom information
    std::cout << "\n--- Atoms (" << frame.atoms().size() << ") ---\n";
    std::cout << std::boolalpha;

    for (const auto &atom : frame.atoms()) {
        std::cout << "ID: " << atom.atom_id << ", Z: " << atom.atomic_number
                  << ", Pos: (" << atom.x << ", " << atom.y << ", " << atom.z
                  << ")"
                  << ", Fixed: " << atom.is_fixed << std::endl;
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <path_to_con_file>" << std::endl;
        return 1;
    }

    std::string filename = argv[1];

    try {
        std::cout << "Attempting to read file: " << filename << "\n"
                  << std::endl;

        // Use the factory function to create a frame object.
        // RAII ensures memory is automatically freed when 'frame' goes out of
        // scope.
        auto frame = readcon::ConFrame::from_file(filename);

        std::cout << "File parsed successfully!\n" << std::endl;
        print_frame_details(frame);

    } catch (const std::exception &e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
