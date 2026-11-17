// A NaN or infinite cell is refused by the C API and the C++ wrapper.
// Usage: test_cell_finite <scratch dir>
#include "readcon-core.hpp"

#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

using namespace readcon;

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__,        \
                         __LINE__, #cond);                                     \
            failures++;                                                        \
        }                                                                      \
    } while (0)

static const double NAN_VALUE = std::numeric_limits<double>::quiet_NaN();
static const double INF_VALUE = std::numeric_limits<double>::infinity();

static bool contains(const std::string &text, const char *needle) {
    return text.find(needle) != std::string::npos;
}

// rkr_frame_new returns NULL, sets a parse error, and names the field.
static void check_c_builder(const double *cell, const double *angles,
                            const char *field, const char *token) {
    rkr_clear_error();
    RKRConFrameBuilder *builder =
        rkr_frame_new(cell, angles, nullptr, nullptr, nullptr, nullptr);
    CHECK(builder == nullptr);
    const rkr_error *err = rkr_last_error();
    CHECK(err != nullptr);
    if (err == nullptr) {
        return;
    }
    CHECK(err->code == static_cast<int32_t>(RKR_STATUS_PARSE_ERROR));
    const std::string message = err->message != nullptr ? err->message : "";
    CHECK(contains(message, "NonFiniteValue"));
    const std::string named = std::string("cell field ") + field + " is " + token;
    CHECK(contains(message, named.c_str()));
    CHECK(!contains(message, "of frame"));
}

static void check_cpp_builder(const std::array<double, 3> &cell,
                              const std::array<double, 3> &angles,
                              const char *field, const char *token) {
    bool refused = false;
    try {
        readcon::ConFrameBuilder builder(cell, angles);
    } catch (const readcon::Error &error) {
        refused = true;
        CHECK(error.code == static_cast<int32_t>(RKR_STATUS_PARSE_ERROR));
        const std::string message = error.what();
        CHECK(contains(message, "NonFiniteValue"));
        const std::string named =
            std::string("cell field ") + field + " is " + token;
        CHECK(contains(message, named.c_str()));
    }
    CHECK(refused);
}

static std::string frame_text(const char *box_line) {
    return std::string("seed\n{\"con_spec_version\":2}\n") + box_line +
           "\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\n"
           "Coordinates of Component 1\n0 0 0 0 0\n";
}

static void write_file(const std::filesystem::path &path,
                       const std::string &text) {
    std::ofstream out(path, std::ios::binary);
    out << text;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: test_cell_finite <scratch>\n");
        return 2;
    }
    const std::filesystem::path dir(argv[1]);
    std::filesystem::create_directories(dir);

    const double good_cell[3] = {10.0, 11.0, 12.0};
    const double good_angles[3] = {90.0, 91.0, 92.0};
    {
        rkr_clear_error();
        RKRConFrameBuilder *builder = rkr_frame_new(
            good_cell, good_angles, nullptr, nullptr, nullptr, nullptr);
        CHECK(builder != nullptr);
        CHECK(rkr_last_error() == nullptr);
        free_rkr_frame_builder(builder);
    }

    {
        const double cell[3] = {10.0, NAN_VALUE, 12.0};
        check_c_builder(cell, good_angles, "cell[1]", "NaN");
        const double wide[3] = {INF_VALUE, 11.0, 12.0};
        check_c_builder(wide, good_angles, "cell[0]", "inf");
        const double angles[3] = {90.0, 91.0, -INF_VALUE};
        check_c_builder(good_cell, angles, "angles[2]", "-inf");
        const double nan_angles[3] = {NAN_VALUE, 91.0, 92.0};
        check_c_builder(good_cell, nan_angles, "angles[0]", "NaN");
    }

    {
        rkr_clear_error();
        RKRConFrameBuilder *builder =
            rkr_frame_new(nullptr, good_angles, nullptr, nullptr, nullptr, nullptr);
        CHECK(builder == nullptr);
        const rkr_error *err = rkr_last_error();
        CHECK(err != nullptr && err->code == static_cast<int32_t>(RKR_STATUS_NULL_POINTER));
    }

    check_cpp_builder({10.0, NAN_VALUE, 12.0}, {90.0, 90.0, 90.0}, "cell[1]", "NaN");
    check_cpp_builder({10.0, 11.0, INF_VALUE}, {90.0, 90.0, 90.0}, "cell[2]", "inf");
    check_cpp_builder({10.0, 11.0, 12.0}, {90.0, -INF_VALUE, 90.0}, "angles[1]", "-inf");

    // A finite cell is kept bit for bit through a write and a read.
    {
        const std::array<double, 3> cell = {10.123456789012345, 1.0 / 3.0, 7.5e-3};
        const std::array<double, 3> angles = {89.99999999999999, 120.00000000000001, 60.5};
        readcon::ConFrameBuilder builder(cell, angles);
        builder.add_atom("Cu", 0.0, 0.0, 0.0, false, 0, 63.546);
        std::vector<readcon::ConFrame> frames;
        frames.push_back(builder.build());
        const std::string text = readcon::write_frames_to_string(frames);
        const auto path = dir / "finite.con";
        write_file(path, text);
        const auto back = readcon::read_all_frames(path);
        CHECK(back.size() == 1);
        if (back.size() == 1) {
            CHECK(std::memcmp(back[0].cell().data(), cell.data(), sizeof cell) == 0);
            CHECK(std::memcmp(back[0].angles().data(), angles.data(), sizeof angles) == 0);
        }
    }

    // A file with a non-finite cell names the field and the frame.
    {
        const auto path = dir / "bad.con";
        write_file(path, frame_text("10 11 12") + frame_text("10 NaN 12"));
        bool refused = false;
        try {
            (void)readcon::read_all_frames(path);
        } catch (const readcon::Error &error) {
            refused = true;
            CHECK(error.code == static_cast<int32_t>(RKR_STATUS_PARSE_ERROR));
            CHECK(error.frame_index == 1);
            const std::string message = error.what();
            CHECK(contains(message, "NonFiniteValue"));
            CHECK(contains(message, "cell field boxl[1] of frame 1 is NaN"));
        }
        CHECK(refused);
    }

    if (failures != 0) {
        std::fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    return 0;
}
