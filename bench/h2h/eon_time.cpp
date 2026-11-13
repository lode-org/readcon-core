// Time the eOn client's .con read.
// The client loads frames with readcon::read_all_frames and copies each
// frame into Matter through eonc::io::con2matter.

#include "eon/ConFileIO.h"
#include "eon/Matter.h"
#include "eon/Parameters.h"
#include "eon/Potential.h"

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {

long status_kb(const char *key) {
    std::ifstream in("/proc/self/status");
    std::string line;
    const std::string prefix = std::string(key) + ":";
    while (std::getline(in, line)) {
        if (line.compare(0, prefix.size(), prefix) == 0) {
            return std::stol(line.substr(prefix.size()));
        }
    }
    return 0;
}

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

void write_dump(const std::string &dump_path, const std::vector<readcon::ConFrame> &frames) {
    std::ofstream out(dump_path, std::ios::binary);
    std::uint32_t magic = 0x31434F4Eu;
    std::uint32_t nframes = static_cast<std::uint32_t>(frames.size());
    out.write(reinterpret_cast<char *>(&magic), 4);
    out.write(reinterpret_cast<char *>(&nframes), 4);
    for (const auto &frame : frames) {
        const auto &atoms = frame.atoms();
        std::uint32_t natoms = static_cast<std::uint32_t>(atoms.size());
        out.write(reinterpret_cast<char *>(&natoms), 4);
        double cell[6] = {frame.cell()[0], frame.cell()[1], frame.cell()[2],
                          frame.angles()[0], frame.angles()[1], frame.angles()[2]};
        out.write(reinterpret_cast<char *>(cell), sizeof(cell));
        for (const auto &atom : atoms) {
            double mass = atom.mass;
            out.write(reinterpret_cast<char *>(&mass), 8);
        }
        for (const auto &atom : atoms) {
            double xyz[3] = {atom.x, atom.y, atom.z};
            out.write(reinterpret_cast<char *>(xyz), sizeof(xyz));
        }
    }
}

} // namespace

int main(int argc, char **argv) {
    if (argc != 4) {
        return 2;
    }
    const std::string cache = argv[1];
    const std::string path = argv[2];
    const std::string dump_path = argv[3];

    eonc::Parameters params;
    eonc::ParametersLoadAccess::potential_options(params).potential = eonc::PotType::LJ;
    auto pot = eonc::helpers::sharePotential(eonc::helpers::makePotential(eonc::PotType::LJ, params));
    eonc::Matter matter(pot, params);

    try {
        auto warmup = readcon::read_first_frame(path);
        eonc::io::con2matter(matter, warmup, nullptr);
    } catch (const std::exception &) {
        std::cout << "{\"status\":\"error\",\"error\":\"warmup\",\"wall_s\":null}\n";
        return 1;
    }
    if (cache == "cold") {
        drop_cache(path);
    } else {
        warm_file(path);
    }
    const int resident = pages_resident(path);
    if (cache == "cold" && resident != 0) {
        std::cout << "{\"status\":\"cache_fault\",\"error\":\"cold resident\",\"wall_s\":null,"
                     "\"pages_resident\":"
                  << resident << "}\n";
        return 1;
    }

    const long baseline = status_kb("VmRSS");
    const auto t0 = std::chrono::steady_clock::now();
    std::vector<readcon::ConFrame> frames;
    try {
        frames = readcon::read_all_frames(path);
        for (const auto &frame : frames) {
            if (!eonc::io::io_ok(eonc::io::con2matter(matter, frame, nullptr))) {
                std::cout << "{\"status\":\"error\",\"error\":\"con2matter\",\"wall_s\":null}\n";
                return 1;
            }
        }
    } catch (const std::exception &) {
        std::cout << "{\"status\":\"error\",\"error\":\"read\",\"wall_s\":null}\n";
        return 1;
    }
    const auto t1 = std::chrono::steady_clock::now();
    const double wall = std::chrono::duration<double>(t1 - t0).count();
    const long after = status_kb("VmRSS");
    const long peak = status_kb("VmHWM");
    write_dump(dump_path, frames);
    const int n_atoms = frames.empty() ? 0 : static_cast<int>(frames.front().atoms().size());
    std::cout << "{\"baseline_rss_bytes\":" << baseline * 1024 << ",\"error\":\"\",\"n_atoms\":" << n_atoms
              << ",\"n_frames\":" << frames.size() << ",\"pages_resident\":" << resident
              << ",\"pages_total\":0,\"peak_rss_bytes\":" << peak * 1024
              << ",\"reader_rss_bytes\":" << std::max(0L, after - baseline) * 1024
              << ",\"status\":\"ok\",\"wall_s\":" << wall << "}\n";
    return 0;
}
