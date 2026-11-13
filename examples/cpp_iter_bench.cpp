// Time a C++ iteration. usage: cpp_iter_bench walk|cell|atoms FILE ITERS
// prints: name ns iters
#include "readcon-core.hpp"

#include <chrono>
#include <iostream>
#include <string>

int main(int argc, char **argv) {
    if (argc != 4) {
        std::cerr << "usage: " << argv[0] << " walk|cell|atoms FILE ITERS\n";
        return 2;
    }
    const std::string mode = argv[1];
    const int iters = std::stoi(argv[3]);
    volatile std::size_t sink = 0;
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < iters; i++) {
        readcon::ConFrameIterator frames(argv[2]);
        for (auto &frame : frames) {
            if (mode == "cell")
                sink += static_cast<std::size_t>(frame.cell()[0]);
            else if (mode == "atoms")
                sink += frame.atoms().size();
            else
                sink += frame.index_natoms();
        }
    }
    const auto dt = std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now() - t0)
                        .count();
    std::cout << "cpp_" << mode << ' ' << dt << ' ' << iters << '\n';
    return sink == 0 ? 1 : 0;
}
