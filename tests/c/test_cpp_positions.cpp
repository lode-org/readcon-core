// Coordinate column through the C++ wrapper.
// Usage: test_cpp_positions <repo root>

#include "readcon-core.hpp"

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__,        \
                         __LINE__, #cond);                                     \
            failures++;                                                        \
        }                                                                      \
    } while (0)

static void check_file(const std::filesystem::path &path, std::size_t frames,
                       std::size_t atoms) {
    auto block = readcon::read_positions(path, 1);
    CHECK(block.n_frames() == frames);
    CHECK(block.n_atoms() == atoms);
    CHECK(block.data() != nullptr);
    CHECK(block.size() == frames * atoms * 3);
    CHECK(std::isfinite(block.data()[0]));
    auto owned = readcon::read_all_frames(path, 1);
    CHECK(owned.size() == frames);
    std::size_t n_head = 0;
    const double *head = owned.front().xyz_f64(&n_head);
    CHECK(head != nullptr);
    CHECK(n_head == atoms);
    CHECK(head[0] == block.data()[0]);
    CHECK(head[1] == block.data()[1]);
    CHECK(head[2] == block.data()[2]);
    std::size_t n_tail = 0;
    const double *tail = owned.back().xyz_f64(&n_tail);
    CHECK(n_tail == atoms);
    const std::size_t last = block.size() - 3;
    CHECK(tail[n_tail * 3 - 3] == block.data()[last]);
    CHECK(tail[n_tail * 3 - 2] == block.data()[last + 1]);
    CHECK(tail[n_tail * 3 - 1] == block.data()[last + 2]);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 2;
    }
    const std::filesystem::path root = argv[1];
    try {
        check_file(root / "resources/test/tiny_cuh2.con", 1, 4);
        check_file(root / "resources/test/tiny_multi_cuh2.con", 2, 4);
    } catch (const std::exception &err) {
        std::fprintf(stderr, "exception: %s\n", err.what());
        return 1;
    }
    if (failures != 0) {
        std::fprintf(stderr, "%d checks failed\n", failures);
        return 1;
    }
    std::printf("cpp read_positions ok\n");
    return 0;
}
