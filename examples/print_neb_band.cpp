#include "readcon-core.hpp"

#include <cmath>
#include <filesystem>
#include <iostream>
#include <string>

int main(int argc, char **argv) {
    std::filesystem::path path;
    if (argc > 1) {
        path = argv[1];
    } else {
        path = std::filesystem::path(__FILE__).parent_path().parent_path() /
               "resources" / "examples" / "neb_band.con";
    }
    if (!std::filesystem::exists(path)) {
        std::cerr << "missing " << path << "\n";
        return 1;
    }

    std::vector<readcon::ConFrame> frames;
    try {
        frames = readcon::read_all_frames(path);
    } catch (const std::exception &e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
    if (frames.empty()) {
        std::cerr << "no frames\n";
        return 1;
    }

    std::cout << "# " << path.string() << "  n_frames=" << frames.size() << "\n";
    std::cout << "bead\tenergy_eV\tfmax\n";
    for (const auto &frame : frames) {
        if (auto bead = frame.neb_bead_opt()) {
            std::cout << *bead;
        } else {
            std::cout << "NA";
        }
        std::cout << '\t';
        if (auto energy = frame.energy_opt()) {
            std::cout << *energy;
        } else {
            std::cout << "NA";
        }
        std::cout << '\t';
        const double fmax = frame.fmax();
        if (std::isnan(fmax)) {
            std::cout << "NA";
        } else {
            std::cout << fmax;
        }
        std::cout << '\n';
    }
    return 0;
}
