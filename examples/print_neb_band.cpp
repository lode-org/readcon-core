#include "readcon-core.hpp"
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

// TSV of bead, energy_eV, fmax for a multi-image NEB band.
// Default input: resources/examples/neb_band.con (override with argv[1]).
// bead/energy: rkr_frame_neb_bead / rkr_frame_energy (UINT64_MAX / NaN => NA).
// fmax: metadata JSON key, else rkr_frame_fmax.

static std::optional<double> metadata_number(const readcon::ConFrame &frame,
                                             const char *key) {
    const std::string json = frame.metadata_json();
    const std::string pat = std::string("\"") + key + "\":";
    auto pos = json.find(pat);
    if (pos == std::string::npos)
        return std::nullopt;
    pos += pat.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t'))
        ++pos;
    char *end = nullptr;
    const double v = std::strtod(json.c_str() + pos, &end);
    if (end == json.c_str() + static_cast<std::ptrdiff_t>(pos) ||
        std::isnan(v)) {
        return std::nullopt;
    }
    return v;
}

int main(int argc, char *argv[]) {
    if (argc > 2) {
        std::cerr << "Usage: " << argv[0] << " [input.con]" << std::endl;
        return 1;
    }

    std::filesystem::path path;
    if (argc == 2) {
        path = argv[1];
    } else {
        path = std::filesystem::path(__FILE__).parent_path().parent_path() /
               "resources" / "examples" / "neb_band.con";
    }

    try {
        const std::vector<readcon::ConFrame> frames =
            readcon::read_all_frames(path);
        if (frames.empty()) {
            std::cerr << "Error: no frames in " << path << std::endl;
            return 1;
        }

        std::cout << "# " << path.string() << "  n_frames=" << frames.size()
                  << std::endl;
        std::cout << "bead\tenergy_eV\tfmax" << std::endl;
        for (const auto &frame : frames) {
            const uint64_t bead = rkr_frame_neb_bead(frame.get_handle());
            const double energy = rkr_frame_energy(frame.get_handle());
            std::optional<double> fmax = metadata_number(frame, "fmax");
            if (!fmax) {
                const double computed = rkr_frame_fmax(frame.get_handle());
                if (!std::isnan(computed))
                    fmax = computed;
            }

            if (bead == UINT64_MAX)
                std::cout << "NA";
            else
                std::cout << bead;
            std::cout << '\t';
            if (std::isnan(energy))
                std::cout << "NA";
            else
                std::cout << energy;
            std::cout << '\t';
            if (!fmax)
                std::cout << "NA";
            else
                std::cout << *fmax;
            std::cout << std::endl;
        }
    } catch (const std::exception &e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
