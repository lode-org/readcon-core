// Spreads through the C++ builder, the Rust writer and the Rust parser:
// set per-atom and bulk root-mean-square spreads, build, read every frame
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
    0.125, 0.25,   0.5,     // Cu atom_id 0
    0.0,   0.0,    0.0,     // H  atom_id 1
    0.5,   0.0625, 0.125,   // Cu atom_id 2
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
    check(frame.has_spreads(), tag + ": has_spreads");
    check(!frame.has_forces(), tag + ": no forces section");
    const auto &atoms = frame.atoms();
    const std::size_t n = atoms.size();
    check(n == 3, tag + ": atom count");

    std::vector<double> copy(3 * n, -1.0);
    check(frame.copy_spreads(copy.data(), copy.size()) ==
              readcon::RKR_STATUS_SUCCESS,
          tag + ": copy_spreads status");
    std::size_t nn = 0;
    const double *ptr = frame.spreads_f64(&nn);
    check(ptr != nullptr && nn == n, tag + ": spreads_f64");
    readcon::RKRArrayView view = frame.spreads_view();
    check(view.data != nullptr && view.n == n && view.cols == 3,
          tag + ": spreads_view shape");

    for (std::size_t i = 0; i < n; ++i) {
        const auto want = expected_for_atom_id(atoms[i].atom_id);
        for (std::size_t k = 0; k < 3; ++k) {
            check(copy[3 * i + k] == want[k], tag + ": copy value");
            if (ptr)
                check(ptr[3 * i + k] == want[k], tag + ": f64 value");
        }
    }

    RKRDLManagedTensorVersioned *t = nullptr;
    check(frame.spreads_dlpack(&t) == readcon::RKR_STATUS_SUCCESS &&
              t != nullptr,
          tag + ": spreads_dlpack");
    if (t)
        readcon::rkr_dlpack_delete(t);
}

} // namespace

int main(int argc, char *argv[]) {
    try {
        // Absent section: accessors report SECTION_ABSENT, like forces.
        {
            auto b = make_builder();
            check(!b.get_atom_spread(0).has_value(),
                  "builder: no spread before set");
            check(b.spreads_data() == nullptr,
                  "builder: spreads_data null when absent");
            auto frame = b.build();
            check(!frame.has_spreads(), "absent: has_spreads");
            std::vector<double> buf(9);
            check(frame.copy_spreads(buf.data(), buf.size()) ==
                      readcon::RKR_STATUS_SECTION_ABSENT,
                  "absent: copy_spreads");
            RKRDLManagedTensorVersioned *t = nullptr;
            check(frame.spreads_dlpack(&t) ==
                      readcon::RKR_STATUS_SECTION_ABSENT,
                  "absent: spreads_dlpack");
        }

        // Per-atom setters.
        {
            auto b = make_builder();
            b.with_spread({kFlat[6], kFlat[7], kFlat[8]});
            b.set_atom_spread(0, {kFlat[0], kFlat[1], kFlat[2]});
            b.set_atom_spread(1, {0.75, 0.75, 0.75});
            b.clear_atom_spread(1);
            auto d1 = b.get_atom_spread(1);
            check(d1.has_value() && (*d1)[0] == 0.0 && (*d1)[2] == 0.0,
                  "builder: clear_atom_spread zeroes slot");
            auto d2 = b.get_atom_spread(2);
            check(d2.has_value() && (*d2)[1] == kFlat[7],
                  "builder: with_spread targets last atom");
            check_frame(b.build(), "per-atom");
        }

        // Bulk setter, then write with the Rust writer and parse back.
        auto b = make_builder();
        b.set_spreads_from_flat(kFlat);
        double *data = b.spreads_data();
        check(data != nullptr && data[3 * 2 + 1] == kFlat[7],
              "builder: spreads_data after bulk set");
        bool threw = false;
        try {
            b.set_spreads_from_flat({1.0, 2.0});
        } catch (const std::exception &) {
            threw = true;
        }
        check(threw, "builder: wrong-length bulk set throws");
        auto frame = b.build();
        check_frame(frame, "built");

        const std::filesystem::path out =
            argc > 1 ? std::filesystem::path(argv[1])
                     : std::filesystem::temp_directory_path() /
                           "readcon_cpp_spreads.con";
        {
            std::vector<readcon::ConFrame> frames;
            frames.push_back(std::move(frame));
            readcon::ConFrameWriter writer(out, 17);
            writer.extend(frames);
        }
        std::ifstream in(out);
        std::stringstream text;
        text << in.rdbuf();
        check(text.str().find("\"spreads\"") != std::string::npos,
              "file: sections declares spreads");
        check(text.str().find("Spreads of Component 2") !=
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
        std::cerr << failures << " spread check(s) failed\n";
        return 1;
    }
    std::cout << "cpp_spreads_roundtrip ok\n";
    return 0;
}
