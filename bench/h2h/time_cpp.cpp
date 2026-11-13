// C++ million-atom read and write through the header-only wrapper.
//
//   time_cpp read|write INPUT OUTPUT REPEATS

#include "readcon-core.hpp"

#include <chrono>
#include <cstdio>
#include <filesystem>
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
    const std::filesystem::path path = argv[2];
    const std::string out = argv[3];
    const int repeats = std::atoi(argv[4]);
    if (op == "read") {
        for (int i = 0; i < repeats + 1; ++i) {
            const double t0 = now_s();
            {
                auto block = readcon::read_positions(path, 1);
                if (block.n_frames() == 0 || block.n_atoms() == 0 || block.data() == nullptr) {
                    std::fprintf(stderr, "read failed\n");
                    return 1;
                }
                if (block.data()[0] != block.data()[0]) {
                    std::fprintf(stderr, "nan\n");
                    return 1;
                }
            }
            std::printf("%s %.9f\n", i == 0 ? "warmup" : "read", now_s() - t0);
        }
        return 0;
    }
    auto frames = readcon::read_all_frames(path, 1);
    for (int i = 0; i < repeats + 1; ++i) {
        const double t0 = now_s();
        std::remove(out.c_str());
        readcon::ConFrameWriter writer(out);
        writer.extend(frames);
        std::printf("%s %.9f\n", i == 0 ? "warmup" : "write", now_s() - t0);
    }
    return 0;
}
