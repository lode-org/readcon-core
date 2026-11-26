// Build a CON 4.0.5 frame with velocities, set the natural time unit, write
// it with ConFrameWriter::round_trip, and read the minor and the unit
// bytes back.
#include "readcon-core.hpp"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>

namespace {

int failures = 0;

void check(bool ok, const std::string &what) {
    if (!ok) {
        std::cerr << "FAIL: " << what << "\n";
        ++failures;
    }
}

} // namespace

int main(int argc, char *argv[]) {
    try {
        std::filesystem::path out = "build/readcon_cpp_v31_units.con";
        if (argc > 1) {
            out = argv[1];
        } else if (const char *dir = std::getenv("READCON_EXAMPLE_DIR")) {
            std::filesystem::create_directories(dir);
            out = std::filesystem::path(dir) / "readcon_cpp_v31_units.con";
        } else {
            std::filesystem::create_directories("build");
        }

        readcon::ConFrameBuilder builder({10.0, 10.0, 10.0}, {90.0, 90.0, 90.0});
        builder.add_atom("H", 0.0, 0.0, 0.0, false, 0, 1.008);
        builder.with_velocity({1.0, 0.0, 0.0});
        builder.set_units(
            R"({"length":"angstrom","energy":"eV","mass":"amu","time":"( amu * angstrom ^ 2 / eV ) ^ 0.5"})");
        auto frame = builder.build();
        {
            std::vector<readcon::ConFrame> frames;
            frames.push_back(std::move(frame));
            auto writer = readcon::ConFrameWriter::round_trip(out);
            writer.extend(frames);
        }

        auto parsed = readcon::read_first_frame(out);
        const std::string json = parsed.metadata_json();
        const std::string pinned = "(u*Å^2/eV)^0.5";
        const std::string historical = "(amu*angstrom^2/eV)^0.5";
        check(json.find("\"con_spec_minor\":0") != std::string::npos,
              "con_spec_minor 0 in " + json);
        check(json.find("\"con_spec_patch\":5") != std::string::npos,
              "con_spec_patch 5 in " + json);
        check(json.find(pinned) != std::string::npos,
              "pinned unit in " + json);
        check(json.find(historical) == std::string::npos,
              "historical unit absent in " + json);

        if (argc <= 1) {
            std::filesystem::remove(out);
        }
    } catch (const std::exception &ex) {
        std::cerr << "exception: " << ex.what() << "\n";
        return 1;
    }
    if (failures != 0) {
        std::cerr << failures << " CON 4.0.5 unit check(s) failed\n";
        return 1;
    }
    return 0;
}
