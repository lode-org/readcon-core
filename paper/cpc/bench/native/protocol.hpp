// READY/GO protocol and checksums shared by the C++ readers of the performance records.
//
// Each reader runs its read once on WARM untimed, prints READY, waits for
// one line on stdin (the parent drops or primes the page cache meanwhile),
// then reads PATH. The read returns one object that owns the reader's frames
// and the per-frame records of the output contract. The clock runs twice:
// from GO until every frame is held, and over the release of that object.
// The checksums are computed between the two, with the clock stopped and
// every frame alive, and printed with both times as one JSON line, with the
// number of per-atom velocity property lookups the timed read made.
#pragma once

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

// Neumaier's compensated sum, so the float checksums do not depend on the
// order in which a reader visits the values.
struct Sum {
    double s = 0.0;
    double c = 0.0;
    void add(double x) {
        const double t = s + x;
        c += std::fabs(s) >= std::fabs(x) ? (s - t) + x : (x - t) + s;
        s = t;
    }
    double value() const { return s + c; }
};

struct Checksums {
    const char *contract = "moc";
    std::size_t frames = 0;
    std::size_t atoms = 0;
    Sum positions;
    Sum velocities;
    Sum cell;
    std::uint64_t n_fixed = 0;
    std::uint64_t sum_ids = 0;
    std::uint64_t sum_numbers = 0;
    std::uint64_t n_pbc = 0;
    std::uint64_t velocity_lookups = 0;

    void add3(Sum &sum, const double *v, std::size_t n_rows) {
        for (std::size_t i = 0; i < 3 * n_rows; ++i)
            sum.add(v[i]);
    }
};

// `read` returns a std::unique_ptr owning every frame and record of `path`;
// `check` turns it into checksums.
template <class Read, class Check>
int run_protocol(const char *path, const char *warm, unsigned threads, Read read, Check check) {
    using clock = std::chrono::steady_clock;
    try {
        auto kept = read(warm);
        (void)check(*kept);
    } catch (const std::exception &e) {
        std::fprintf(stderr, "warm-up failed: %s\n", e.what());
        return 1;
    }
    std::puts("READY");
    std::fflush(stdout);
    std::string go;
    std::getline(std::cin, go);
    const auto start = clock::now();
    decltype(read(path)) kept;
    try {
        kept = read(path);
    } catch (const std::exception &e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
    const auto parsed = clock::now();
    const Checksums o = check(*kept);
    const auto release = clock::now();
    kept.reset();
    const auto freed = clock::now();
    const double parse_s = std::chrono::duration<double>(parsed - start).count();
    const double free_s = std::chrono::duration<double>(freed - release).count();
    std::printf("{\"seconds\":%.9f,\"parse_seconds\":%.9f,\"free_seconds\":%.9f,\"contract\":\"%s\","
                "\"frames\":%zu,\"atoms\":%zu,\"sum_positions\":%.17g,\"sum_velocities\":%.17g,"
                "\"n_fixed\":%llu,\"sum_ids\":%llu,\"sum_numbers\":%llu,\"sum_cell\":%.17g,\"n_pbc\":%llu,"
                "\"velocity_lookups\":%llu,\"threads\":%u}\n",
                parse_s + free_s, parse_s, free_s, o.contract, o.frames, o.atoms, o.positions.value(),
                o.velocities.value(), static_cast<unsigned long long>(o.n_fixed),
                static_cast<unsigned long long>(o.sum_ids), static_cast<unsigned long long>(o.sum_numbers),
                o.cell.value(), static_cast<unsigned long long>(o.n_pbc),
                static_cast<unsigned long long>(o.velocity_lookups), threads);
    std::fflush(stdout);
    return 0;
}

// Contract argument shared by the readers: 1 for `moc`, 0 for `coords`, -1 otherwise.
inline int contract_of(const char *mode) {
    if (std::strcmp(mode, "moc") == 0)
        return 1;
    if (std::strcmp(mode, "coords") == 0)
        return 0;
    std::fprintf(stderr, "unknown contract %s\n", mode);
    return -1;
}
