// Time eOn's C++ CON reader and writer (client/ConFileIO.cpp).
//
// Read: readcon::read_all_frames through the readcon eOn links, then
// eonc::io::con2matter into Matter, then copy positions, masses, the
// per-axis fixed mask, velocities and the cell out of Matter.
// Write: unlink the destination, then matter2con or matter2convel.
// The clock excludes process startup and the one warmup frame.
// Cache preparation matches the Python tools: posix_fadvise DONTNEED
// or a full read, then mincore.

#include "eon/ConFileIO.h"
#include "eon/Matter.h"
#include "eon/Parameters.h"

#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#ifndef EON_TIMER_FLAGS
#define EON_TIMER_FLAGS "-O3"
#endif

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {

void drop_cache(const std::string &path) {
    int fd = open(path.c_str(), O_RDONLY);
    if (fd < 0) {
        return;
    }
    fsync(fd);
    posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);
    close(fd);
}

void warm_file(const std::string &path) {
    std::ifstream in(path, std::ios::binary);
    std::vector<char> buf(1 << 20);
    while (in) {
        in.read(buf.data(), static_cast<std::streamsize>(buf.size()));
    }
}

int pages_resident(const std::string &path) {
    int fd = open(path.c_str(), O_RDONLY);
    if (fd < 0) {
        return -1;
    }
    struct stat st;
    if (fstat(fd, &st) != 0 || st.st_size <= 0) {
        close(fd);
        return 0;
    }
    void *mapped = mmap(nullptr, static_cast<size_t>(st.st_size), PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (mapped == MAP_FAILED) {
        return -1;
    }
    const long page = sysconf(_SC_PAGESIZE);
    const size_t npages = (static_cast<size_t>(st.st_size) + static_cast<size_t>(page) - 1) /
                          static_cast<size_t>(page);
    std::vector<unsigned char> vec(npages);
    int rc = mincore(mapped, static_cast<size_t>(st.st_size), vec.data());
    munmap(mapped, static_cast<size_t>(st.st_size));
    if (rc != 0) {
        return -1;
    }
    int resident = 0;
    for (unsigned char byte : vec) {
        resident += byte & 1;
    }
    return resident;
}

struct FrameDump {
    std::uint32_t n_atoms = 0;
    int has_vel = 0;
    double cell[6]{};
    std::vector<double> masses;
    std::vector<std::uint8_t> fixed;
    std::vector<double> coords;
    std::vector<double> vels;
};

void capture(const eonc::Matter &matter, FrameDump &out) {
    const long n = matter.numberOfAtoms();
    out.n_atoms = static_cast<std::uint32_t>(n);
    const auto lengths_angles = eonc::io::cell_to_lengths_angles(matter);
    for (int i = 0; i < 3; ++i) {
        out.cell[i] = lengths_angles.first[static_cast<size_t>(i)];
        out.cell[3 + i] = lengths_angles.second[static_cast<size_t>(i)];
    }
    const auto masses = matter.getMasses();
    const auto &pos = matter.getPositions();
    const auto vel = matter.getVelocities();
    out.masses.resize(static_cast<size_t>(n));
    out.coords.resize(static_cast<size_t>(n) * 3);
    out.fixed.resize(static_cast<size_t>(n) * 3);
    out.vels.resize(static_cast<size_t>(n) * 3);
    out.has_vel = 0;
    for (long i = 0; i < n; ++i) {
        out.masses[static_cast<size_t>(i)] = masses(i);
        const auto mask = matter.getFixedMask(i);
        out.fixed[static_cast<size_t>(i) * 3] = static_cast<std::uint8_t>(mask[0]);
        out.fixed[static_cast<size_t>(i) * 3 + 1] = static_cast<std::uint8_t>(mask[1]);
        out.fixed[static_cast<size_t>(i) * 3 + 2] = static_cast<std::uint8_t>(mask[2]);
        for (int axis = 0; axis < 3; ++axis) {
            out.coords[static_cast<size_t>(i) * 3 + static_cast<size_t>(axis)] = pos(i, axis);
            const double v = vel(i, axis);
            out.vels[static_cast<size_t>(i) * 3 + static_cast<size_t>(axis)] = v;
            if (v != 0.0) {
                out.has_vel = 1;
            }
        }
    }
}

void write_dump(const std::string &path, const std::vector<FrameDump> &frames) {
    std::ofstream out(path, std::ios::binary);
    const std::uint32_t magic = 0x31434F4Eu;
    const std::uint32_t version = 2;
    const std::uint32_t nframes = static_cast<std::uint32_t>(frames.size());
    out.write(reinterpret_cast<const char *>(&magic), 4);
    out.write(reinterpret_cast<const char *>(&version), 4);
    out.write(reinterpret_cast<const char *>(&nframes), 4);
    for (const auto &frame : frames) {
        out.write(reinterpret_cast<const char *>(&frame.n_atoms), 4);
        std::uint32_t has_vel = static_cast<std::uint32_t>(frame.has_vel);
        out.write(reinterpret_cast<const char *>(&has_vel), 4);
        out.write(reinterpret_cast<const char *>(frame.cell), sizeof(frame.cell));
        out.write(reinterpret_cast<const char *>(frame.masses.data()),
                  static_cast<std::streamsize>(frame.masses.size() * sizeof(double)));
        out.write(reinterpret_cast<const char *>(frame.fixed.data()),
                  static_cast<std::streamsize>(frame.fixed.size()));
        out.write(reinterpret_cast<const char *>(frame.coords.data()),
                  static_cast<std::streamsize>(frame.coords.size() * sizeof(double)));
        if (frame.has_vel) {
            out.write(reinterpret_cast<const char *>(frame.vels.data()),
                      static_cast<std::streamsize>(frame.vels.size() * sizeof(double)));
        }
    }
}

void fail(const std::string &error) {
    std::cout << "{\"status\":\"error\",\"error\":\"" << error << "\",\"wall_s\":null}\n";
}

bool prepare_cache(const std::string &cache, const std::string &path, int &resident) {
    if (cache == "cold") {
        drop_cache(path);
    } else if (cache == "warm") {
        warm_file(path);
    } else {
        fail("cache");
        return false;
    }
    resident = pages_resident(path);
    if (cache == "cold" && resident != 0) {
        std::cout << "{\"status\":\"cache_fault\",\"error\":\"cold resident\",\"wall_s\":null,"
                     "\"pages_resident\":"
                  << resident << "}\n";
        return false;
    }
    return true;
}

eonc::Matter make_matter(eonc::Parameters &params) {
    return eonc::Matter(std::shared_ptr<eonc::Potential>(), params);
}

bool load_frames(eonc::Matter &matter, const std::string &path, std::vector<FrameDump> &dumps) {
    std::vector<readcon::ConFrame> frames;
    try {
        frames = readcon::read_all_frames(path);
    } catch (const std::exception &) {
        fail("read");
        return false;
    }
    dumps.clear();
    dumps.reserve(frames.size());
    for (const auto &frame : frames) {
        if (!eonc::io::io_ok(eonc::io::con2matter(matter, frame, nullptr))) {
            fail("con2matter");
            return false;
        }
        FrameDump dump;
        capture(matter, dump);
        dumps.push_back(std::move(dump));
    }
    return true;
}

}  // namespace

