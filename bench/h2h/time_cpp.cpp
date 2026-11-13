// C++ million-atom read and write through the header-only wrapper.
//
//   time_cpp read|write INPUT OUTPUT REPEATS

#include "readcon-core.hpp"

#include <chrono>
#include <cstdio>
#include <fstream>
#include <string>

static double now_s() {
    using clock = std::chrono::steady_clock;
    return std::chrono::duration<double>(clock::now().time_since_epoch()).count();
}

int main(int argc, char** argv) {
    if (argc != 5) {
        return 2;
    }
    const std::string op = argv[1];
    const std::string path = argv[2];
    const std::string out = argv[3];
    const int repeats = std::atoi(argv[4]);
    if (op == "read") {
        for (int i = 0; i < repeats + 1; ++i) {
            const double t0 = now_s();
            auto frames = readcon::read_all_frames(path, 1);
            if (frames.empty()) {
                std::fprintf(stderr, "read failed\n");
                return 1;
            }
            if (i > 0) {
                std::printf("read %.9f\n", now_s() - t0);
            }
        }
        std::printf("n_frames %zu\n", readcon::read_all_frames(path, 1).size());
        return 0;
    }
    auto frames = readcon::read_all_frames(path, 1);
    for (int i = 0; i < repeats; ++i) {
        const double t0 = now_s();
        readcon::ConFrameWriter writer(out);
        writer.extend(frames);
        std::printf("write %.9f\n", now_s() - t0);
    }
    return 0;
}
