// Time eOn's C++ ConFileIO on one file.
//
// Reads are readcon::read_all_frames plus con2matter on every frame, which is
// the client path. Writes load the first frame outside the clock, then time
// matter2con, matter2convel, or matter2xyz. There is no xyz reader.
//
// stdout: wall_s <seconds>
// A read also writes a dump the harness compares to the file.

#include "eon/ConFileIO.h"
#include "eon/Matter.h"
#include "eon/Parameters.h"
#include "eon/Potential.h"

#include <readcon-core.hpp>

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

void put_u32(std::ostream &out, std::uint32_t value) {
    out.write(reinterpret_cast<const char *>(&value), 4);
}

void put_u8(std::ostream &out, std::uint8_t value) { out.write(reinterpret_cast<const char *>(&value), 1); }

void put_doubles(std::ostream &out, const double *data, std::size_t count) {
    out.write(reinterpret_cast<const char *>(data), static_cast<std::streamsize>(count * sizeof(double)));
}

struct Client {
    eonc::Parameters parameters;
    std::shared_ptr<eonc::Potential> potential;
    eonc::Matter matter;

    Client()
        : potential(eonc::helpers::sharePotential(
              eonc::helpers::makePotential(eonc::PotType::LJ, parameters))),
          matter(potential, parameters) {}
};

void dump_matter(std::ostream &out, eonc::Matter &matter, bool velocities) {
    const long n = matter.numberOfAtoms();
    const Eigen::Matrix3d cell = matter.getCell();
    double lengths[6] = {cell(0, 0), cell(1, 1), cell(2, 2), 90.0, 90.0, 90.0};
    put_doubles(out, lengths, 6);
    const auto positions = matter.getPositions();
    std::vector<double> pos(static_cast<std::size_t>(n) * 3);
    for (long atom = 0; atom < n; ++atom) {
        pos[static_cast<std::size_t>(atom) * 3] = positions(atom, 0);
        pos[static_cast<std::size_t>(atom) * 3 + 1] = positions(atom, 1);
        pos[static_cast<std::size_t>(atom) * 3 + 2] = positions(atom, 2);
    }
    put_doubles(out, pos.data(), pos.size());
    const auto masses = matter.getMasses();
    std::vector<double> mass(static_cast<std::size_t>(n));
    for (long atom = 0; atom < n; ++atom) {
        mass[static_cast<std::size_t>(atom)] = masses(atom);
    }
    put_doubles(out, mass.data(), mass.size());
    for (long atom = 0; atom < n; ++atom) {
        const auto id = static_cast<std::int64_t>(matter.getAtomIndex(atom));
        out.write(reinterpret_cast<const char *>(&id), 8);
    }
    for (long atom = 0; atom < n; ++atom) {
        const auto mask = matter.getFixedMask(atom);
        std::uint8_t bits = 0;
        if (mask[0]) {
            bits |= 1;
        }
        if (mask[1]) {
            bits |= 2;
        }
        if (mask[2]) {
            bits |= 4;
        }
        put_u8(out, bits);
    }
    if (velocities) {
        const auto vel = matter.getVelocities();
        std::vector<double> row(static_cast<std::size_t>(n) * 3);
        for (long atom = 0; atom < n; ++atom) {
            row[static_cast<std::size_t>(atom) * 3] = vel(atom, 0);
            row[static_cast<std::size_t>(atom) * 3 + 1] = vel(atom, 1);
            row[static_cast<std::size_t>(atom) * 3 + 2] = vel(atom, 2);
        }
        put_doubles(out, row.data(), row.size());
    }
}

int read_file(const std::string &path, const std::string &dump_path) {
    const bool velocities = path.size() >= 7 && path.rfind(".convel") == path.size() - 7;
    Client client;
    auto &matter = client.matter;
    const auto t0 = std::chrono::steady_clock::now();
    const auto frames = readcon::read_all_frames(path);
    if (frames.empty()) {
        std::cerr << "no frames\n";
        return 1;
    }
    for (const auto &frame : frames) {
        if (!eonc::io::io_ok(eonc::io::con2matter(matter, frame, nullptr))) {
            std::cerr << "con2matter failed\n";
            return 1;
        }
    }
    const auto t1 = std::chrono::steady_clock::now();
    std::ofstream dump(dump_path, std::ios::binary);
    if (!dump) {
        std::cerr << "dump open failed\n";
        return 1;
    }
    const char magic[8] = {'E', 'O', 'N', 'S', 'M', 'F', '1', '\0'};
    dump.write(magic, 8);
    put_u32(dump, static_cast<std::uint32_t>(frames.size()));
    put_u32(dump, static_cast<std::uint32_t>(frames.front().atoms().size()));
    put_u8(dump, velocities ? 1 : 0);
    // The last con2matter left one frame in Matter. Replay outside the clock.
    for (const auto &frame : frames) {
        if (!eonc::io::io_ok(eonc::io::con2matter(matter, frame, nullptr))) {
            std::cerr << "con2matter replay failed\n";
            return 1;
        }
        dump_matter(dump, matter, velocities);
    }
    const double wall = std::chrono::duration<double>(t1 - t0).count();
    std::cout << "wall_s " << wall << "\n";
    return dump ? 0 : 1;
}

int write_file(const std::string &op, const std::string &input, const std::string &output) {
    Client client;
    auto &matter = client.matter;
    try {
        const auto frame = readcon::read_first_frame(input);
        if (!eonc::io::io_ok(eonc::io::con2matter(matter, frame, nullptr))) {
            std::cerr << "load failed\n";
            return 1;
        }
    } catch (const std::exception &exc) {
        std::cerr << exc.what() << "\n";
        return 1;
    }
    const auto t0 = std::chrono::steady_clock::now();
    eonc::io::IoStatus status = eonc::io::IoStatus::WriteError;
    if (op == "write-con") {
        status = eonc::io::matter2con(matter, output, false, nullptr);
    } else if (op == "write-convel") {
        status = eonc::io::matter2convel(matter, output);
    } else if (op == "write-xyz") {
        status = eonc::io::matter2xyz(matter, output, false);
    } else {
        std::cerr << "unknown write\n";
        return 2;
    }
    const auto t1 = std::chrono::steady_clock::now();
    if (!eonc::io::io_ok(status)) {
        std::cerr << "write failed\n";
        return 1;
    }
    const double wall = std::chrono::duration<double>(t1 - t0).count();
    std::cout << "wall_s " << wall << "\n";
    return 0;
}

} // namespace

int main(int argc, char **argv) {
    if (argc != 4) {
        std::cerr << "usage: eon_samefmt read|write-con|write-convel|write-xyz INPUT OUTPUT\n";
        return 2;
    }
    const std::string op = argv[1];
    try {
        if (op == "read") {
            return read_file(argv[2], argv[3]);
        }
        if (op == "write-con" || op == "write-convel" || op == "write-xyz") {
            return write_file(op, argv[2], argv[3]);
        }
    } catch (const std::exception &exc) {
        std::cerr << exc.what() << "\n";
        return 1;
    }
    std::cerr << "unknown op\n";
    return 2;
}
