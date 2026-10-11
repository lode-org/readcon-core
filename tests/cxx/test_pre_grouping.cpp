// pre_grouping_indices: unique ids sort, repeated ids keep input order.
// The C++ wrapper owns the returned vector and frees the C array.
#include "readcon-core.hpp"

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

static int expect_eq(const char *name, const std::vector<std::size_t> &got,
                      const std::vector<std::size_t> &want) {
    if (got != want) {
        std::cerr << "FAIL " << name << "\n";
        return 1;
    }
    return 0;
}

int main() {
    int nfail = 0;
    const std::vector<uint64_t> unique = {2, 0, 1};
    nfail += expect_eq("unique", readcon::pre_grouping_indices(unique), {1, 2, 0});

    const std::vector<uint64_t> repeated = {1, 1, 0};
    nfail += expect_eq("repeated", readcon::pre_grouping_indices(repeated), {0, 1, 2});

    const std::vector<uint64_t> empty;
    nfail += expect_eq("empty", readcon::pre_grouping_indices(empty), {});

    bool threw = false;
    try {
        readcon::pre_grouping_indices(static_cast<const uint64_t *>(nullptr), 3);
    } catch (const std::invalid_argument &) {
        threw = true;
    }
    if (!threw) {
        std::cerr << "FAIL null ids should throw\n";
        nfail++;
    }

    if (nfail != 0) {
        std::cerr << "c++ pre_grouping_indices: FAIL " << nfail << "\n";
        return 1;
    }
    std::cout << "c++ pre_grouping_indices: OK\n";
    return 0;
}
