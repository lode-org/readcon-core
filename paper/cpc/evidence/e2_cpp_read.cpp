// Time the C++ call eOn 3.6.0 makes in client/ConFileIO.cpp.
// readcon::read_all_frames is a header over rkr_read_all_frames. There is
// no second CON parser in that client.

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>

#include "readcon-core.hpp"

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "usage: e2_cpp_read PATH [threads]\n";
        return 2;
    }
    const std::string path = argv[1];
    const std::size_t threads = argc > 2 ? static_cast<std::size_t>(std::strtoul(argv[2], nullptr, 10)) : 0;
    const auto start = std::chrono::steady_clock::now();
    std::vector<readcon::ConFrame> frames = threads == 0
                                                ? readcon::read_all_frames(path)
                                                : readcon::read_all_frames(path, threads);
    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    std::uint64_t tag = static_cast<std::uint64_t>(frames.size());
    if (!frames.empty() && frames.front().atom_count() > 0) {
        std::size_t n = 0;
        const double *xyz = frames.front().xyz_f64(&n);
        if (xyz != nullptr && n > 0) {
            tag ^= static_cast<std::uint64_t>(*reinterpret_cast<const std::uint64_t *>(xyz));
        }
    }
    if (tag == 0) {
        tag = 1;
    }
    std::cout << "{\"seconds\":" << seconds << ",\"frames\":" << frames.size() << ",\"tag\":" << tag
              << ",\"threads\":" << threads << "}\n";
    return frames.empty() ? 1 : 0;
}