int main(int argc, char **argv) {
    std::string op = "read";
    int arg = 1;
    if (argc == 5 && (std::strcmp(argv[1], "read") == 0 || std::strcmp(argv[1], "write") == 0)) {
        op = argv[1];
        arg = 2;
    }
    if (argc - arg != 3) {
        return 2;
    }
    const std::string cache = argv[arg];
    const std::string path = argv[arg + 1];
    const std::string dest = argv[arg + 2];
    const bool convel = dest.size() >= 7 && dest.compare(dest.size() - 7, 7, ".convel") == 0;

    eonc::Parameters params;
    eonc::Matter matter = make_matter(params);

    try {
        auto warmup = readcon::read_first_frame(path);
        if (!eonc::io::io_ok(eonc::io::con2matter(matter, warmup, nullptr))) {
            fail("warmup");
            return 1;
        }
    } catch (const std::exception &) {
        fail("warmup");
        return 1;
    }

    int resident = 0;
    if (op == "read") {
        if (!prepare_cache(cache, path, resident)) {
            return 1;
        }
        const auto t0 = std::chrono::steady_clock::now();
        std::vector<FrameDump> dumps;
        if (!load_frames(matter, path, dumps)) {
            return 1;
        }
        const auto t1 = std::chrono::steady_clock::now();
        const double wall = std::chrono::duration<double>(t1 - t0).count();
        write_dump(dest, dumps);
        const int n_atoms = dumps.empty() ? 0 : static_cast<int>(dumps.front().n_atoms);
        std::cout << "{\"status\":\"ok\",\"op\":\"read\",\"wall_s\":" << wall
                  << ",\"n_atoms\":" << n_atoms << ",\"n_frames\":" << dumps.size()
                  << ",\"pages_resident\":" << resident
                  << ",\"flags\":\"" << EON_TIMER_FLAGS << "\"}\n";
        return 0;
    }

    // The structure is already in `matter` from the warmup frame. A
    // multi-frame file is loaded outside the clock so the sample is the write.
    std::vector<FrameDump> loaded;
    if (!load_frames(matter, path, loaded)) {
        return 1;
    }
    if (loaded.size() != 1) {
        fail("write expects one frame");
        return 1;
    }
    // load_frames left the last frame in matter. One frame, so that is the source.
    const auto t0 = std::chrono::steady_clock::now();
    if (unlink(dest.c_str()) != 0 && errno != ENOENT) {
        fail("unlink");
        return 1;
    }
    const eonc::io::IoStatus status =
        convel ? eonc::io::matter2convel(matter, dest)
               : eonc::io::matter2con(matter, dest, false, nullptr);
    const auto t1 = std::chrono::steady_clock::now();
    if (!eonc::io::io_ok(status)) {
        fail("write");
        return 1;
    }
    const double wall = std::chrono::duration<double>(t1 - t0).count();
    std::cout << "{\"status\":\"ok\",\"op\":\"write\",\"wall_s\":" << wall
              << ",\"n_atoms\":" << loaded[0].n_atoms << ",\"n_frames\":1"
              << ",\"flags\":\"" << EON_TIMER_FLAGS << "\"}\n";
    return 0;
}
