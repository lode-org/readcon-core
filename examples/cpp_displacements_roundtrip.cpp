// Displacements through the C++ builder, the Rust writer and the Rust
// parser: set per-atom and bulk displacements, build, read every frame
// accessor, write a .con file, parse it back and compare exactly.
#include "readcon-core.hpp"

#include <array>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
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

// Exactly representable at the writer precision used below.
const std::vector<double> kFlat = {
    0.125, -0.25,  0.5,     // Cu atom_id 0
    0.0,   0.0,    0.0,     // H  atom_id 1
    -0.5,  0.0625, -0.125,  // Cu atom_id 2
};

// Frame order is type-grouped (Cu, Cu, H); map row -> atom_id row in kFlat.
std::array<double, 3> expected_for_atom_id(uint64_t id) {
    return {kFlat[3 * id], kFlat[3 * id + 1], kFlat[3 * id + 2]};
}

readcon::ConFrameBuilder make_builder() {
    readcon::ConFrameBuilder b({10.0, 10.0, 10.0}, {90.0, 90.0, 90.0});
    b.add_atom("Cu", 0.0, 0.0, 0.0, {false, false, false}, 0, 63.546);
    b.add_atom("H", 1.0, 0.0, 0.0, {true, true, true}, 1, 1.008);
    b.add_atom("Cu", 2.0, 0.0, 0.0, {false, false, false}, 2, 63.546);
    return b;
}

void check_frame(const readcon::ConFrame &frame, const std::string &tag) {
    check(frame.has_displacements(), tag + ": has_displacements");
    check(!frame.has_forces(), tag + ": no forces section");
    const auto &atoms = frame.atoms();
    const std::size_t n = atoms.size();
    check(n == 3, tag + ": atom count");

    std::vector<double> copy(3 * n, -1.0);
    check(frame.copy_displacements(copy.data(), copy.size()) ==
              readcon::RKR_STATUS_SUCCESS,
          tag + ": copy_displacements status");
    std::size_t nn = 0;
    const double *ptr = frame.displacements_f64(&nn);
    check(ptr != nullptr && nn == n, tag + ": displacements_f64");
    readcon::RKRArrayView view = frame.displacements_view();
    check(view.data != nullptr && view.n == n && view.cols == 3,
          tag + ": displacements_view shape");

    for (std::size_t i = 0; i < n; ++i) {
        const auto want = expected_for_atom_id(atoms[i].atom_id);
        for (std::size_t k = 0; k < 3; ++k) {
            check(copy[3 * i + k] == want[k], tag + ": copy value");
            if (ptr)
                check(ptr[3 * i + k] == want[k], tag + ": f64 value");
        }
    }

    RKRDLManagedTensorVersioned *t = nullptr;
    check(frame.displacements_dlpack(&t) == readcon::RKR_STATUS_SUCCESS &&
              t != nullptr,
          tag + ": displacements_dlpack");
    if (t)
        readcon::rkr_dlpack_delete(t);
}

} // namespace

int main(int argc, char *argv[]) {
    try {
        // Absent section: accessors report SECTION_ABSENT, like forces.
        {
            auto b = make_builder();
            check(!b.get_atom_displacement(0).has_value(),
                  "builder: no displacement before set");
            check(b.displacements_data() == nullptr,
                  "builder: displacements_data null when absent");
            auto frame = b.build();
            check(!frame.has_displacements(), "absent: has_displacements");
            std::vector<double> buf(9);
            check(frame.copy_displacements(buf.data(), buf.size()) ==
                      readcon::RKR_STATUS_SECTION_ABSENT,
                  "absent: copy_displacements");
            RKRDLManagedTensorVersioned *t = nullptr;
            check(frame.displacements_dlpack(&t) ==
                      readcon::RKR_STATUS_SECTION_ABSENT,
                  "absent: displacements_dlpack");
        }

        // Per-atom setters.
        {
            auto b = make_builder();
            b.with_displacement({kFlat[6], kFlat[7], kFlat[8]});
            b.set_atom_displacement(0, {kFlat[0], kFlat[1], kFlat[2]});
            b.set_atom_displacement(1, {9.0, 9.0, 9.0});
            b.clear_atom_displacement(1);
            auto d1 = b.get_atom_displacement(1);
            check(d1.has_value() && (*d1)[0] == 0.0 && (*d1)[2] == 0.0,
                  "builder: clear_atom_displacement zeroes slot");
            auto d2 = b.get_atom_displacement(2);
            check(d2.has_value() && (*d2)[1] == kFlat[7],
                  "builder: with_displacement targets last atom");
            check_frame(b.build(), "per-atom");
        }

        // Bulk setter, then write with the Rust writer and parse back.
        auto b = make_builder();
        b.set_displacements_from_flat(kFlat);
        double *data = b.displacements_data();
        check(data != nullptr && data[3 * 2 + 1] == kFlat[7],
              "builder: displacements_data after bulk set");
        bool threw = false;
        try {
            b.set_displacements_from_flat({1.0, 2.0});
        } catch (const std::exception &) {
            threw = true;
        }
        check(threw, "builder: wrong-length bulk set throws");
        auto frame = b.build();
        check_frame(frame, "built");

        const std::filesystem::path out =
            argc > 1 ? std::filesystem::path(argv[1])
                     : std::filesystem::temp_directory_path() /
                           "readcon_cpp_displacements.con";
        {
            std::vector<readcon::ConFrame> frames;
            frames.push_back(std::move(frame));
            readcon::ConFrameWriter writer(out, 17);
            writer.extend(frames);
        }
        std::ifstream in(out);
        std::stringstream text;
        text << in.rdbuf();
        check(text.str().find("\"displacements\"") != std::string::npos,
              "file: sections declares displacements");
        check(text.str().find("Displacements of Component 2") !=
                  std::string::npos,
              "file: component label");

        std::size_t count = 0;
        for (const auto &parsed : readcon::ConFrameIterator(out.string())) {
            check_frame(parsed, "parsed");
            ++count;
        }
        check(count == 1, "parsed: one frame");
        if (argc <= 1)
            std::filesystem::remove(out);
    } catch (const std::exception &e) {
        std::cerr << "exception: " << e.what() << "\n";
        return 1;
    }

    if (failures != 0) {
        std::cerr << failures << " displacement check(s) failed\n";
        return 1;
    }
    std::cout << "cpp_displacements_roundtrip ok\n";
    return 0;
}
