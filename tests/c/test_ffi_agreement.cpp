// C++ API against the same frames the C ABI returns.
//
// Build a geometry, write it, and read it back. Species stay in Rust's
// grouped order. Fixed flags, velocities, and forces match bit for bit.
// A torn file and a null path are errors. RAII frees every handle.

#include "readcon-core.hpp"

#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <vector>

namespace {

uint64_t bits(double value) {
    uint64_t out = 0;
    std::memcpy(&out, &value, sizeof(out));
    return out;
}

void require(bool cond, const char *what) {
    if (!cond) {
        std::cerr << what << "\n";
        std::exit(1);
    }
}

struct Row {
    uint64_t z;
    double x, y, zpos;
    bool fx, fy, fz;
    uint64_t id;
    double mass;
    bool has_v;
    double vx, vy, vz;
    bool has_f;
    double ffx, ffy, ffz;
};

void check_atom(const readcon::Atom &got, const Row &expect) {
    require(got.atomic_number == expect.z, "species");
    require(bits(got.x) == bits(expect.x), "x");
    require(bits(got.y) == bits(expect.y), "y");
    require(bits(got.z) == bits(expect.zpos), "z");
    require(got.fixed_x == expect.fx && got.fixed_y == expect.fy && got.fixed_z == expect.fz,
            "fixed");
    require(got.atom_id == expect.id, "id");
    require(bits(got.mass) == bits(expect.mass), "mass");
    auto velocity = got.velocity();
    require(velocity.has_value() == expect.has_v, "velocity presence");
    if (expect.has_v) {
        require(bits((*velocity)[0]) == bits(expect.vx), "vx");
        require(bits((*velocity)[1]) == bits(expect.vy), "vy");
        require(bits((*velocity)[2]) == bits(expect.vz), "vz");
    }
    auto force = got.force();
    require(force.has_value() == expect.has_f, "force presence");
    if (expect.has_f) {
        require(bits((*force)[0]) == bits(expect.ffx), "fx");
        require(bits((*force)[1]) == bits(expect.ffy), "fy");
        require(bits((*force)[2]) == bits(expect.ffz), "fz");
    }
}

}  // namespace

int main() {
    const std::string units =
        std::string("{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\",\"time\":\"") +
        "(amu*angstrom^2/eV)^0.5\"}";
    readcon::ConFrameBuilder builder({10.5, 11.0, 12.25}, {90.0, 90.0, 120.0});
    builder.set_units(units);
    builder.add_atom("Cu", 0.0, -0.0, 1.0, {true, false, false}, 10, 63.546,
                     std::array<double, 3>{-0.0, 0.1, -0.2},
                     std::array<double, 3>{0.0, -0.0, 1.5});
    builder.add_atom("H", 1.25e-10, -1.0e20, 2.5, {false, true, false}, 11, 1.008,
                     std::array<double, 3>{1.0e-20, 0.0, -0.0},
                     std::array<double, 3>{-2.0, 3.0, -4.0});
    builder.add_atom("Cu", -0.0, 2.5, -3.5, {true, true, true}, 13, 63.546,
                     std::array<double, 3>{0.5, -0.5, 0.25},
                     std::array<double, 3>{1.0, 0.0, -1.0});
    auto frame = builder.build();

    // The builder groups by symbol, so the second Cu sits before H.
    const Row expect[] = {
        {29, 0.0, -0.0, 1.0, true, false, false, 10, 63.546, true, -0.0, 0.1, -0.2, true, 0.0,
         -0.0, 1.5},
        {29, -0.0, 2.5, -3.5, true, true, true, 13, 63.546, true, 0.5, -0.5, 0.25, true, 1.0, 0.0,
         -1.0},
        {1, 1.25e-10, -1.0e20, 2.5, false, true, false, 11, 1.008, true, 1.0e-20, 0.0, -0.0, true,
         -2.0, 3.0, -4.0},
    };
    require(frame.atoms().size() == 3, "grouped count");
    for (size_t i = 0; i < 3; ++i) {
        check_atom(frame.atoms()[i], expect[i]);
    }

    const auto dir = std::filesystem::temp_directory_path();
    const auto path = dir / "readcon-ffi-agreement.con";
    {
        std::vector<readcon::ConFrame> frames;
        frames.push_back(std::move(frame));
        readcon::ConFrameWriter writer(path);
        writer.extend(frames);
        writer.flush();
    }
    auto back = readcon::read_all_frames(path, 1);
    require(back.size() == 1, "frame count");
    require(back[0].atoms().size() == 3, "reread count");
    for (size_t i = 0; i < 3; ++i) {
        check_atom(back[0].atoms()[i], expect[i]);
    }
    std::filesystem::remove(path);

    const auto torn = dir / "readcon-ffi-agreement-torn.con";
    {
        std::ofstream out(torn);
        out << "torn\n{\"con_spec_version\":3}\n1.0\n";
    }
    bool failed = false;
    try {
        auto ignored = readcon::read_all_frames(torn);
        (void)ignored;
    } catch (const readcon::Error &) {
        failed = true;
    }
    require(failed, "truncated read must fail");
    std::filesystem::remove(torn);

    size_t count = 4;
    readcon::RKRConFrame **handles = readcon::rkr_read_all_frames(nullptr, &count);
    require(handles == nullptr, "null path");
    require(readcon::rkr_last_error()->code == readcon::RKR_STATUS_NULL_POINTER, "null status");
    readcon::free_rkr_frame(nullptr);
    readcon::free_c_frame(nullptr);
    readcon::free_rkr_frame_array(nullptr, 0);
    readcon::rkr_free_string(nullptr);
    return 0;
}
