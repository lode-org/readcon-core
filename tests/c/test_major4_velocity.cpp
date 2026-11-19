// Write a major-4 frame with a velocity and units.time fs, then read both back.
#include "readcon-core.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

namespace {

int failures = 0;

void check(bool ok, const std::string &what) {
    if (!ok) {
        std::cerr << "FAIL: " << what << "\n";
        ++failures;
    }
}

std::uint64_t bits(double value) {
    std::uint64_t out = 0;
    std::memcpy(&out, &value, sizeof out);
    return out;
}

} // namespace

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "usage: " << argv[0] << " FILE\n";
        return 2;
    }
    const std::filesystem::path out = argv[1];
    try {
        readcon::ConFrameBuilder builder({10.0, 10.0, 10.0}, {90.0, 90.0, 90.0});
        builder.set_units(
            R"({"length":"angstrom","energy":"eV","mass":"amu","time":"fs"})");
        const std::array<double, 3> velocity{1.5, -0.25, 0.0};
        builder.add_atom("H", 0.0, 0.0, 0.0, false, 7, 1.008, velocity);
        auto frame = builder.build();
        {
            std::vector<readcon::ConFrame> frames;
            frames.push_back(std::move(frame));
            auto writer = readcon::ConFrameWriter::round_trip(out);
            writer.extend(frames);
            writer.flush();
        }

        auto parsed = readcon::read_first_frame(out);
        const std::string json = parsed.metadata_json();
        check(parsed.spec_version() == 4, "spec version 4, json " + json);
        check(json.find("\"time\":\"fs\"") != std::string::npos, "units.time fs in " + json);
        check(json.find("\"con_spec_version\":4") != std::string::npos,
              "major 4 in " + json);
        check(parsed.atoms().size() == 1, "one atom");
        auto got = parsed.atoms().at(0).velocity();
        check(got.has_value(), "velocity present");
        if (got) {
            check(bits((*got)[0]) == bits(1.5) && bits((*got)[1]) == bits(-0.25) &&
                       bits((*got)[2]) == bits(0.0),
                   "velocity bytes");
        }
    } catch (const std::exception &ex) {
        std::cerr << "exception: " << ex.what() << "\n";
        return 1;
    }
    if (failures != 0) {
        std::cerr << failures << " C++ major-4 velocity check(s) failed\n";
        return 1;
    }
    return 0;
}
